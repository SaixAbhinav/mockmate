# Inputs. All have sensible defaults so `terraform plan`/`apply` need no
# tfvars for the account this was bootstrapped in (356252962813, us-east-1).

variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name, used for default tags."
  type        = string
  default     = "mockmate"
}

variable "ecr_untagged_image_expiry_days" {
  description = "Days after which untagged images in the ECR repository expire."
  type        = number
  default     = 14
}
