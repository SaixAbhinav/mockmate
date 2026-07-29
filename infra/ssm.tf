# Secret parameters (ADR 0029). SSM Parameter Store SecureString, not
# Secrets Manager - see ADR 0029's "Secrets" section (free vs. $0.40/mo
# each for no benefit at this scale).
#
# Terraform creates these with a placeholder value only. The real secret
# is set out-of-band after apply (see infra/README.md) and
# `ignore_changes = [value]` means Terraform never reads back, diffs, or
# prints the real value on subsequent plans.

resource "aws_ssm_parameter" "groq_api_key" {
  name        = "/mockmate/GROQ_API_KEY"
  description = "Groq API key (ADR 0013/0014 primary LLM provider). Real value set out-of-band after apply."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "mockmate-groq-api-key"
  }
}

resource "aws_ssm_parameter" "gemini_api_key" {
  name        = "/mockmate/GEMINI_API_KEY"
  description = "Gemini API key (ADR 0014 failover LLM provider). Real value set out-of-band after apply."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "mockmate-gemini-api-key"
  }
}
