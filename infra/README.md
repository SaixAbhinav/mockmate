# infra/ — Terraform (ADR 0029, PR 2a + PR 2b + PR 3 + PR 5)

Terraform for the serverless AWS deploy. PR 2a laid the foundation: the
DynamoDB session table (`dynamodb.tf`), the ECR repository (`ecr.tf`), the
Lambda execution IAM role (`iam.tf`), and the two SSM secret parameters
(`ssm.tf`) - deliberately no compute yet, since none of it depends on a
built container image. PR 2b adds the compute that does: the Lambda
function (`lambda.tf`) and the API Gateway HTTP API in front of it
(`apigateway.tf`), both referencing PR 2a's resources rather than
duplicating them. PR 3 adds the frontend: a private S3 bucket
(`s3_frontend.tf`) and a CloudFront distribution (`cloudfront.tf`) that is
the single origin the browser talks to - `/` serves the SPA from S3,
`/api/*` forwards to PR 2b's API Gateway. PR 5 adds monitoring
(`cloudwatch.tf`): an SNS alerts topic, one dashboard, and five alarms
across all of the above, staying inside the free tier. Everything in this
directory is `apply`-able together as one unit.

See [ADR 0029](../docs/decisions/0029-serverless-aws-deploy.md) for the full
design rationale.

## Remote state backend

State lives in S3 (`mockmate-tfstate-356252962813`, key
`mockmate/terraform.tfstate`, region `us-east-1`), locked via the DynamoDB
table `mockmate-tflock` (see `versions.tf`). **Both the bucket and the lock
table were created out-of-band, before this Terraform existed** - this is the
standard chicken-and-egg with S3 backends: Terraform cannot create the
backend it is about to start storing its own state in. There is no
bootstrap `.tf` for them in this repo; they're accounted for here as a fact
of the environment, not something `terraform apply` will ever (re)create.

## Commands

From this directory:

```bash
# One-time (or after changing backend/provider config):
terraform init

# Confirms the configuration is syntactically/internally valid:
terraform validate

# Shows what would change - should be a clean create-only plan on first run:
terraform plan

# Applies it:
terraform apply
```

All variables (`region`, `project`, `ecr_untagged_image_expiry_days`) default
to values that match the account this was bootstrapped in, so no `.tfvars`
file is required for a standard apply.

## Setting the real secrets

Terraform creates `/mockmate/GROQ_API_KEY` and `/mockmate/GEMINI_API_KEY` as
SecureString parameters with a `"REPLACE_ME"` placeholder value, and
`lifecycle { ignore_changes = [value] }` so Terraform never manages, diffs, or
prints the real secret. Set the real values **after** `terraform apply`,
out-of-band, with the AWS CLI:

```bash
aws ssm put-parameter \
  --name /mockmate/GROQ_API_KEY \
  --type SecureString \
  --value <your-groq-key> \
  --overwrite

aws ssm put-parameter \
  --name /mockmate/GEMINI_API_KEY \
  --type SecureString \
  --value <your-gemini-key> \
  --overwrite
```

**This must happen before PR 2b's Lambda is invoked** - the function reads
both parameters at startup (mirroring today's `.env`-based
`GROQ_API_KEY`/Gemini key), and a `"REPLACE_ME"` value will fail provider
calls, not fail to start.

## What PR 2b consumes

PR 2b (Lambda + API Gateway) reads this PR's outputs: the ECR repository URL
to know where to push the backend image, the DynamoDB table name/ARN, the
Lambda execution role ARN, and the two SSM parameter names. Run
`terraform output` after `apply` to see them.

## IAM scope

The Lambda execution role is granted, on this table's ARN only:
`dynamodb:GetItem`, `PutItem`, `DeleteItem` - exactly the three actions
`DynamoDBSessionStore` (`backend/app/session_store.py`) calls, no
`Query`/`Scan`/`UpdateItem`. It also gets `ssm:GetParameter`/`GetParameters`
scoped to the two secret parameter ARNs, plus `kms:Decrypt` on the account's
default SSM key (`alias/aws/ssm`, resolved via data source) so SecureString
reads can actually decrypt. Plus the AWS-managed
`AWSLambdaBasicExecutionRole` for CloudWatch Logs.

