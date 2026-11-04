# Plans the real configuration with mocked providers: no credentials, no AWS
# calls, no state. Run with `terraform init -backend=false && terraform test`.
# The variable rules mirror tests/test_terraform_hosting.py, which checks
# them against a copy of variables.tf; here they run against the whole
# configuration, plus a few security properties of the planned resources.

mock_provider "aws" {
  # local.azs slices the first two zone names, so the mock needs two.
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["ap-south-1a", "ap-south-1b"]
    }
  }
}

mock_provider "random" {}

run "security_properties_by_default" {
  command = plan

  assert {
    condition     = aws_db_instance.main.publicly_accessible == false
    error_message = "the database must not be publicly accessible"
  }
  assert {
    condition     = aws_db_instance.main.storage_encrypted == true
    error_message = "database storage must be encrypted"
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.frontend.block_public_acls,
      aws_s3_bucket_public_access_block.frontend.block_public_policy,
      aws_s3_bucket_public_access_block.frontend.ignore_public_acls,
      aws_s3_bucket_public_access_block.frontend.restrict_public_buckets,
    ])
    error_message = "the frontend bucket must block all public access"
  }
  assert {
    condition     = aws_lb_listener.http.default_action[0].fixed_response[0].status_code == "403"
    error_message = "the load balancer must answer 403 unless a rule forwards the request"
  }
  assert {
    condition     = aws_cloudfront_distribution.main.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "CloudFront must redirect viewers to HTTPS"
  }
  assert {
    condition     = length(aws_lb_listener_rule.debug_ips) == 0
    error_message = "direct debug access must be off by default"
  }
}

run "debug_access_off_by_default" {
  command = plan
  assert {
    condition     = length(var.debug_allowed_cidrs) == 0
    error_message = "debug access must be off by default"
  }
}

run "single_ip_allowed" {
  command = plan
  variables { debug_allowed_cidrs = ["203.0.113.7/32"] }
}

run "whole_internet_refused" {
  command = plan
  variables { debug_allowed_cidrs = ["0.0.0.0/0"] }
  expect_failures = [var.debug_allowed_cidrs]
}

run "wide_range_refused" {
  command = plan
  variables { debug_allowed_cidrs = ["10.0.0.0/8"] }
  expect_failures = [var.debug_allowed_cidrs]
}

run "ipv6_any_refused" {
  command = plan
  variables { debug_allowed_cidrs = ["::/0"] }
  expect_failures = [var.debug_allowed_cidrs]
}

run "not_a_cidr_refused" {
  command = plan
  variables { debug_allowed_cidrs = ["not-an-ip"] }
  expect_failures = [var.debug_allowed_cidrs]
}

run "timeout_above_quota_refused" {
  command = plan
  variables { api_origin_read_timeout = 180 }
  expect_failures = [var.api_origin_read_timeout]
}

run "initial_admin_emails_must_be_emails" {
  command = plan
  variables { initial_admin_emails = ["not an email"] }
  expect_failures = [var.initial_admin_emails]
}

run "allowed_domains_must_be_domains" {
  command = plan
  variables { allowed_email_domains = ["@example.com"] }
  expect_failures = [var.allowed_email_domains]
}

run "invitation_ttl_in_range" {
  command = plan
  variables { invitation_ttl_days = 0 }
  expect_failures = [var.invitation_ttl_days]
}

run "valid_team_settings_pass" {
  command = plan
  variables {
    initial_admin_emails  = ["first.admin@example.com"]
    allowed_email_domains = ["example.com"]
  }
}

run "csp_starts_report_only" {
  command = plan
  assert {
    condition     = var.csp_enforce == false
    error_message = "CSP must start in report-only mode"
  }
}
