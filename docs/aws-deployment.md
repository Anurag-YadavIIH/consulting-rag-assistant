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

- No HTTPS, frontend or browser sign-in on AWS. The frontend still only supports a local development login.
- `/ingest` reads a file path on the server, so cloud ingestion needs an upload flow, such as S3.
- Terraform state is stored on my laptop, and deployments are manual, with no CI/CD yet.
- The database is a single instance with no backups, because this is a learning environment holding no real data.
- This setup is not reviewed for real client or patient data.

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

When finished, run `terraform destroy`.

## How this was built

I ran the deployment on my own AWS account, tested it and made the decisions. Claude, an AI assistant, helped me plan it, write the Terraform and code changes, and debug problems.
