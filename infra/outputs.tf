# Consumed by PR 2b (Lambda + API Gateway).

output "ecr_repository_url" {
  description = "ECR repository URL - the backend image's push target."
  value       = aws_ecr_repository.backend.repository_url
}

output "dynamodb_table_name" {
  description = "DynamoDB table name (matches MOCKMATE_DDB_TABLE's default in session_store.py)."
  value       = aws_dynamodb_table.sessions.name
}

output "dynamodb_table_arn" {
  description = "DynamoDB table ARN."
  value       = aws_dynamodb_table.sessions.arn
}

output "lambda_execution_role_arn" {
  description = "IAM role ARN the PR 2b Lambda function should assume."
  value       = aws_iam_role.lambda_exec.arn
}

output "groq_api_key_parameter_name" {
  description = "SSM parameter name holding the Groq API key. Set the real value out-of-band (see README) before the Lambda depends on it."
  value       = aws_ssm_parameter.groq_api_key.name
}

output "gemini_api_key_parameter_name" {
  description = "SSM parameter name holding the Gemini API key. Set the real value out-of-band (see README) before the Lambda depends on it."
  value       = aws_ssm_parameter.gemini_api_key.name
}

# Consumed by PR 4 (GitHub Actions OIDC CI/CD) - not by the workflows
# themselves (they hardcode the role ARN so they can assume it before any
# `terraform output` is possible), but useful for verifying what got
# created after the one-time local bootstrap apply.
output "github_deploy_role_arn" {
  description = "IAM role ARN GitHub Actions assumes via OIDC to plan/apply this stack."
  value       = aws_iam_role.github_deploy.arn
}

output "github_oidc_provider_arn" {
  description = "The GitHub Actions OIDC identity provider's ARN."
  value       = aws_iam_openid_connect_provider.github.arn
}
