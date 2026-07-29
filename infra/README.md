# infra/ — Terraform (ADR 0029, PR 2a + PR 2b)

Terraform for the serverless AWS deploy. PR 2a laid the foundation: the
DynamoDB session table (`dynamodb.tf`), the ECR repository (`ecr.tf`), the
Lambda execution IAM role (`iam.tf`), and the two SSM secret parameters
(`ssm.tf`) - deliberately no compute yet, since none of it depends on a
built container image. PR 2b adds the compute that does: the Lambda
function (`lambda.tf`) and the API Gateway HTTP API in front of it
(`apigateway.tf`), both referencing PR 2a's resources rather than
duplicating them. Everything in this directory is `apply`-able together as
one unit.

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
   `backend/`, so build from there):

   ```bash
   docker build -t mockmate .
   ```

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
