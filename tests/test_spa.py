from fastapi.testclient import TestClient

from webapi.app import create_app


def make_client(tmp_path, with_dist=True):
    dist = tmp_path / "dist"
    if with_dist:
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text('<div id="root"></div>')
        (dist / "assets" / "app.js").write_text("console.log(1)")
    return TestClient(create_app(dist=dist))


def test_index_and_deep_link(tmp_path):
    c = make_client(tmp_path)
    assert 'id="root"' in c.get("/").text
    assert 'id="root"' in c.get("/games/5").text


def test_assets(tmp_path):
    c = make_client(tmp_path)
    r = c.get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_api_unknown_is_json_404(tmp_path):
    r = make_client(tmp_path).get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not found"}


def test_path_traversal(tmp_path, auth_file):
    r = make_client(tmp_path).get("/..%2F..%2Fauth.yaml")
    assert "credentials" not in r.text
    assert "password" not in r.text


def test_no_dist(tmp_path):
    assert make_client(tmp_path, with_dist=False).get("/").status_code == 404
