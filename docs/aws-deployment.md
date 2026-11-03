# Deploying ConsultRAG's API to AWS

I deployed ConsultRAG's FastAPI backend to AWS on 2 November 2026 to learn how a containerised ML service runs in the cloud. The whole environment is defined in Terraform, so I can build it, test it and destroy it to control cost.

**Status:** the API and database ran successfully on AWS. It is not a public demo yet: there is no frontend, HTTPS or browser sign-in on AWS, and access was limited to my own IP address. I shut it down after testing, so there is no live URL. Hosting the frontend on S3 and CloudFront, with browser sign-in on one HTTPS URL, is written in Terraform but not yet applied or tested (see "Planned: frontend on S3 and CloudFront").

## Architecture

```
My IP only ── HTTP ──▶ Application Load Balancer (public subnets, 2 availability zones)
                              │ port 8000, load balancer only
                              ▼
                       ECS Fargate task: FastAPI + embedding model
                       (1 vCPU, 3 GB, image from ECR)
                          │                │               │
                          │ port 5432      │ at startup    │ logs
                          ▼                ▼               ▼
                 RDS PostgreSQL 16    Secrets Manager   CloudWatch Logs
                 + pgvector           (DB URL, JWT key)  (7-day retention)
                 (private subnets, no internet route)
```

## What each piece does

| Service | Role here |
|---|---|
| **Terraform** | Defines all 32 AWS resources in [`infra/terraform/`](../infra/terraform/) |
| **VPC and security groups** | Only my IP reaches the load balancer, only the load balancer reaches the containers, and only the containers reach the database |
| **Docker and ECR** | Packages the API with CPU-only PyTorch and the embedding model, and stores the image |
| **ECS Fargate** | Runs the API without a server to manage, plus one-off database migration tasks |
| **Application Load Balancer** | Sends traffic to the container and checks `/health` |
| **RDS with pgvector** | Stores text chunks, embedding vectors and permissions, encrypted at rest |
| **Secrets Manager and IAM** | Gives the container the database URL and signing key at startup, with a role limited to reading those two secrets |
| **CloudWatch Logs** | Collects container output |

## What I verified on AWS

| Test | Result |
|---|---|
| Run database migrations as a one-off Fargate task | Exit code 0: `Schema ready: table 'chunks' (dim=384)`, `Authz schema ready` |
| Run the API as an ECS service | 1 task running: `service consultrag-api has reached a steady state` |
| `GET /health` through the load balancer | `200 OK`, `{"status":"ok"}` |
| `GET /me` with no token | `401 Unauthorized`, `{"detail":"missing Authorization header"}` |
| Ship a code change with an ECS rolling deployment | New image pushed to ECR, and `/health` then returned `{"status":"ok","version":"0.2.0"}` |

**Not tested on AWS yet:** ingesting documents, answering queries, and Google sign-in.

## Problems worth a closer look

- **Passwords in logs.** The migration scripts printed the full database URL. That was harmless on a laptop, but on AWS it would have put the password in CloudWatch, so I removed it before the first run.
- **pgvector on RDS.** Locally, a Docker init script enabled the extension. RDS doesn't run that script, so the migration now enables it.
- **Image size.** The default PyTorch install includes NVIDIA GPU libraries this service never uses. The CPU-only image is 643 MB compressed. The model is built into the image, so a new container doesn't download it.
- **Cost.** Containers sit in public subnets, protected by security groups, to avoid the monthly cost of a NAT gateway. A private-subnet setup would be the better choice for production.
- **Safe startup order.** Terraform starts with zero containers. The image gets pushed and migrations run before the service starts.

## Cost

I estimate about $0.10 to $0.13 an hour while running. I used AWS credits and ran `terraform destroy` after testing.

## Current limitations

- No frontend, HTTPS or browser sign-in on AWS yet. Google sign-in works in the frontend locally (Docker Compose and the static export on `http://localhost:3000`). Hosting the frontend on S3 and CloudFront is written in Terraform but **not applied or tested on AWS**; see "Planned: frontend on S3 and CloudFront" below.
- Document upload (`POST /ingest/upload`) works with Docker Compose locally but hasn't been deployed or tested on AWS. The path-based `/ingest` returns 404 unless `APP_ENV` is `development` or `dev`.
- After an upload, only the API process that handled it refreshes its in-memory keyword (BM25) index. Other processes find new documents through vector search only until they restart. This deployment runs one task, but running more than one needs a shared fix first, such as keyword search in Postgres or a refresh signal between tasks.
- FastAPI receives a whole upload before checking its size, so an oversized file still arrives before the 413 is returned.
- Terraform state is stored on my laptop, and deployments are manual, with no CI/CD yet.
- The database is a single instance with no backups, because this is a learning environment holding no real data.
- This setup is not reviewed for real client or patient data.

## Planned: frontend on S3 and CloudFront (untested on AWS)

**Status:** the Terraform in `infra/terraform/frontend.tf` (with changes to `network.tf`, `service.tf`, `variables.tf` and `outputs.tf`) passes `terraform fmt` and `terraform validate`. It has not been planned or applied. The step-by-step rebuild, including the post-deploy checks, is in [aws-frontend-runbook.md](aws-frontend-runbook.md).

```text
Browser ── HTTPS ──▶ CloudFront (default *.cloudfront.net domain, PriceClass_200)
                       │                                  │
         default (*)   │ Origin Access Control            │ /auth/*, /me, /query, /draft,
         + function    ▼                                  │ /ingest, /ingest/*, /documents, /admin/*, /health
              S3 bucket (private, static export)          │ HTTP + secret origin header
                                                          ▼
                         Application Load Balancer (only CloudFront's IP ranges allowed;
                         listener forwards only requests carrying the secret header)
                                                          │
                                                          ▼
                                            ECS Fargate API ── RDS, Secrets Manager
```

