"""Auth tests — passcode + JWT."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import (
    verify_passcode, create_owner_token, decode_owner_token, is_valid_token,
)
from app.main import app

client = TestClient(app)


def test_verify_passcode_correct():
    settings.PERSONAL_PASSCODE = "test-passcode-123"
    assert verify_passcode("test-passcode-123") is True


def test_verify_passcode_wrong():
    settings.PERSONAL_PASSCODE = "test-passcode-123"
    assert verify_passcode("wrong") is False
    assert verify_passcode("") is False


def test_jwt_create_and_decode():
    token = create_owner_token()
    payload = decode_owner_token(token)
    assert payload["sub"] == "owner"
    assert "exp" in payload


def test_jwt_invalid_raises():
    with pytest.raises(ValueError):
        decode_owner_token("not.a.token")


def test_is_valid_token():
    token = create_owner_token()
    assert is_valid_token(token) is True
    assert is_valid_token(None) is False
    assert is_valid_token("garbage") is False


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_app_info_endpoint():
    r = client.get("/api/info")
    assert r.status_code == 200
    body = r.json()
    assert "name" in body
    assert "owner_name" in body
    assert "features" in body


def test_unauthenticated_me_is_401():
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_login_correct_passcode():
    settings.PERSONAL_PASSCODE = "test-passcode-123"
    r = client.post("/api/v1/auth/login", json={"passcode": "test-passcode-123"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_passcode():
    settings.PERSONAL_PASSCODE = "test-passcode-123"
    r = client.post("/api/v1/auth/login", json={"passcode": "wrong"})
    assert r.status_code == 401


def test_authenticated_me_succeeds():
    settings.PERSONAL_PASSCODE = "test-passcode-123"
    r = client.post("/api/v1/auth/login", json={"passcode": "test-passcode-123"})
    token = r.json()["access_token"]
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    body = r2.json()
    assert "display_name" in body
