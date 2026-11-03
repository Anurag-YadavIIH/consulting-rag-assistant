"""
Static checks on the CloudFront/S3 Terraform (infra/terraform/), with no AWS
calls:

  * every route the FastAPI app serves is covered by a CloudFront API path
    pattern, and the docs routes (/docs, /redoc, /openapi.json) are not;
  * there are no distribution-wide custom error responses, which would turn
    the API's JSON 401/403/404/409 into HTML;
  * the variable rules (debug IPs, timeout, CSP default) behave, via
    `terraform test` on a scratch copy of variables.tf with no providers or
    state, skipped if terraform isn't installed.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed")

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / "infra" / "terraform"
sys.path.insert(0, str(ROOT / "src"))

from consultrag.api.main import app  # noqa: E402

DOC_ROUTES = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _api_path_patterns() -> list[str]:
    text = (TF / "frontend.tf").read_text(encoding="utf-8")
    block = re.search(r"api_path_patterns\s*=\s*\[(.*?)\]", text, re.S)
    assert block, "api_path_patterns not found in frontend.tf"
    return re.findall(r'"([^"]+)"', block.group(1))


def _cloudfront_matches(pattern: str, path: str) -> bool:
    # CloudFront path patterns: case-sensitive, * matches any characters
    # (including /), ? matches one character.
    regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
    return re.match(regex, path) is not None


def _app_paths() -> set[str]:
    # The OpenAPI schema lists every API route. (app.routes isn't enough:
    # this FastAPI version wraps included routers in objects without a
    # `path`, which once hid every route but /health from this test.)
    paths = set(app.openapi()["paths"])
    paths |= {r.path for r in app.routes if hasattr(r, "path")}  # docs routes
    return paths


def test_route_discovery_sees_the_real_api_routes():
    paths = _app_paths()
    for expected in ("/auth/login", "/auth/refresh", "/me", "/query", "/documents",
                     "/ingest/upload", "/admin/activity", "/admin/members"):
        assert expected in paths, expected
    assert len(paths - DOC_ROUTES) >= 15


def test_every_api_route_is_routed_to_the_load_balancer():
    patterns = _api_path_patterns()
    api_routes = _app_paths() - DOC_ROUTES
    assert api_routes, "no routes found"
    missing = sorted(p for p in api_routes if not any(_cloudfront_matches(pat, p) for pat in patterns))
    assert missing == [], f"API routes CloudFront would send to S3: {missing}"


def test_api_docs_are_not_exposed_through_cloudfront():
    patterns = _api_path_patterns()
    exposed = sorted(p for p in DOC_ROUTES if any(_cloudfront_matches(pat, p) for pat in patterns))
    assert exposed == []


def test_static_site_paths_stay_on_s3():
    patterns = _api_path_patterns()
    for path in ("/", "/index.html", "/management/", "/_next/static/chunks/main.js", "/404.html"):
        assert not any(_cloudfront_matches(pat, path) for pat in patterns), path


def test_no_distribution_wide_custom_error_responses():
    for tf in TF.glob("*.tf"):
        assert "custom_error_response" not in tf.read_text(encoding="utf-8"), tf.name


def test_origin_secret_is_never_output():
    outputs = (TF / "outputs.tf").read_text(encoding="utf-8")
    assert "origin_verify" not in outputs
    assert "random_password" not in outputs


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_variable_rules_with_terraform_test(tmp_path):
    shutil.copy(TF / "variables.tf", tmp_path / "variables.tf")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "vars.tftest.hcl").write_text(
        """
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
""",
        encoding="utf-8",
    )
    # No provider blocks and no state in this directory: nothing can reach AWS.
    env = {"PATH": os.environ["PATH"], "AWS_CONFIG_FILE": "nul",
           "AWS_SHARED_CREDENTIALS_FILE": "nul", "CHECKPOINT_DISABLE": "1"}
    for name in ("SYSTEMROOT", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME"):
        if name in os.environ:
            env[name] = os.environ[name]
    init = subprocess.run(["terraform", "init", "-input=false", "-no-color"], cwd=tmp_path,
                          capture_output=True, text=True, env=env, timeout=120)
    assert init.returncode == 0, init.stdout + init.stderr
    result = subprocess.run(["terraform", "test", "-no-color"], cwd=tmp_path,
                            capture_output=True, text=True, env=env, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "12 passed, 0 failed" in result.stdout
