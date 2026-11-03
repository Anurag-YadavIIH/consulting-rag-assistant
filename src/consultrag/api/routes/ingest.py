"""
Ingestion routes, both wrapping the existing IngestionPipeline (redaction
always runs before embedding and storage):

  * POST /ingest/upload: multipart file upload. The way to ingest when the
    server doesn't hold the files (any cloud deployment).
  * POST /ingest: a path on the server's filesystem. Development only: it
    returns 404 unless APP_ENV is explicitly development/dev (the same
    allowlist as DEV_AUTH_BYPASS), because it lets a caller ingest any path
    the server can read. Kept for the Streamlit UI's local use.

Engagement and clearance are request-declared TARGETS, validated against the
authenticated User server-side (never trusted): a caller may only ingest into
an engagement they belong to (or be a global admin), and never above their
own clearance. Both checks run before the pipeline (or the uploaded file) is
touched.
"""

from __future__ import annotations

import logging
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ...auth.dev_bypass import is_dev_auth_bypass_permitted
from ...config import settings
from ...ingestion.loaders import PdfLoader, PptxLoader, TextLoader
from ...pipeline import DocumentLoadError, DocumentTooLarge, IngestionPipeline
from ...rag import RAGEngine
from ...security.access import MAX_CLEARANCE, MIN_CLEARANCE, AccessPolicy, User
from ...vectorstore import DocumentReplaceForbidden
from ..deps import get_current_app_user, get_ingestion_pipeline, get_rag_engine
from ..schemas import IngestRequest, IngestResponse, UploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])

# Taken from the loaders themselves so this list can't drift from what the
# pipeline parses. Audio (AudioLoader) is deliberately excluded for now.
UPLOAD_EXTENSIONS = frozenset(TextLoader.extensions + PdfLoader.extensions + PptxLoader.extensions)
MAX_FILENAME_LENGTH = 255
_COPY_CHUNK_BYTES = 1024 * 1024


def _require_dev_environment() -> None:
    # Same whitelist as DEV_AUTH_BYPASS: unset, empty or misspelled APP_ENV
    # keeps the route disabled. 404 rather than 403: outside development the
    # route should look like it doesn't exist.
    if not is_dev_auth_bypass_permitted(settings.app_env):
        raise HTTPException(status_code=404, detail="Not Found")


def _authorize_ingest(user: User, engagement: str, clearance: int) -> None:
    if not AccessPolicy.is_admin(user) and engagement not in AccessPolicy.engagements_for(user):
        raise HTTPException(status_code=403, detail="not a member of this engagement")
    if clearance > user.clearance:
        raise HTTPException(
            status_code=403, detail="cannot ingest at a clearance above your own"
        )


def _refresh_keyword_index(engine: RAGEngine) -> None:
    # HybridRetriever's BM25 index is a snapshot taken when the engine is
    # built. Without a refresh, newly ingested chunks only reach the dense leg
    # and lose to every older chunk that scores in both legs. This refreshes
    # THIS process only; other API processes stay stale until they restart.
    refresh = getattr(engine.retriever, "refresh", None)
    if refresh is not None:
        refresh()


def clean_filename(raw: str | None) -> str:
    """The uploaded filename is user input. It is only ever used as a label
    (citations, chunk IDs, audit), never as a filesystem path: keep the last
    path component (either separator), drop control and format characters
    (e.g. NUL, newlines, right-to-left overrides), and bound the length."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    if name in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="the uploaded file has no usable name")
    if len(name) > MAX_FILENAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"filename is too long (max {MAX_FILENAME_LENGTH} characters)",
        )
    return name


@router.post("/ingest", response_model=IngestResponse,
             dependencies=[Depends(_require_dev_environment)])
def ingest(
    body: IngestRequest,
    user: User = Depends(get_current_app_user),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    engine: RAGEngine = Depends(get_rag_engine),
) -> IngestResponse:
    _authorize_ingest(user, body.engagement, body.clearance)
    n = pipeline.ingest_path(
        body.path, engagement=body.engagement, clearance=body.clearance, user_id=user.user_id
    )
    _refresh_keyword_index(engine)
    return IngestResponse(chunks_ingested=n)


@router.post("/ingest/upload", response_model=UploadResponse)
def ingest_upload(
    file: UploadFile = File(...),
    engagement: str = Form(...),
    # Clearance levels are 1 to 3 (security/access.py); FastAPI returns 422 outside them.
    clearance: int = Form(1, ge=MIN_CLEARANCE, le=MAX_CLEARANCE),
    user: User = Depends(get_current_app_user),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    engine: RAGEngine = Depends(get_rag_engine),
) -> UploadResponse:
    _authorize_ingest(user, engagement, clearance)

    name = clean_filename(file.filename)
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type '{suffix or name}'. "
                   f"Supported: {', '.join(sorted(UPLOAD_EXTENSIONS))}",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    # The directory (and everything in it) is removed on exit, including when
    # anything below raises. The file inside gets a fixed name; the uploaded
    # name never touches the filesystem.
    with tempfile.TemporaryDirectory(prefix="consultrag-upload-") as tmp:
        dest = Path(tmp) / f"upload{suffix}"
        written = 0
        with open(dest, "wb") as out:
            while chunk := file.file.read(_COPY_CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"file is larger than the {settings.max_upload_mb} MB upload limit",
                    )
                out.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="the uploaded file is empty")

        try:
            n = pipeline.ingest_path(
                dest,
                engagement=engagement,
                clearance=clearance,
                user_id=user.user_id,
                source_name=name,
                replace_max_clearance=None if AccessPolicy.is_admin(user) else user.clearance,
                max_chunks=settings.max_upload_chunks,
            )
        except DocumentReplaceForbidden:
            # Deliberately says nothing about the existing document's
            # clearance or contents.
            raise HTTPException(
                status_code=409,
                detail="a document with this name already exists in this engagement "
                       "and you are not permitted to replace it",
            ) from None
        except DocumentTooLarge as e:
            # The limit only; never the document's text or its chunk count.
            raise HTTPException(
                status_code=413,
                # ~250 words per chunk: 350-token windows overlap by 50, and
                # the token count includes punctuation.
                detail=f"the document has too much text to process: the limit is "
                       f"{e.max_chunks} chunks (roughly {e.max_chunks * 250:,} words). "
                       f"Split it into smaller files and upload them separately.",
            ) from None
        except DocumentLoadError as e:
            logger.info("upload could not be read (%s): %s", suffix, e)
            raise HTTPException(
                status_code=422, detail=f"could not read the file as {suffix}"
            ) from None

    if n == 0:
        raise HTTPException(status_code=422, detail="no extractable text found in the file")
    _refresh_keyword_index(engine)
    return UploadResponse(chunks_ingested=n, source_name=name)
