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

# ADR 0032's outputs - the custom-domain cutover.

output "acm_validation_record" {
  description = "The DNS record proving domain ownership to ACM. Copy name/value into the is-a.dev register PR (see infra/README.md); empty when no custom_domain is set."
  value = length(aws_acm_certificate.frontend) == 0 ? null : {
    name  = one(aws_acm_certificate.frontend[0].domain_validation_options).resource_record_name
    type  = one(aws_acm_certificate.frontend[0].domain_validation_options).resource_record_type
    value = one(aws_acm_certificate.frontend[0].domain_validation_options).resource_record_value
  }
}

output "acm_certificate_status" {
  description = "ACM certificate status. Stays PENDING_VALIDATION until the is-a.dev PR merges and propagates; must read ISSUED before custom_domain_active can be flipped to true."
  value       = length(aws_acm_certificate.frontend) == 0 ? null : aws_acm_certificate.frontend[0].status
}

output "site_url" {
  description = "The URL to visit - the custom domain once it is active (ADR 0032), otherwise the CloudFront default name."
  value       = local.custom_domain_active ? "https://${var.custom_domain}" : "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

# PR 5's outputs (cloudwatch.tf) - see infra/README.md's Monitoring section.
output "sns_alerts_topic_arn" {
  description = "SNS topic ARN that every CloudWatch alarm notifies. No email subscription is created by Terraform - subscribe with `aws sns subscribe --topic-arn <this> --protocol email --notification-endpoint you@example.com` and confirm the email (see README)."
  value       = aws_sns_topic.alerts.arn
}

output "cloudwatch_dashboard_url" {
  description = "Console URL for the mockmate CloudWatch dashboard (Lambda/API Gateway/DynamoDB/CloudFront at a glance)."
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.mockmate.dashboard_name}"
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

output "github_plan_role_arn" {
  description = "IAM role ARN terraform-plan.yml assumes via OIDC on pull requests - read-only plus state-lock access (ADR 0031)."
  value       = aws_iam_role.github_plan.arn
}