## Deploying the backend (PR 2b: Lambda + API Gateway)

`lambda.tf` and `apigateway.tf` put the backend on Lambda behind an API
Gateway HTTP API, running the repo-root `Dockerfile` (adapted with the [AWS
Lambda Web Adapter](https://github.com/aws/aws-lambda-web-adapter) so the
same image still runs unchanged on Render/locally - see the Dockerfile's
top comment). The Lambda function (`aws_lambda_function.backend`) is a
`package_type = "Image"` function pointing at a tag in PR 2a's ECR repo, so
**the image must exist in ECR before `terraform apply` can create (or
update) the function that references it.**

Run these in order, from the repo root unless noted:

1. **Build the image** (Dockerfile lives at the repo root and `COPY`s
   `backend/`, so build from there). Use `--provenance=false` and pin
   `--platform linux/amd64`:

   ```bash
   docker buildx build --provenance=false --platform linux/amd64 -t mockmate:latest --load .
   ```

   > **Why not a plain `docker build`?** Modern Docker (BuildKit) attaches
   > provenance/SBOM attestations by default, which pushes an OCI *image index*
   > that AWS Lambda rejects with `InvalidParameterValueException: The image
   > manifest, config or layer media type ... is not supported`.
   > `--provenance=false` pushes a single-arch image manifest Lambda accepts;
   > `--platform linux/amd64` matches the function's `architectures = ["x86_64"]`.
   > The PR 4 CI build must pass the same flags.

2. **Log in to ECR** (credentials from your AWS profile; region/account are
   fixed for this project):

   ```bash
   aws ecr get-login-password --region us-east-1 \
     | docker login --username AWS --password-stdin 356252962813.dkr.ecr.us-east-1.amazonaws.com
   ```

3. **Tag and push** to the repository `ecr.tf` created:

   ```bash
   docker tag mockmate:latest 356252962813.dkr.ecr.us-east-1.amazonaws.com/mockmate:latest
   docker push 356252962813.dkr.ecr.us-east-1.amazonaws.com/mockmate:latest
   ```

4. **Apply the Terraform** (from `infra/`) - creates/updates the Lambda
   function and the API Gateway HTTP API in front of it:

   ```bash
   terraform apply
   ```

5. **Smoke test** with the `api_endpoint` output:

   ```bash
   curl "$(terraform output -raw api_endpoint)/api/health"
   ```

### Redeploying after a code change

Two ways to ship a new image, both valid:

- **Rebuild → push → `terraform apply`** (steps 1-4 above again). Pushing
  `:latest` again changes the image digest, which Terraform detects as a
  change to `image_uri` and updates the function in place. This is the
  "normal" path and is what a human runs; PR 4 automates it as CI.
- **`aws lambda update-function-code`** - faster for an ad-hoc redeploy
  (skips a Terraform run), but drifts Terraform's state (the function's
  running image no longer matches what `plan` thinks is deployed) until the
  next `apply` reconciles it. Fine for quick iteration, not a substitute for
  step 4 before considering a change actually shipped.

### Why a 504 from API Gateway is expected, not a bug

API Gateway HTTP API integrations cap out at roughly 30 seconds regardless
of what's configured. A full Evaluation is ~9 LLM calls and can run longer
than that. `aws_lambda_function.backend` sets `timeout = 60` specifically
so the Lambda invocation itself keeps running past the gateway's own
timeout: whichever request wins `claim_evaluation`'s atomic guard
(`DynamoDBSessionStore`) still finishes and **caches** the Evaluation, even
though the client that made that particular HTTP request already got a 504.
The frontend's retry (or the losing request's poll) then reads the cached
Evaluation quickly. This is ADR 0029's "Race A" and is by design - don't
try to "fix" it by raising API Gateway's timeout further; it can't go past
its own cap.

