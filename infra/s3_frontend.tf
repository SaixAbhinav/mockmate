# S3 bucket for the built frontend SPA, served only through CloudFront
# (ADR 0029, PR 3).
#
# The bucket is PRIVATE - no website hosting, no public ACLs, no public
# bucket policy. The single apparent origin (ADR 0025's load-bearing
# property, preserved by this ADR - see cloudfront.tf) requires that the
# only way to read an object is via CloudFront's Origin Access Control
# below; a public bucket would create a second, cache-bypassing origin and
# defeat that property.

resource "aws_s3_bucket" "frontend" {
  bucket = "mockmate-frontend-356252962813"

  tags = {
    Name = "mockmate-frontend"
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Origin Access Control - lets CloudFront sign requests to this bucket with
# SigV4 so the bucket policy below can scope access to "this distribution",
# not "anyone with the CloudFront service principal". Supersedes the older
# Origin Access Identity (OAI) mechanism.
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "mockmate-frontend-oac"
  description                       = "OAC for the mockmate frontend S3 origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Grants the CloudFront service principal s3:GetObject, but only when the
# request comes from THIS distribution (AWS:SourceArn) - not from any
# CloudFront distribution in any account. This is the standard OAC bucket
# policy shape; without the SourceArn condition, any distribution anywhere
# with this bucket as an origin could read it.
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipalReadOnly"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
          }
        }
      }
    ]
  })
}
