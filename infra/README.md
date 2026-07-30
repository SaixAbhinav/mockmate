# infra/ — Terraform foundation (ADR 0029, PR 2a)

Foundation resources for the serverless AWS deploy: the DynamoDB session table,
the ECR repository, the Lambda execution IAM role, and the two SSM secret
parameters. Deliberately **no Lambda function and no API Gateway** here - those
depend on a built container image and land in PR 2b. Everything in this
directory is independently `apply`-able on its own.

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

## CI/CD (PR 4)

`infra/iam_github_oidc.tf` defines the GitHub Actions OIDC provider and the
`mockmate-github-deploy` IAM role two workflows assume to run this stack from
CI: [`.github/workflows/terraform-plan.yml`](../.github/workflows/terraform-plan.yml)
(`terraform plan` on every PR touching `infra/`, `backend/`, `frontend/`, or the
workflows themselves) and
[`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) (build +
push the backend image, `terraform apply`, then build + sync the frontend and
invalidate CloudFront, on every push to `main`).

**No AWS access keys are stored in GitHub.** Both workflows authenticate via
OIDC federation - GitHub issues each job a short-lived OIDC token, and
`aws-actions/configure-aws-credentials` exchanges it for temporary STS
credentials by assuming `mockmate-github-deploy`
(`sts:AssumeRoleWithWebIdentity`). Nothing long-lived ever leaves AWS.

**One-time bootstrap - this can't be turned on from CI itself.** The OIDC
provider and the deploy role have to exist *before* any workflow can assume
the role, so the `terraform apply` that first creates
`infra/iam_github_oidc.tf`'s resources must be run **locally**, the same way
every other resource in this directory was bootstrapped. Once that one apply
has run, every later plan/apply - including changes to this same file - can
go through the workflows normally.

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
