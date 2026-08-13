from fastapi.testclient import TestClient

from support_operations_intelligence_platform.api.app import create_test_app


def test_health_and_ready_start_empty():
    client = TestClient(create_test_app())

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready", "assets": 0}


def test_seed_and_ingest_event_through_api():
    client = TestClient(create_test_app())
    assert client.post("/demo/seed").status_code == 200
    assert len(client.get("/assets").json()) == 3
    assert len(client.get("/rules").json()) == 2

    response = client.post(
        "/events",
        json={
            "asset_external_id": "PUMP-101",
            "source": "north-gateway",
            "category": "offline",
            "severity": 92,
            "message": "Synthetic heartbeat failure detected",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["incident"]["state"] == "open"
    assert body["action"]["state"] == "queued"
    assert len(client.get("/incidents").json()) == 1
    assert len(client.get("/actions").json()) == 1
    assert client.post("/jobs/health-sweep").json() == {
        "job_name": "health_sweep",
        "status": "succeeded",
        "actions_created": 0,
    }


def test_api_rejects_duplicate_asset():
    client = TestClient(create_test_app())

    payload = {"external_id": "LAB-1", "name": "Lab asset", "group": "demo"}
    assert client.post("/assets", json=payload).status_code == 200
    assert client.post("/assets", json=payload).status_code == 409


def test_api_returns_404_for_unknown_asset_event():
    client = TestClient(create_test_app())

    response = client.post(
        "/events",
        json={
            "asset_external_id": "MISSING",
            "source": "north-gateway",
            "category": "offline",
            "severity": 90,
            "message": "Synthetic event for missing asset",
        },
    )

    assert response.status_code == 404
