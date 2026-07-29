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
