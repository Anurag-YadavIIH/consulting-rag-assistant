# Frontend hosting: the static Next.js export in a private S3 bucket, and one
# CloudFront distribution that serves it and forwards the API paths to the
# load balancer, so the browser sees a single HTTPS origin. Same origin keeps
# the refresh cookie (Secure, SameSite=Strict, Path=/auth) first-party and
# means the API needs no CORS.

locals {
  # Every route the FastAPI app serves (src/consultrag/api/main.py and
  # routes/). FastAPI's /docs, /redoc and /openapi.json are deliberately NOT
  # listed, so they aren't reachable through CloudFront.
  # tests/test_cloudfront_routes.py checks this list against the real app.
  api_path_patterns = [
    "/auth/*",
    "/me",
    "/query",
    "/draft",
    "/ingest",
    "/ingest/*",
    "/health",
  ]

  s3_origin_id  = "s3-frontend"
  api_origin_id = "alb-api"

  origin_verify_header = "X-Origin-Verify"

  # Content Security Policy, allowing Google Identity Services as documented
  # by Google (script, style, frame and connect under accounts.google.com/gsi).
  # 'unsafe-inline' for scripts is needed because the static Next.js export
  # uses inline bootstrap scripts and has no per-request nonce.
  csp = join("; ", [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/client",
    "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
    "frame-src https://accounts.google.com/gsi/",
    "connect-src 'self' https://accounts.google.com/gsi/",
    "img-src 'self' data:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ])
}

# --- S3: private bucket, reachable only through this distribution ------------

resource "aws_s3_bucket" "frontend" {
  bucket_prefix = "${var.project}-frontend-"
  force_destroy = true # terraform destroy empties it first.
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project}-frontend"
  description                       = "CloudFront access to the private frontend bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "CloudFrontReadOnly"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
      Condition = {
        StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.main.arn }
      }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

# --- Secret header from CloudFront to the load balancer ----------------------

# Checked by a listener rule (service.tf). Lives only in Terraform state and
# the distribution config; it is never output.
resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

# --- Managed policies ---------------------------------------------------------

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# All viewer headers (including Authorization and X-ConsultRAG-CSRF), all
# cookies (including consultrag_refresh) and all query strings, but not the
# viewer's Host header.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

# --- Static paths: rewrite folder URLs to their index.html ----------------------

# Only attached to the S3 (default) behavior, so API responses are never
# touched. There are no distribution-wide custom error responses, because
# those would replace the API's JSON 401/403/404/409 with HTML.
resource "aws_cloudfront_function" "static_rewrite" {
  name    = "${var.project}-static-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Map /path/ and /path to /path/index.html for the static export"
  publish = true
  code    = file("${path.module}/functions/static_rewrite.js")
}

# --- Response headers for the static site ----------------------------------------

resource "aws_cloudfront_response_headers_policy" "frontend" {
  name    = "${var.project}-frontend-security"
  comment = "HSTS, nosniff, framing, referrer, COOP for Google sign-in, CSP"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }

    dynamic "content_security_policy" {
      for_each = var.csp_enforce ? [1] : []
      content {
        content_security_policy = local.csp
        override                = true
      }
    }
  }

  custom_headers_config {
    # Google Identity Services' popup sign-in needs same-origin-allow-popups;
    # plain same-origin breaks the popup's handoff back to the page.
    items {
      header   = "Cross-Origin-Opener-Policy"
      value    = "same-origin-allow-popups"
      override = true
    }

    dynamic "items" {
      for_each = var.csp_enforce ? [] : [1]
      content {
        header   = "Content-Security-Policy-Report-Only"
        value    = local.csp
        override = true
      }
    }
  }
}

# --- The distribution -----------------------------------------------------------

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  comment             = "${var.project} frontend and API"
  default_root_object = "index.html"

  # PriceClass_200 is the cheapest class that includes edge locations in India
  # (PriceClass_100 covers only North America, Europe and Israel).
  price_class = "PriceClass_200"

  origin {
    origin_id                = local.s3_origin_id
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  origin {
    origin_id   = local.api_origin_id
    domain_name = aws_lb.api.dns_name

    custom_origin_config {
      http_port  = 80
      https_port = 443
      # HTTP between CloudFront and the load balancer: there is no custom
      # domain or certificate for the load balancer yet. See
      # docs/aws-deployment.md ("CloudFront to the load balancer is HTTP").
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = var.api_origin_read_timeout
      origin_keepalive_timeout = 5
    }

    custom_header {
      name  = local.origin_verify_header
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id           = local.s3_origin_id
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.frontend.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.static_rewrite.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = local.api_path_patterns
    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = local.api_origin_id
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = false
      cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
      origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
      response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
