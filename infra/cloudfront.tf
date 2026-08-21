# CloudFront distribution - the single origin the browser talks to (ADR
# 0029, PR 3; preserves ADR 0025's "one apparent origin" property).
#
# "/" -> S3 (the Vite build of the SPA). "/api/*" -> the existing API
# Gateway HTTP API (apigateway.tf) -> Lambda. Because both live behind one
# CloudFront distribution, the browser sees one origin, so the frontend's
# relative fetch("/api/...") calls (frontend/src/api.js, VITE_API_BASE
# empty) keep working unchanged and there is no production CORS. This PR
# makes no frontend code change - see infra/README.md for confirmation.
#
# No SPA error-rewrite (custom_error_response) is configured on purpose:
# the frontend has no react-router (single page, no client-side routes to
# rebuild on refresh), and adding a 404/403 -> index.html rewrite would
# wrongly rewrite genuine /api/* errors (e.g. a 404 from the FastAPI app
# itself) into the SPA's HTML instead of passing them through.
#
# This is ADR 0029's "cutover" point: once this distribution is live and
# the frontend is uploaded, the AWS deploy supersedes ADR 0025's Render
# host. Updating that ADR's status is PR 5's docs step, not this one.

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# "Except host header" matters: without it, CloudFront would forward its
# own Host header (the distribution's domain) to API Gateway, which uses
# Host-based routing internally and would reject or mis-route the request.
# This policy forwards every other viewer header/cookie/query string but
# lets API Gateway see its own host.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host_header" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # cheapest class (NA + EU) - stays inside the near-free bound (ADR 0029)
  comment             = "mockmate frontend + API single-origin distribution"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  origin {
    domain_name = replace(aws_apigatewayv2_api.http.api_endpoint, "https://", "")
    origin_id   = "apigw"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Default behavior: everything not matched by a more specific ordered
  # behavior below (i.e. everything except /api/*) serves the SPA from S3.
  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_optimized.id
    compress               = true
  }

  # /api/* -> API Gateway -> Lambda. Not cached (session/interview state is
  # per-request and must never be served stale), and POST-heavy since most
  # of the app's traffic is submitting answers/code, not GETs.
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "apigw"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host_header.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # Custom domain (ADR 0032, retargeted by ADR 0034), off until phase 2 -
  # see route53.tf for why the cutover is two applies. While inactive this
  # is empty and the block below serves the default *.cloudfront.net
  # certificate, exactly as before.
  aliases = local.custom_domain_active ? [var.custom_domain] : []

  # Exactly one of these two renders: the for_each expressions are
  # mutually exclusive, and viewer_certificate is a required, max-one
  # block. Attaching an ACM cert and serving the default cert are
  # different attribute sets, not different values of the same one, which
  # is why this is two dynamic blocks rather than a conditional.
  dynamic "viewer_certificate" {
    for_each = local.custom_domain_active ? [1] : []
    content {
      # The validation resource's arn, not the certificate's own, so
      # Terraform cannot attach a certificate before it has been proven
      # issued. Same ARN, ordered dependency.
      acm_certificate_arn = aws_acm_certificate_validation.frontend[0].certificate_arn
      ssl_support_method  = "sni-only"
      # TLS 1.2+ only. The default (TLSv1) is weaker than anything this
      # app's browsers need.
      minimum_protocol_version = "TLSv1.2_2021"
    }
  }

  dynamic "viewer_certificate" {
    for_each = local.custom_domain_active ? [] : [1]
    content {
      cloudfront_default_certificate = true
    }
  }

  # Turns the most likely operator mistake - flipping
  # custom_domain_active before the registrar's nameservers point at this
  # zone, so the certificate never validated - into a sentence instead of
  # an opaque CloudFront API error.
  lifecycle {
    precondition {
      condition = !local.custom_domain_active || (
        length(aws_acm_certificate.frontend) > 0 &&
        aws_acm_certificate.frontend[0].status == "ISSUED"
      )
      error_message = "custom_domain_active is true but the ACM certificate for ${var.custom_domain} is not ISSUED yet. Point the registrar at this zone's nameservers (terraform output route53_name_servers), wait for delegation to resolve, then re-apply."
    }
  }

  tags = {
    Name = "mockmate-frontend"
  }
}
