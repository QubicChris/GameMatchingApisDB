"""Shared pytest fixtures for the dashboard API tests."""
import bcrypt
import pytest
import yaml
from fastapi.testclient import TestClient

TEST_PASSWORD = "correct-horse"


@pytest.fixture(autouse=True)
def auth_file(tmp_path, monkeypatch):
    path = tmp_path / "auth.yaml"
    hashed = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    path.write_text(yaml.safe_dump({
        "cookie": {"expiry_days": 1, "key": "test-cookie-key-not-secret-0123456789abcdef", "name": "x"},
        "credentials": {"usernames": {"Tester": {"name": "Test User", "password": hashed}}},
    }))
    monkeypatch.setenv("DASHBOARD_AUTH_FILE", str(path))
    monkeypatch.delenv("DASHBOARD_SECRET", raising=False)
    from webapi import auth
    auth._failures.clear()
    return path


@pytest.fixture
def client(tmp_path):
    from webapi.app import create_app
    return TestClient(create_app(dist=tmp_path / "no-dist"))


@pytest.fixture
def authed(client):
    r = client.post("/api/auth/login", json={"username": "tester", "password": TEST_PASSWORD})
    assert r.status_code == 200
    return client
