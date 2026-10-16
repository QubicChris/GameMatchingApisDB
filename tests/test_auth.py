import yaml

TEST_PASSWORD = "correct-horse"  # must match tests/conftest.py

BAD = "Incorrect username or password."


def login(client, user="tester", pw=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"username": user, "password": pw})


def test_login_success(client):
    r = login(client)
    assert r.status_code == 200
    assert r.json() == {"username": "Tester", "name": "Test User"}
    assert "pregames_session" in client.cookies


def test_username_case_insensitive(client):
    assert login(client, "TESTER").status_code == 200


def test_wrong_password_and_unknown_user_same_error(client):
    r1 = login(client, pw="nope")
    r2 = login(client, user="ghost")
    assert r1.status_code == 401 and r2.status_code == 401
    assert r1.json()["detail"] == BAD and r2.json()["detail"] == BAD


def test_me_requires_cookie(client):
    assert client.get("/api/auth/me").status_code == 401
    login(client)
    assert client.get("/api/auth/me").status_code == 200


def test_tampered_cookie(client):
    client.cookies.set("pregames_session", "abc")
    assert client.get("/api/auth/me").status_code == 401


def test_logout(authed):
    assert authed.post("/api/auth/logout").status_code == 204
    authed.cookies.clear()
    assert authed.get("/api/auth/me").status_code == 401


def test_lockout_after_10_failures(client):
    for _ in range(10):
        assert login(client, pw="bad").status_code == 401
    assert login(client).status_code == 429


def test_removed_user_loses_session(authed, auth_file):
    cfg = yaml.safe_load(auth_file.read_text())
    cfg["credentials"]["usernames"] = {}
    auth_file.write_text(yaml.safe_dump(cfg))
    assert authed.get("/api/auth/me").status_code == 401


def test_summary_needs_login_health_does_not(client):
    assert client.get("/api/summary").status_code == 401
    assert client.get("/api/health").status_code == 200
