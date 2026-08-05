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

variable "image_tag" {
  description = <<-EOT
    Tag (within the ecr.tf repository) of the backend image the Lambda
    function (lambda.tf) runs. The user pushes the image first, then
    `terraform apply` - see infra/README.md's deploy runbook. Defaults to
    "latest"; pass a specific tag/digest-derived tag to pin a release.
  EOT
  type        = string
  default     = "latest"
}