How it fits together:

- **One origin.** The browser loads the app and calls the API on the same CloudFront URL, so the refresh cookie (`Secure`, `SameSite=Strict`, `Path=/auth`) stays first-party and the API needs no CORS (`CORS_ALLOWED_ORIGINS` stays unset). The frontend is built with `NEXT_PUBLIC_API_BASE_URL=/`, which means relative API paths.
- **S3:** a private bucket with all public access blocked, readable only by this distribution through Origin Access Control. `force_destroy` lets `terraform destroy` remove it with files in it.
- **Static paths:** a CloudFront Function on the S3 behavior only maps `/management/` and `/management` to `management/index.html`. There are no distribution-wide custom error responses, because those would turn the API's JSON 401, 403, 404 and 409 into HTML.
- **API behaviors:** the exact API paths (including `/documents` and `/admin/*`, added after this section was first written) go to the load balancer with all HTTP methods, the managed `CachingDisabled` cache policy and the managed `AllViewerExceptHostHeader` origin request policy, which forwards `Authorization`, `X-ConsultRAG-CSRF`, all cookies and all query strings, but not the viewer's `Host`. FastAPI's `/docs`, `/redoc` and `/openapi.json` aren't routed, so they aren't public. A test checks the path list against the app's real routes.
- **Load balancer:** the security group allows port 80 only from the AWS-managed CloudFront origin-facing prefix list. The listener's default action is a JSON 403; a rule forwards only requests carrying a random secret header that CloudFront adds (`X-Origin-Verify`), so other CloudFront distributions can't use it. The value lives only in Terraform state and the distribution config, and is never output. `debug_allowed_cidrs` (off by default, `/24` or narrower, never `0.0.0.0/0`) can temporarily open the security group to your IP.
- **Security headers:** HSTS, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` and `Cross-Origin-Opener-Policy: same-origin-allow-popups` (Google's popup sign-in needs that value; plain `same-origin` breaks it). The Content-Security-Policy allows Google Identity Services and is **report-only** until the post-deploy checks show no reports; `csp_enforce = true` then enforces it.
- **API settings:** `OAUTH_AUDIENCE` comes from `var.oauth_audience` (the Google client ID), with `APP_ENV=production` and `DEV_AUTH_BYPASS=false`.

Known limitations of this design:

- **CloudFront to the load balancer is HTTP.** Viewers always use HTTPS, but the hop from CloudFront to the load balancer inside AWS's network is unencrypted, because the load balancer has no certificate without a custom domain. Requests on that hop include access tokens and the refresh cookie. The production option is a custom domain with an ACM certificate on an HTTPS listener (and `origin_protocol_policy = "https-only"`), or a CloudFront VPC origin with an internal load balancer.
- **Upload processing time.** CloudFront waits `api_origin_read_timeout` seconds (60 by default; 30 is CloudFront's default and 120 the maximum without a quota increase) and doesn't retry a POST that times out; the viewer gets a 504. The load balancer's idle timeout is set 10 seconds longer, and the container's keep-alive (150 seconds) longer again, as AWS recommends. Embedding on the 1 vCPU container ran at about 3 chunks a second (about 150 seconds per MB of extracted text) in a local benchmark inside the API image limited to one CPU, so roughly 60 to 70 dense pages fit in 60 seconds. Uploads are therefore also capped by extracted text: `MAX_UPLOAD_CHUNKS` (default 150 chunks, roughly 37,500 words, about 50 seconds of embedding) refuses longer documents with a `413` before any embedding. A document just under the cap could still approach the timeout on a slower CPU; in that case CloudFront returns `504`, the frontend shows a timeout message, and the API may still finish storing the document.
- **Unknown static paths** such as `/nope/` return S3's `403` XML page, because there's no distribution-wide error page.
- **The CloudFront prefix list** counts as about 55 of the security group's default 60 rules.
- **Cost (estimate).** CloudFront's always-free tier includes 1 TB of transfer, 10 million requests and 2 million function invocations a month, and the static site is about 1 MB in S3, so personal use should add close to $0 a month on top of the running cost above. This is an estimate, not a measured bill.

## Rebuild it

Requires AWS CLI v2, Terraform, Docker and an AWS profile named `consultrag`. Commands are for Windows PowerShell. Running this creates billable resources.

With the planned frontend hosting, follow [aws-frontend-runbook.md](aws-frontend-runbook.md) instead: it covers the whole order from credits to destroy. The steps below are the original API-only rebuild.

```powershell
cd infra\terraform
terraform init
terraform apply
```

Then push the image to the `ecr_repository_url` output, run `scripts/migrate_pg.py --dim 384` and `scripts/migrate_authz.py` as a one-off Fargate task, and start the API:

```powershell
terraform apply -var="desired_count=1"
```

To ship a code change, build and push a new image, then start a rolling deployment. ECS starts the new container and waits for it to pass health checks before draining the old one:

```powershell
aws ecs update-service --cluster consultrag --service consultrag-api --force-new-deployment
aws ecs wait services-stable --cluster consultrag --services consultrag-api
```

When finished, run `terraform destroy`.

## How this was built

I ran the deployment on my own AWS account, tested it and made the decisions. Claude, an AI assistant, helped me plan it, write the Terraform and code changes, and debug problems.