## Deploying the frontend (PR 3: S3 + CloudFront)

`s3_frontend.tf` and `cloudfront.tf` put the built React SPA behind
CloudFront, with CloudFront also fronting PR 2b's API Gateway at `/api/*`.
This makes CloudFront the app's **single origin**: the browser only ever
talks to the CloudFront domain, so the frontend's relative `/api/...` calls
(`frontend/src/api.js`) keep working unchanged and there is **no production
CORS** - the same property ADR 0025's Render rewrite held, preserved across
the AWS cutover. There is no frontend code change in this PR:
`VITE_API_BASE` stays unset, exactly like local dev (Vite's own `/api`
proxy in `vite.config.js`).

The S3 bucket is private - it has no website hosting, no public ACLs, and
its bucket policy only allows the CloudFront service principal, scoped by
`AWS:SourceArn` to this one distribution (Origin Access Control). There is
no path that reaches the bucket except through CloudFront.

Run these in order, from the repo root unless noted:

1. **Apply the Terraform** - creates the S3 bucket and the CloudFront
   distribution. `wait_for_deployment` defaults to `true`, so `apply` blocks
   until the distribution reaches `Deployed` status - expect this step to take
   a few minutes on first apply. (`-chdir=infra` so every step in this section
   runs from the repo root):

   ```bash
   terraform -chdir=infra apply
   ```

2. **Build the SPA**:

   ```bash
   npm --prefix frontend install
   npm --prefix frontend run build
   ```

   Outputs to `frontend/dist`.

3. **Upload the build to S3**, using the `frontend_bucket_name` output:

   ```bash
   aws s3 sync frontend/dist "s3://$(terraform -chdir=infra output -raw frontend_bucket_name)" --delete
   ```

4. **Invalidate the CloudFront cache** so the new build is visible
   immediately instead of waiting out the cache policy's TTL, using the
   `cloudfront_distribution_id` output:

   ```bash
   aws cloudfront create-invalidation \
     --distribution-id "$(terraform -chdir=infra output -raw cloudfront_distribution_id)" \
     --paths "/*"
   ```

5. **Visit the site**, using the `cloudfront_domain` output:

   ```bash
   echo "https://$(terraform -chdir=infra output -raw cloudfront_domain)"
   ```

   The SPA loads from S3, and its `/api/*` calls hit the Lambda through the
   same origin - no CORS involved, matching local dev.

### Redeploying the frontend after a code change

Steps 2-4 above, in order: **rebuild → `s3 sync` → invalidate**. No
`terraform apply` is needed unless the CloudFront/S3 config itself changed.
PR 4 automates this sequence as CI.

### Cutover note

Done. The distribution is live, the frontend is served from it, and the AWS
deploy has superseded
[ADR 0025](../docs/decisions/0025-deploy-render-static-plus-api.md)'s Render
host in full — both ADRs' statuses and the decisions index say so. Render stays
documented as the fallback, not the live host.

## Custom domain (ADR 0032)

