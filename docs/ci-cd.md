# CI/CD

ConsultRAG has continuous integration (CI) with GitHub Actions in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). There is **no automated deployment (CD) yet**: nothing in the workflow deploys to AWS, calls an AWS API or holds AWS credentials. Deployment is still the manual process in [aws-frontend-runbook.md](aws-frontend-runbook.md).

**Status:** every job's checks pass when run locally. The first run on GitHub is still pending, and this page will be updated with its results.

## When it runs

- On every pull request.
- On every push to `main`.

A new push to the same pull request cancels the run that is still going. Runs on `main` are never cancelled, so every commit on `main` gets a complete result.

## Jobs

The job names are fixed so they can be made required checks later.

| Job | What it does |
|---|---|
| **Backend tests** | Python 3.11 with a `pgvector/pgvector:pg16` Postgres service container. Installs CPU-only PyTorch and `requirements-api.txt`, runs the full pytest suite, then fails if **any** test was skipped. Every database test skips itself when Postgres is unreachable, so this check proves they really ran. Terraform is installed too, because one pytest test runs `terraform test`. The tests use a deterministic hash embedder, and `HF_HUB_OFFLINE=1` makes any accidental model download fail instead of downloading. |
| **Frontend** | Node 22: `npm ci`, the vitest suite, `tsc --noEmit` and the static `next build`, with placeholder public values (`http://localhost:8000` and a dummy Google client ID). |
| **Terraform** | Terraform 1.9.8 in `infra/terraform`: `fmt -check -recursive`, `init -backend=false`, `validate`, and `terraform test`. The test file [`infra/terraform/tests/plan.tftest.hcl`](../infra/terraform/tests/plan.tftest.hcl) plans the real configuration with mocked AWS and random providers, so it needs no credentials. It checks the variable rules and a few security properties: the database is private and encrypted, the frontend bucket blocks public access, the load balancer answers 403 by default, CloudFront redirects to HTTPS, and direct debug access is off. |
| **Docker build** | Builds `docker/api/Dockerfile` with Buildx and the GitHub Actions build cache. The image is **not pushed** anywhere. |
| **Secret scan** | [Gitleaks](https://github.com/gitleaks/gitleaks) over the full git history, from the official image pinned by digest, with `--redact` so a matched value is never printed. |
| **CI passed** | Runs after the five jobs above and passes only if all of them succeeded. It is meant to be the single required check. |

## Security choices

- The workflow token has `contents: read` only.
- The workflow uses no repository secrets, and `pull_request_target` is not used, so pull requests from forks receive nothing they could leak.
- Third-party actions are pinned to full commit SHAs with the version in a comment. The gitleaks image is pinned by digest.
- Checkout uses `persist-credentials: false`, so the token is not left in the git config for later steps.
- Every job has a timeout.

## Checking locally

The same checks can be run on a developer machine:

```bash
# Backend (needs Postgres with pgvector, e.g. `docker compose up -d postgres`)
python -m pytest -q -rs

# Frontend
cd frontend && npm ci && npm test && npx tsc --noEmit && npm run build

# Terraform (no credentials needed)
cd infra/terraform && terraform fmt -check -recursive && terraform init -backend=false && terraform validate && terraform test

# Workflow lint and secret scan
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:1.7.12 .github/workflows/ci.yml
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.1 git /repo --redact
```

## Not built yet

- Automated deployment to AWS. Images are not pushed to ECR, and nothing runs `terraform plan` or `apply` against a real account.
- Branch protection. The checks run, but no check is required to merge yet.
