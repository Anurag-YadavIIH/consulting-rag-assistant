# Runbook: rebuild ConsultRAG on AWS with the frontend

**Status: planned and untested on AWS.** The Terraform passes `terraform fmt` and `terraform validate`, and the API checks below were trialled against the API running locally in Docker Compose. Nothing here has been applied to AWS yet. Update this file with real results after the first run.

Everything runs from Windows PowerShell in the repository root, with AWS CLI v2, Terraform, Docker Desktop and Node.js installed, and an AWS profile named `consultrag`. Each `terraform apply` creates billable resources.

The whole sequence, in order:

0. Check credits and sign-in
1. Prepare Terraform settings
2. Apply with no containers
3. Push the API image
4. Run database migrations
5. Start the API
6. Add the CloudFront URL to Google
7. Deploy the frontend
8. Sign in (you're the first admin)
9. Give the team access from the Team page
10. Run the post-deploy checks
11. Take screenshots
12. Destroy

## 0. Check credits and sign-in

- **Credit balance:** in the AWS console, open **Billing and Cost Management**, then **Credits**. It shows the remaining balance and expiry. Don't start if the balance is low.
- **Spend so far this month** (the Cost Explorer API charges $0.01 per request):

  ```powershell
  $start = (Get-Date -Day 1).ToString("yyyy-MM-dd"); $end = (Get-Date).AddDays(1).ToString("yyyy-MM-dd")
  aws ce get-cost-and-usage --time-period Start=$start,End=$end --granularity MONTHLY --metrics UnblendedCost --profile consultrag
  ```

- **Who you are signed in as:** `aws sts get-caller-identity --profile consultrag`. The `Arn` should be an IAM user or role (for example `anurag-admin`), not `root`.

## 1. Prepare Terraform settings

The load balancer no longer takes an IP allowlist; only CloudFront can reach it. If your local `infra\terraform\terraform.tfvars` still contains this line, delete it (Terraform would otherwise warn about an undeclared variable):

```hcl
allowed_cidrs = ["YOUR.IP/32"]
```

Set the first admin in `infra\terraform\terraform.tfvars` (gitignored; the
email is personal data and must never go into a committed file):

```hcl
initial_admin_emails = ["you@example.com"]
```

Optionally restrict sign-in to your organisation's domain (invited emails
and the initial admin can still sign in):

```hcl
allowed_email_domains = ["example.com"]
```

Every other setting has a default (see `variables.tf`). `terraform.tfvars.example` shows the optional settings.

## 2. Apply with no containers

```powershell
cd infra\terraform
terraform init
terraform apply          # desired_count defaults to 0
cd ..\..
```

Creating the CloudFront distribution usually takes several minutes. Note the outputs: `cloudfront_url`, `ecr_repository_url`, `frontend_bucket`, `cloudfront_distribution_id`, `load_balancer_dns_name`, `public_subnet_ids` and `api_security_group_id`. None of them is secret.

## 3. Push the API image

```powershell
$tf = "infra\terraform"
$repoUrl = terraform "-chdir=$tf" output -raw ecr_repository_url
$registry = $repoUrl.Split("/")[0]
aws ecr get-login-password --region ap-south-1 --profile consultrag | docker login --username AWS --password-stdin $registry
docker build -f docker/api/Dockerfile -t consultrag-api .
docker tag consultrag-api "${repoUrl}:latest"
docker push "${repoUrl}:latest"
```

## 4. Run database migrations

One-off Fargate task using the API image and network settings:

```powershell
$tf = "infra\terraform"
$cluster = terraform "-chdir=$tf" output -raw cluster_name
$taskDef = terraform "-chdir=$tf" output -raw task_definition
$subnets = (terraform "-chdir=$tf" output -json public_subnet_ids | ConvertFrom-Json) -join ","
$sg = terraform "-chdir=$tf" output -raw api_security_group_id
$net = "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}"

function Invoke-OneOffTask([string[]]$command) {
    $overrides = @{ containerOverrides = @(@{ name = "api"; command = $command }) } | ConvertTo-Json -Depth 5 -Compress
    $file = New-TemporaryFile
    Set-Content -Path $file -Value $overrides -Encoding ascii
    $arn = aws ecs run-task --cluster $cluster --task-definition $taskDef --launch-type FARGATE `
        --network-configuration $net --overrides "file://$file" --profile consultrag `
        --query "tasks[0].taskArn" --output text
    Remove-Item $file
    aws ecs wait tasks-stopped --cluster $cluster --tasks $arn --profile consultrag
    aws ecs describe-tasks --cluster $cluster --tasks $arn --profile consultrag `
        --query "tasks[0].containers[0].{exitCode:exitCode,reason:reason}"
}

