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

variable "custom_domain" {
  description = <<-EOT
    Custom domain for the CloudFront distribution (ADR 0032). Setting it
    creates an ACM certificate (acm.tf) and outputs the DNS validation
    record to submit to the is-a.dev register repo. It does NOT put the
    domain in front of the distribution on its own - that is
    `custom_domain_active`, which is a separate, later apply. Set to ""
    to disable the custom domain entirely.
  EOT
  type        = string
  default     = "callback.is-a.dev"
}

variable "custom_domain_active" {
  description = <<-EOT
    Whether to attach `custom_domain` and its certificate to the
    CloudFront distribution. Flip this to true ONLY after the certificate
    has reached ISSUED (i.e. the is-a.dev PR carrying the validation CNAME
    has merged and propagated) - CloudFront rejects a certificate that is
    still PENDING_VALIDATION. cloudfront.tf asserts this with a
    precondition so the failure is a readable message rather than an
    opaque API error. While false, the distribution keeps serving on its
    default *.cloudfront.net certificate.
  EOT
  type        = bool
  default     = false
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
