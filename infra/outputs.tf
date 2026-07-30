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

# PR 2b's own output - the backend URL for the frontend (PR 3) and for a
# post-apply smoke test (see infra/README.md).
output "api_endpoint" {
  description = "Invoke URL of the HTTP API's $default stage - the backend's public base URL. Append /api/health for a smoke test."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

# PR 3's outputs - the frontend deploy runbook (README.md) consumes these:
# the bucket name to `aws s3 sync` into, the domain to visit, and the
# distribution id to invalidate after each new build.
output "frontend_bucket_name" {
  description = "S3 bucket name for the built SPA - sync `frontend/dist` here (see README's deploy runbook)."
  value       = aws_s3_bucket.frontend.bucket
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain name - the URL to visit. Single origin: '/' serves the SPA from S3, '/api/*' forwards to the API Gateway HTTP API above, so there is no production CORS."
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution id - pass to `aws cloudfront create-invalidation --distribution-id <this> --paths \"/*\"` after each frontend redeploy."
  value       = aws_cloudfront_distribution.frontend.id
}