Invoke-OneOffTask @("sh", "-c", "python scripts/migrate_pg.py --dim 384 && python scripts/migrate_authz.py")
```

Expect `exitCode: 0`. The output is in CloudWatch Logs, group `/ecs/consultrag-api`: `Schema ready ...`, `Audit schema ready: table 'audit_events'` and `Authz schema ready`. Keep this PowerShell window open; step 9 reuses `Invoke-OneOffTask`.

## 5. Start the API

```powershell
cd infra\terraform
terraform apply -var="desired_count=1"
cd ..\..
aws ecs wait services-stable --cluster consultrag --services consultrag-api --profile consultrag
$u = terraform -chdir=infra\terraform output -raw cloudfront_url
curl.exe -s "$u/health"
```

Expect `{"status":"ok","version":"0.2.0"}`. Use `-var="desired_count=1"` on every later `terraform apply`, or it scales the API back to 0.

## 6. Add the CloudFront URL to Google

The URL only exists after step 2. In Google Cloud Console, open **APIs & Services**, then **Credentials**, then the OAuth client `778432443327-tfr98qv01htq229443g0kjnvlkp2md4h`:

- Under **Authorized JavaScript origins**, add the `cloudfront_url` output, for example `https://d1234abcd.cloudfront.net` (no trailing slash).
- If you no longer develop locally, remove `http://localhost:3000` and `http://localhost`. Keep them if you still run the frontend on your machine.
- Save. Google says changes can take 5 minutes to a few hours.

## 7. Deploy the frontend

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_frontend.ps1
```

It stops with an error if any Terraform output is missing, if the build fails, if `out\index.html` is missing, or if the build still contains `localhost:8000`, before anything is uploaded. Wait a few minutes for the invalidation.

## 8. Sign in (you're the first admin)

Step 1 set `initial_admin_emails` to your Google account, so the first time
you sign in with it (Google must report the email as verified) the account
becomes a global admin with clearance 3. That happens once per account; the
API logs it by user number only. Open the `cloudfront_url` and sign in. You
should see the app with **Activity** and **Team** in the sidebar, and
"Admin, clearance 3" under your name.

## 9. Give the team access from the Team page

The database starts empty, so there are no engagements until documents are
uploaded or someone is invited to one. On **Team**:

- **Invite** each colleague by their Google account email, with a role
  preset (Analyst 1, Manager 2, Senior management 3, Admin) and the
  engagements they need. No email is sent: share the `cloudfront_url` with
  them. The invitation applies once, at their first verified sign-in, and
  expires after `invitation_ttl_days` (14 by default).
- **Edit** or **Remove** people later. Changes reach them at their next
  token refresh (within 15 minutes); removal also signs them out of new
  sessions, but a page they already have open can keep working for up to 15
  minutes.

**Fallback (shell access):** if sign-in as the first admin doesn't work, the
one-off Fargate task can still grant access by user number (shown in the
sidebar after any sign-in). In the PowerShell window from step 4:

```powershell
Invoke-OneOffTask @("python", "scripts/seed_authz.py", "--user-id", "90", "--admin", "--clearance", "3")
```

Expect `exitCode: 0`; an unknown number fails with `exitCode: 1` and grants
nothing.

## 10. Post-deploy checks

Record the result of each one.

### API, from PowerShell

These commands were trialled against the API in local Docker Compose; the expected results through CloudFront are untested.

```powershell
$u = terraform -chdir=infra\terraform output -raw cloudfront_url
curl.exe -s -w " [%{http_code} %{content_type}]" "$u/health"
curl.exe -s -w " [%{http_code} %{content_type}]" "$u/me"
curl.exe -s -w " [%{http_code} %{content_type}]" "$u/auth/nope"
curl.exe -s -w " [%{http_code} %{content_type}]" -X POST -H "Content-Type: application/json" -d "{}" "$u/ingest"
curl.exe -s -w " [%{http_code} %{content_type}]" -X POST "$u/auth/refresh"
curl.exe -s -w " [%{http_code} %{content_type}]" -X POST -H "X-ConsultRAG-CSRF: 1" "$u/auth/refresh"
curl.exe -s -o NUL -w "[%{http_code} %{content_type}]" "$u/docs"
curl.exe -s -w " [%{http_code} %{content_type}]" "$u/admin/members"
```

| # | Request | Expected |
|---|---|---|
| A1 | `/health` | `200`, JSON `{"status":"ok",...}` |
| A2 | `/me` with no token | `401`, JSON `{"detail":"missing Authorization header"}`. Proves API errors aren't replaced by HTML. |
| A3 | `/auth/nope` | `404`, JSON `{"detail":"Not Found"}` |
| A4 | `POST /ingest` (path ingest) | `404`, JSON (development-only route) |
| A5 | `POST /auth/refresh`, no CSRF header | `403`, JSON `{"detail":"missing X-ConsultRAG-CSRF header"}` |
| A6 | `POST /auth/refresh`, header, no cookie | `401`, JSON `{"detail":"not signed in"}` |
| A7 | `/docs` | Not `200`: CloudFront sends it to S3, which answers `403` (XML). The API docs aren't public. |
| A8 | `/admin/members` with no token | `401`, JSON. The Team routes reach the API and need a signed-in admin. |

Static site and headers:

```powershell
curl.exe -s -I "$u/"
curl.exe -s -o NUL -w "[%{http_code} %{content_type}]" "$u/management/"
curl.exe -s -o NUL -w "[%{http_code} %{content_type}]" "$u/nope/"
curl.exe -s -I ($u -replace "^https", "http")
```

| # | Expected |
|---|---|
| S1 | `/` is `200` with `strict-transport-security`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `referrer-policy: strict-origin-when-cross-origin`, `cross-origin-opener-policy: same-origin-allow-popups` and `content-security-policy-report-only` |
| S2 | `/management/` is `200 text/html` |
| S3 | `/nope/` is `403` XML from S3 (known limitation) |
| S4 | `http://` gets `301` to `https://` |

