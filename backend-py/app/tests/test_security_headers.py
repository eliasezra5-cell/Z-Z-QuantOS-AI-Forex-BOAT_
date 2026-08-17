"""Tests for the security headers middleware (Task 2).

Verifies every HTTP response carries the configured security headers, HSTS is
emitted for https (X-Forwarded-Proto) requests only, and the FastAPI docs page
remains served.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("DATA_DIR", "/tmp/quantos_security_headers_test")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"


def test_health_response_has_all_security_headers():
    response = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "geolocation=(), microphone=(), camera=()"


def test_hsts_not_set_on_plain_http():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "strict-transport-security" not in response.headers
    assert response.headers["content-security-policy"] == CSP


def test_docs_route_is_not_broken_by_headers():
    response = client.get("/api/docs", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200
    assert "content-security-policy" in response.headers


def test_headers_apply_to_error_responses():
    response = client.get("/api/does-not-exist", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 404
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-frame-options"] == "DENY"
