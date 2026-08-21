# DNS for the custom domain (ADR 0034).
#
# ADR 0032 got its domain from is-a.dev, whose DNS records are added by pull
# request to a volunteer-run repository. That request was denied, and the
# replacement is a registered domain from the GitHub Student Developer Pack.
# The important consequence is not the name: it is that DNS becomes an API we
# control, so ACM's validation record can be created by Terraform instead of
# by a stranger. That removes the reason ADR 0032 could not use
# aws_acm_certificate_validation at all.
#
# The cutover is still two applies, but the wait in the middle is now minutes
# and under your control rather than days and under someone else's:
#
#   1. `custom_domain` set: creates the zone, the certificate, and the
#      validation records. Nothing is attached and nothing blocks. Read
#      `terraform output route53_name_servers` and point the registrar at
#      them. ACM issues on its own once delegation resolves.
#   2. `custom_domain_active = true`: waits for ISSUED (fast by then) and
#      puts the domain in front of the distribution.
#
# The zone is the one line item here that costs money: $0.50/month, the first
# standing charge on this project. ADR 0034 argues why that is worth it over
# hosting DNS somewhere free and outside Terraform.

resource "aws_route53_zone" "primary" {
  count = var.custom_domain == "" ? 0 : 1

  name    = var.custom_domain
  comment = "callback frontend (ADR 0034)"

  tags = {
    Name = "callback"
  }
}

# One record per name ACM asks us to prove. A for_each over
# domain_validation_options rather than a single record so that adding a
# subject alternative name later (a www SAN, say) needs no change here.
resource "aws_route53_record" "cert_validation" {
  for_each = var.custom_domain == "" ? {} : {
    for option in aws_acm_certificate.frontend[0].domain_validation_options :
    option.domain_name => option
  }

  zone_id = aws_route53_zone.primary[0].zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 60

  # ACM reissues against the same record name, and a re-created certificate
  # would otherwise collide with the record still standing from the last one.
  allow_overwrite = true
}

# Deliberately gated on the *active* flag, not merely on the domain being
# set. This resource blocks until the certificate validates, and before the
# registrar delegates to this zone it never will - a plain `terraform apply`
# on an unrelated change would sit there until it timed out, holding the
# DynamoDB state lock and every other deploy behind it (the failure mode ADR
# 0032 called out). By phase 2 delegation is done, so this returns quickly
# and gives the distribution a certificate it can prove is ISSUED.
resource "aws_acm_certificate_validation" "frontend" {
  count = local.custom_domain_active ? 1 : 0

  certificate_arn         = aws_acm_certificate.frontend[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]

  timeouts {
    create = "15m"
  }
}

# The apex pointed at CloudFront. An alias, not a CNAME: DNS forbids a CNAME
# at a zone apex alongside the SOA and NS records that must live there, and
# an alias is also free to resolve where a CNAME costs a lookup.
resource "aws_route53_record" "apex" {
  count = local.custom_domain_active ? 1 : 0

  zone_id = aws_route53_zone.primary[0].zone_id
  name    = var.custom_domain
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.frontend.domain_name
    zone_id                = aws_cloudfront_distribution.frontend.hosted_zone_id
    evaluate_target_health = false
  }
}