### Direct access to the load balancer is refused

```powershell
$alb = terraform -chdir=infra\terraform output -raw load_balancer_dns_name
curl.exe -s -m 10 -o NUL -w "[%{http_code}]" "http://$alb/health"
```

- **D1, default settings:** expect `[000]` after about 10 seconds, meaning no response. The **security group** drops the traffic, because only CloudFront's address ranges are allowed in. The request never reaches the listener.
- **D2, the listener layer:** to see the secret-header rule itself, temporarily allow your IP in the security group only:

  ```powershell
  # A temporary variables file avoids PowerShell's quoting problems with -var.
  $ip = (curl.exe -s https://checkip.amazonaws.com).Trim()
  $debugVars = Join-Path $env:TEMP "consultrag-debug.tfvars"
  Set-Content -Path $debugVars -Value "debug_allowed_cidrs = [`"$ip/32`"]" -Encoding ascii
  cd infra\terraform
  terraform apply -var="desired_count=1" "-var-file=$debugVars"
  cd ..\..
  curl.exe -s -w " [%{http_code}]" "http://$alb/health"
  ```

  Expect `{"detail":"Forbidden"} [403]`. That's the **listener's** default action: the request has no `X-Origin-Verify` header. `debug_bypass_origin_check` stays false, so your IP gets no bypass. The header value is never printed or needed.

  **Then remove the debug access:**

  ```powershell
  cd infra\terraform
  terraform apply -var="desired_count=1"
  cd ..\..
  Remove-Item $debugVars
  ```

  Variables don't persist between runs, so this apply drops the IP again. If you ever put `debug_allowed_cidrs` in `terraform.tfvars` instead, delete that line before this apply. Variable validation refuses `0.0.0.0/0`, IPv6 and anything wider than `/24`.

### Browser (Chrome, DevTools open, Network tab with "Preserve log" or "Keep log" ticked)

| # | Do | Expected |
|---|---|---|
| B1 | Open the URL, sign in | Google popup, then the app (or "No access yet" before step 9) |
| B2 | Network: the `me` request after sign-in | `200`. This proves CloudFront forwards the `Authorization` header (managed `CachingDisabled` + `AllViewerExceptHostHeader`). If it's `401` with `missing Authorization header`, stop: the fallback cache policy is needed. |
| B3 | Reload twice | Stays signed in; Network shows `me` 401, `refresh` 200, `me` 200 each time |
| B4 | Upload `data\sample\deck.pptx` to acme | "Ingested 2 chunks from deck.pptx." |
| B5 | Ask "What is the TAM for ambulatory neurosurgery?" | First source `deck.pptx`, slide 1 |
| B6 | Console during B1, B4 and B5 | Note every `[Report Only]` Content-Security-Policy message. None is the goal; any listed message needs a policy change before enforcing. |
| B7 | Sign out, then reload | Back to the sign-in screen and stays there |
| B8a | Large upload within the text limit: a real, text-heavy PDF of about 40 to 60 pages (under roughly 37,500 words) | Record the time from the Network tab's Time column. Expect success in under 60 s. If it takes longer, CloudFront returns `504` and the app shows "The server took too long to respond..."; wait a minute and ask about the document to see whether it finished in the background, and record it. |
| B8b | Over the text limit: a long, text-heavy PDF (for example 150+ pages, under 25 MB) | A `413` within a few seconds and the app shows "the document has too much text to process: the limit is 150 chunks (roughly 37,500 words)...". Nothing new is cited afterwards. |

### Enforcing the CSP (a later step)

The Content-Security-Policy is **report-only** until this step. Once B6 shows no reports during sign-in, upload and query:

```powershell
cd infra\terraform
terraform apply -var="desired_count=1" -var="csp_enforce=true"
cd ..\..
```

Then repeat B1, B4, B5 and B6.

## 11. Take screenshots

The sign-in screen, the app with a cited answer, and the "No access yet" screen if you have it. Leave out your email if you'll share them.

## 12. Destroy

```powershell
cd infra\terraform
terraform destroy
cd ..\..
```

`force_destroy` on the bucket and `force_delete` on the image repository let destroy remove their contents, and the secrets have no recovery window. Deleting the CloudFront distribution takes several minutes (it's disabled first). The next day, check **Billing and Cost Management** to confirm nothing is still running.
