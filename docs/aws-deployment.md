# Deploying ConsultRAG's API to AWS

I deployed ConsultRAG's FastAPI backend to AWS on 2 November 2026 to learn how a containerised ML service runs in the cloud. The whole environment is defined in Terraform, so I can build it, test it and destroy it to control cost.

**Status:** the API and database ran successfully on AWS. It is not a public demo yet: there is no frontend, HTTPS or browser sign-in on AWS, and access was limited to my own IP address. I shut it down after testing, so there is no live URL.

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

- No HTTPS, frontend or browser sign-in on AWS. Google sign-in now works in the frontend locally (Docker Compose and the static export on `http://localhost:3000`), but none of it has been deployed or tested on AWS. The steps it would need are listed under "Future step: frontend and sign-in on AWS" below.
- This deployment doesn't set `OAUTH_AUDIENCE`. With the current code the API still starts, logs a warning, and rejects every `POST /auth/login`. The `refresh_version` column that sign-out uses is added automatically the first time the API or `scripts/migrate_authz.py` connects.
- Document upload (`POST /ingest/upload`) was added after this deployment. It works with Docker Compose locally but hasn't been deployed or tested on AWS. The path-based `/ingest` now returns 404 unless `APP_ENV` is `development` or `dev`.
- After an upload, only the API process that handled it refreshes its in-memory keyword (BM25) index. Other processes find new documents through vector search only until they restart. This deployment runs one task, but running more than one needs a shared fix first, such as keyword search in Postgres or a refresh signal between tasks.
- FastAPI receives a whole upload before checking its size, so an oversized file still arrives before the 413 is returned. A request size cap at the load balancer would be needed.
- Terraform state is stored on my laptop, and deployments are manual, with no CI/CD yet.
- The database is a single instance with no backups, because this is a learning environment holding no real data.
- This setup is not reviewed for real client or patient data.

## Future step: frontend and sign-in on AWS

Not done, and not tested. This is what the sign-in design needs from AWS.

The refresh token is a `Secure`, `SameSite=Strict` cookie on `Path=/auth`, so the browser must see the frontend and the API as the same site, over HTTPS. The simplest way is one CloudFront distribution in front of both:

- **Origins:** the S3 bucket holding `frontend/out/` (with origin access control), and the API's load balancer.
- **Default behavior (`*`):** the S3 origin, normal caching. S3 doesn't resolve folder index files, so a CloudFront Function must rewrite paths ending in `/` to `.../index.html` (the export uses `trailingSlash`, for example `/management/` maps to `management/index.html`).
- **API behaviors, routed to the load balancer:** `/auth/*`, `/me`, `/query`, `/draft`, `/ingest/*` and `/health`. For each:
  - Allowed methods: GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE.
  - Caching disabled (the managed `CachingDisabled` policy).
  - An origin request policy that forwards all viewer headers except `Host` (the managed `AllViewerExceptHostHeader`), so these reach the API: `Authorization` (the access token, and the Google ID token at login), `Content-Type` (including multipart uploads), `X-ConsultRAG-CSRF`, `Origin`, and the `Cookie` header carrying `consultrag_refresh`. Check against the current AWS documentation when building this, because CloudFront treats `Authorization` specially.
  - Response headers, including `Set-Cookie` from `/auth/login` and `/auth/logout`, must pass through unchanged.
- **Viewer protocol:** redirect HTTP to HTTPS. The cookie is `Secure`, so sign-in doesn't work over plain HTTP outside `localhost`.
- **CloudFront to the load balancer:** the load balancer is HTTP-only today, which would leave that leg unencrypted. Add an HTTPS listener (an ACM certificate), and allow traffic only from CloudFront (its managed prefix list plus a secret custom header the load balancer checks).

Settings that go with it:

- Build the frontend with `NEXT_PUBLIC_API_BASE_URL` set to the CloudFront URL (`https://<distribution>`), and `NEXT_PUBLIC_GOOGLE_CLIENT_ID` set to the OAuth client ID.
- On the API task: `OAUTH_AUDIENCE` set to the same client ID, `CORS_ALLOWED_ORIGINS` set to the CloudFront URL (requests are same-origin then, but this keeps the allowlist explicit), `APP_ENV=production`, and `DEV_AUTH_BYPASS` unset or false.
- In Google Cloud Console, add `https://<distribution>` (or the custom domain) as an authorized JavaScript origin.

## Rebuild it

Requires AWS CLI v2, Terraform, Docker and an AWS profile named `consultrag`. Commands are for Windows PowerShell. Running this creates billable resources.

```powershell
cd infra\terraform
terraform init
Copy-Item terraform.tfvars.example terraform.tfvars   # then add your public IP
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
