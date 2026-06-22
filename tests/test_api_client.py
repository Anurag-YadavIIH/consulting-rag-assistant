"""
ui/api_client.py tests — httpx mocked, fully offline. Does NOT import
streamlit and does not test ui/app.py's rendering; this only covers the HTTP
client functions.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui"))

from api_client import (
    ForbiddenError,
    NotAuthenticatedError,
    ServerError,
    ingest,
    me,
    query,
)


def _response(status_code: int, json_body: dict, url: str = "http://localhost:8000/x") -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(status_code=status_code, json=json_body, request=request)


# --- happy paths --------------------------------------------------------------


def test_me_happy_path_parses_correctly():
    body = {"user_id": "1", "engagements": ["acme"], "is_admin": False, "clearance": 2}
    with patch("httpx.get", return_value=_response(200, body)):
        result = me()
    assert result.user_id == "1"
    assert result.engagements == ["acme"]
    assert result.is_admin is False
    assert result.clearance == 2


def test_query_happy_path_parses_correctly():
    body = {
        "answer": "The barrier is reimbursement uncertainty.",
        "citations": [{"source_path": "data/sample/acme.txt", "locator": "", "score": 0.83}],
    }
    with patch("httpx.post", return_value=_response(200, body)):
        result = query("What is the barrier?", engagement="acme")
    assert result.answer == "The barrier is reimbursement uncertainty."
    assert len(result.citations) == 1
    assert result.citations[0].source_path == "data/sample/acme.txt"
    assert result.citations[0].score == 0.83


def test_query_with_no_citations_parses_correctly():
    body = {"answer": "No accessible material matched this question.", "citations": []}
    with patch("httpx.post", return_value=_response(200, body)):
        result = query("anything")
    assert result.citations == []


def test_ingest_happy_path_parses_correctly():
    body = {"chunks_ingested": 4}
    with patch("httpx.post", return_value=_response(200, body)):
        n = ingest("data/sample", "acme", clearance=2)
    assert n == 4


# --- typed error surfacing ----------------------------------------------------


def test_me_401_raises_not_authenticated_error():
    with patch("httpx.get", return_value=_response(401, {"detail": "missing Authorization header"})):
        with pytest.raises(NotAuthenticatedError) as exc_info:
            me()
    assert exc_info.value.status_code == 401
    assert "missing Authorization header" in exc_info.value.detail


def test_query_403_raises_forbidden_error():
    with patch("httpx.post", return_value=_response(403, {"detail": "not a member of this engagement"})):
        with pytest.raises(ForbiddenError) as exc_info:
            query("anything", engagement="globex")
    assert exc_info.value.status_code == 403
    assert "not a member" in exc_info.value.detail


def test_ingest_403_raises_forbidden_error():
    with patch("httpx.post", return_value=_response(403, {"detail": "cannot ingest at a clearance above your own"})):
        with pytest.raises(ForbiddenError):
            ingest("data/sample", "acme", clearance=99)


def test_query_500_raises_server_error():
    with patch("httpx.post", return_value=_response(500, {"detail": "internal error"})):
        with pytest.raises(ServerError) as exc_info:
            query("anything")
    assert exc_info.value.status_code == 500


def test_me_503_raises_server_error():
    with patch("httpx.get", return_value=_response(503, {"detail": "service unavailable"})):
        with pytest.raises(ServerError):
            me()


def test_error_detail_falls_back_to_text_when_body_is_not_json():
    request = httpx.Request("GET", "http://localhost:8000/me")
    resp = httpx.Response(status_code=401, text="not json", request=request)
    with patch("httpx.get", return_value=resp):
        with pytest.raises(NotAuthenticatedError) as exc_info:
            me()
    assert "not json" in exc_info.value.detail
