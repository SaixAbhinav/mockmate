# Custom domain certificate (ADR 0032).
#
# The distribution's default name is an AWS-assigned hash
# (d1ukk616lu5bcc.cloudfront.net) - you cannot choose it. A readable URL
# needs a domain you control, and ADR 0032 takes the free path: a
# community subdomain from is-a.dev, whose DNS records are added by
# pull request to their register repo rather than by an API.
#
# That external, human-merged DNS is the whole reason this file is shaped
# the way it is. ACM only issues a certificate once its validation CNAME
# resolves, and CloudFront only accepts a certificate that is already
# ISSUED - but the record in between is merged by a stranger on their
# schedule, not by `terraform apply`. So the cutover is deliberately TWO
# applies, gated by two variables:
#
#   1. `custom_domain` set (the default) creates the certificate and
#      outputs the validation record to put in the is-a.dev PR. The
#      certificate sits PENDING_VALIDATION and nothing else changes -
#      crucially, this apply does NOT block, so CI stays fast and green
#      while the PR waits.
#   2. `custom_domain_active = true`, set only after the certificate has
#      actually reached ISSUED, attaches it and the alias to the
#      distribution (cloudfront.tf).
#
# aws_acm_certificate_validation is deliberately NOT used: it blocks the
# apply until the record resolves, which here could be days, and it would
# hold the deploy workflow's job open (and the Terraform state lock with
# it) the entire time.
#
# No aliased provider is needed for the us-east-1 requirement (CloudFront
# only reads certificates from us-east-1) because this whole stack already
# lives there - see providers.tf.

locals {
  # Both conditions, so `custom_domain_active = true` with no domain set
  # is a no-op rather than an index error on an empty certificate list.
  custom_domain_active = var.custom_domain != "" && var.custom_domain_active
}

resource "aws_acm_certificate" "frontend" {
  count = var.custom_domain == "" ? 0 : 1

  domain_name       = var.custom_domain
  validation_method = "DNS"

  # The distribution references this certificate by ARN. Replacing a
  # certificate in place would briefly leave the alias pointing at a
  # deleted cert, so build the new one before destroying the old.
  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "callback-frontend"
  }
}
