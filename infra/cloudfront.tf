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

  # No custom domain yet - the default *.cloudfront.net certificate is
  # fine for a demo deploy. A custom domain would need its own ACM cert
  # (us-east-1, since CloudFront only reads certs from that region) plus
  # `aliases` here; not in scope for this PR.
  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name = "mockmate-frontend"
  }
}
