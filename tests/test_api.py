"""Backend integration tests over fixtures (no MCP)."""

from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)


def test_get_data_scores_fixture(temp_data):
    # NOTE: this path scores with the real clock (now=None), so ranking ORDER is
    # time-dependent — deterministic ordering is covered in test_scoring with a
    # fixed `now`. Here we only assert time-independent structure.
    r = client.get("/api/data")
    assert r.status_code == 200
    data = r.json()
    # 7 non-meeting items are always present; the 2 fixture meetings may be
    # filtered as "past" depending on the wall clock, so allow a range.
    assert 7 <= len(data["ranked"]) <= 9
    assert all(isinstance(it["score"], (int, float)) and it["tier"] in {"now", "soon", "later"} for it in data["ranked"])
    assert any(it["id"] == "notion:task:abc100" for it in data["ranked"])


def test_get_rules(temp_data):
    r = client.get("/api/rules")
    assert r.status_code == 200
    assert r.json()["version"] == 1


def test_put_rules_rerescores(temp_data):
    rules = client.get("/api/rules").json()
    rules["vip_people"] = []  # drop Jane's VIP boost
    r = client.put("/api/rules", json=rules)
    assert r.status_code == 200
    data = client.get("/api/data").json()
    mention = next(i for i in data["ranked"] if i["id"] == "teams:msg:AAQk001")
    assert mention["factors"]["vip"] == 0


def test_put_invalid_rules_422(temp_data):
    rules = client.get("/api/rules").json()
    rules["do_now_limit"] = -1
    r = client.put("/api/rules", json=rules)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_rules"


def test_override_bumps_and_persists(temp_data):
    client.get("/api/data")  # seed
    r = client.post("/api/override", json={"id": "notion:task:abc100", "delta": 30})
    assert r.status_code == 200
    item = next(i for i in r.json()["ranked"] if i["id"] == "notion:task:abc100")
    assert item["factors"]["manual"] == 30
    # persisted to overrides.json and reflected on next read
    assert config.OVERRIDES_PATH.exists()
    data = client.get("/api/data").json()
    assert next(i for i in data["ranked"] if i["id"] == "notion:task:abc100")["factors"]["manual"] == 30


def test_override_accumulates_and_resets(temp_data):
    client.post("/api/override", json={"id": "teams:dm:AAQk002", "delta": 20})
    client.post("/api/override", json={"id": "teams:dm:AAQk002", "delta": 20})
    data = client.post("/api/override", json={"id": "teams:dm:AAQk002", "delta": -40}).json()
    # back to zero → manual cleared
    assert next(i for i in data["ranked"] if i["id"] == "teams:dm:AAQk002")["factors"]["manual"] == 0
    import json as _json
    assert "teams:dm:AAQk002" not in _json.loads(config.OVERRIDES_PATH.read_text())


def test_override_invalid_payload_422(temp_data):
    r = client.post("/api/override", json={"id": 123, "delta": "x"})
    assert r.status_code == 422


def test_refresh_without_collector_rescores(temp_data):
    r = client.post("/api/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ok"] is True
    # history line appended
    assert config.HISTORY_PATH.exists()


def test_history_accumulates(temp_data):
    assert client.get("/api/history").json() == []
    client.post("/api/refresh")
    client.post("/api/refresh")
    hist = client.get("/api/history").json()
    assert len(hist) == 2
    assert "now" in hist[0] and "items_total" in hist[0]


def test_health_and_status(temp_data):
    client.post("/api/refresh")
    h = client.get("/api/health").json()
    assert "sources_health" in h
    assert h["running"] is False
    s = client.get("/api/status").json()
    assert s["ok"] is True
