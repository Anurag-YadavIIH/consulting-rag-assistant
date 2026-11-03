FROM python:3.11-slim

WORKDIR /app

# Keep the Hugging Face cache inside the image, in a path the app user can read.
ENV HF_HOME=/app/.hf-cache

COPY requirements.txt requirements-api.txt ./

# Install CPU-only PyTorch first. Otherwise sentence-transformers pulls the
# much larger NVIDIA GPU build, which this service never uses.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements-api.txt

# Bake the embedding model into the image so new containers start without a download.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# scripts/ is included so database migrations can run as a one-off task from this image.
COPY src ./src
COPY scripts ./scripts

ENV PYTHONPATH=/app/src
# The model is already in the image; never contact Hugging Face at runtime.
ENV HF_HUB_OFFLINE=1

# Do not run as root in production.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
# Keep-alive longer than the load balancer's idle timeout (at most 130 s, see
# infra/terraform/service.tf), as AWS recommends; uvicorn's 5 s default lets
# the load balancer reuse a connection the app just closed, giving a 502.
CMD ["uvicorn", "consultrag.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "150"]