`acm.tf` plus the guarded `aliases`/`viewer_certificate` wiring in
`cloudfront.tf` put the app at **`https://callback.is-a.dev`** instead of
the AWS-assigned `d1ukk616lu5bcc.cloudfront.net`. DNS is hosted free by
[is-a.dev](https://github.com/is-a-dev/register), whose records are added
by **pull request to their repo** - which is why the cutover is two
applies rather than one. See
[ADR 0032](../docs/decisions/0032-custom-domain-free-subdomain.md) for the
reasoning; the mechanics are below.

Two variables gate it (`variables.tf`):

| Variable | Default | Effect |
|---|---|---|
| `custom_domain` | `callback.is-a.dev` | Creates the ACM certificate and outputs its validation record. Attaches nothing. `""` disables the domain entirely. |
| `custom_domain_active` | `false` | Attaches the alias + certificate to the distribution. Flip only once the certificate reads `ISSUED`. |

While `custom_domain_active` is `false`, the distribution serves its
default `*.cloudfront.net` certificate exactly as before - so a stalled
is-a.dev PR is a no-op, not an outage.

### Phase 1 - create the certificate (done by merging to `main`)

`deploy.yml` applies it. Then read the record ACM wants:

```bash
terraform -chdir=infra output -json acm_validation_record
```

### Phase 2 - get the records into is-a.dev

Open a PR against [`is-a-dev/register`](https://github.com/is-a-dev/register)
adding **two** files under `domains/`:

`domains/callback.json` - the site itself:

```json
{
  "owner": { "username": "SaixAbhinav" },
  "records": { "CNAME": "d1ukk616lu5bcc.cloudfront.net" }
}
```

`domains/_<hash>.callback.json` - the ACM validation record, where
`_<hash>` and the CNAME value both come from the `acm_validation_record`
output above (strip the trailing `.is-a.dev.` from the record name to get
the filename):

```json
{
  "owner": { "username": "SaixAbhinav" },
  "records": { "CNAME": "_<hash>.<something>.acm-validations.aws" }
}
```

> **Both files must carry the same `owner.username`.** Their test suite
> enforces that a nested subdomain (`_hash.callback`) is owned by the same
> user as its parent (`callback`), and the PR fails CI otherwise. An
> `owner.email` field is conventional in their repo but not required -
> omit it if you'd rather not publish an address.

### Phase 3 - activate

Once that PR merges and DNS propagates, confirm ACM has issued:

```bash
terraform -chdir=infra output -raw acm_certificate_status
```

When it reads `ISSUED`, set `custom_domain_active = true` (in
`variables.tf`'s default, or via `-var`) and apply. `terraform output -raw
site_url` then prints the custom domain. If you flip it too early,
`cloudfront.tf`'s precondition stops the apply with a message saying so
rather than failing inside the CloudFront API.

> **Do not delete the validation record after issuance.** ACM re-validates
> through that same CNAME to auto-renew the certificate. Removing it once
> the site is live doesn't break anything immediately - it breaks the
> renewal, quietly, up to a year later.

## Monitoring (PR 5)

`cloudwatch.tf` adds one SNS topic, one dashboard, and five alarms - all
inside ADR 0029's near-free bound (1 of 3 free dashboards, 5 of 10 free
alarms).

### Dashboard

`terraform output cloudwatch_dashboard_url` prints the console link
directly (constructed from the dashboard's own name, not hard-coded). It
shows four rows, two widgets each:

- **Lambda** - Invocations/Errors/Throttles, and Duration (avg + p99).
- **API Gateway** - Count/4xx/5xx, and Latency (avg).
- **DynamoDB** - Consumed read/write capacity, and read/write throttle events.
- **CloudFront** - Requests, and 4xx/5xx error rate.

### Alarms

All five notify the same SNS topic (`sns_alerts_topic_arn` output) on both
`ALARM` and `OK`, with `treat_missing_data = "notBreaching"` so a quiet
period never itself pages anyone:

| Alarm | Fires when |
|---|---|
| `mockmate-lambda-errors` | Lambda `Errors` sum > 0 in two consecutive 5-minute periods |
| `mockmate-lambda-throttles` | Lambda `Throttles` sum > 0 in two consecutive 5-minute periods |
| `mockmate-lambda-duration-p99` | Lambda `Duration` p99 > 55s (5s inside the 60s function timeout - see `lambda.tf`) |
| `mockmate-apigateway-5xx` | API Gateway `5xx` sum > 5 in a 5-minute period |
| `mockmate-dynamodb-throttles` | DynamoDB `ReadThrottleEvents + WriteThrottleEvents` (metric math, one alarm for both) > 0 in a 5-minute period |

### Opting in to email alerts (one-time, out-of-band)

Terraform deliberately creates **no** `aws_sns_topic_subscription` - an
email subscription sits `PENDING` until a human clicks the confirmation
link AWS sends, which isn't something `apply` can do for you. Subscribe
once, after `apply`:

```bash
aws sns subscribe \
  --topic-arn "$(terraform output -raw sns_alerts_topic_arn)" \
  --protocol email \
  --notification-endpoint you@example.com
```

Then click the confirmation link in the email AWS sends. Until confirmed,
the subscription stays `PendingConfirmation` and alarms notify no one.

### Staying inside the free tier

One dashboard (3 free), five alarms (10 free), one SNS topic and email
subscription (both free), and the CloudWatch metrics themselves (all
listed here are standard, not the paid detailed/high-resolution kind).
Nothing in this file changes ADR 0029's ~$0/month bound.

## CI/CD (PR 4, hardened by ADR 0031)

`infra/iam_github_oidc.tf` defines the GitHub Actions OIDC provider and the
**two** IAM roles the workflows assume to run this stack from CI - one per
workflow, with deliberately different power (ADR 0031):

| Workflow | Role | Trust (`sub`) | Permissions |
|---|---|---|---|
| [`terraform-plan.yml`](../.github/workflows/terraform-plan.yml) — `terraform plan` on every PR touching `infra/`, `backend/`, `frontend/`, or the workflows | `mockmate-github-plan` | `repo:SaixAbhinav/mockmate:pull_request` | `ReadOnlyAccess` + state lock + `kms:Decrypt` |
| [`deploy.yml`](../.github/workflows/deploy.yml) — build + push the image, `terraform apply`, build + sync the frontend, invalidate CloudFront, on every push to `main` | `mockmate-github-deploy` | `repo:SaixAbhinav/mockmate:ref:refs/heads/main` | `PowerUserAccess` + scoped IAM top-up |

The split exists because PR workflows run the workflow definition from the
PR's own branch: if that job could assume a `PowerUserAccess` role, anyone
who could open a PR could edit the workflow into arbitrary AWS access. Plans
only read, so the plan role only reads. Both trust conditions are
`StringEquals` - no wildcard `sub` remains on either role.

**No AWS access keys are stored in GitHub.** Both workflows authenticate via
OIDC federation - GitHub issues each job a short-lived OIDC token, and
`aws-actions/configure-aws-credentials` exchanges it for temporary STS
credentials by assuming the role above
(`sts:AssumeRoleWithWebIdentity`). Nothing long-lived ever leaves AWS.

> **Gotcha when editing these trust policies.** Both condition keys (`aud`
> and `sub`) must sit *inside* the `StringEquals` block. A key placed
> directly under `Condition` is parsed as an operator name and IAM rejects
> the whole document with `MalformedPolicyDocument: Invalid condition
> prefix`. `terraform validate` does **not** catch this - the config is
> valid HCL and valid JSON, so it only fails at apply time.

**One-time bootstrap - this can't be turned on from CI itself.** A role has
to exist *before* any workflow can assume it, so the `terraform apply` that
first creates it must be run **locally**. This applies to any *new* role
here, not just the original two resources: adding `mockmate-github-plan`
(ADR 0031) hit the same wall, because the PR introducing it referenced the
role in `terraform-plan.yml` before the role existed - the same way every
other resource in this directory was bootstrapped. Once that one apply has
run, every later plan/apply - including changes to this same file - can go
through the workflows normally.

**Merge-order caveat.** PR 4 must merge **after** PR 2b (Lambda + API
Gateway, #42) and PR 3 (S3 + CloudFront, #43). `deploy.yml` assumes the full
stack's outputs exist (`ecr_repository_url`, `api_endpoint`,
`frontend_bucket_name`, `cloudfront_distribution_id`, `cloudfront_domain`) -
its first run against `main` only succeeds once all of those are real.

**Supersedes the manual runbook.** Once merged and bootstrapped, pushing to
`main` is the deploy path; the manual `docker build`/`terraform apply`/`aws s3
sync` steps described elsewhere in this README stay documented as the
fallback (e.g. for a local `apply` while iterating, or if CI is down), not
the everyday path.
