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
    Apex domain the app is served at, e.g. "callback.me" (ADR 0034). Setting
    it creates a Route 53 hosted zone, an ACM certificate, and the DNS
    records that validate it - but does NOT put the domain in front of the
    distribution. That is `custom_domain_active`, a second apply, run once
    the registrar points at this zone's nameservers. Empty disables the
    custom domain entirely, which is the state before a domain is
    registered.
  EOT
  type        = string
  default     = ""
}

variable "custom_domain_active" {
  description = <<-EOT
    Whether to attach `custom_domain` and its certificate to the CloudFront
    distribution. Flip to true only after the registrar's nameservers point
    at this zone (`terraform output route53_name_servers`) and the
    certificate has reached ISSUED - CloudFront rejects one that has not.
    cloudfront.tf asserts this with a precondition so the failure is a
    readable message rather than an opaque API error. While false, the
    distribution keeps serving on its default *.cloudfront.net certificate.
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
