# Custom domain certificate (ADR 0032, retargeted by ADR 0034).
#
# The distribution's default name is an AWS-assigned hash
# (d1ukk616lu5bcc.cloudfront.net) - you cannot choose it. A readable URL
# needs a domain you control, and ADR 0034 uses a registered one from the
# GitHub Student Developer Pack after ADR 0032's free is-a.dev subdomain was
# denied by that project's reviewers.
#
# The certificate itself is unchanged by that switch: free, DNS-validated,
# and necessarily in us-east-1 because CloudFront reads certificates from
# nowhere else. No aliased provider is needed, since this whole stack already
# lives there (providers.tf).
#
# What did change is who creates the validation record. It is now
# route53.tf's job rather than a pull request against someone else's
# repository, which is what makes automatic issuance and renewal possible -
# see that file for the two-apply sequence and why the wait exists at all.

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
