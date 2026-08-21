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
            "asset_id": "PUMP-101",
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
    metrics = client.get("/metrics").json()
    assert metrics["events"] == 1
    assert metrics["incidents"] == 1
    assert metrics["actions"] == 1
    assert len(client.get("/audit").json()) >= 3
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


def test_api_processes_queued_actions_and_resets():
    client = TestClient(create_test_app())
    assert client.post("/demo/seed").status_code == 200
    response = client.post(
        "/events",
        json={
            "asset_id": "GATEWAY-7",
            "source": "warehouse",
            "category": "offline",
            "severity": 91,
            "message": "Synthetic gateway outage with transient executor",
            "executor_mode": "transient_failure",
        },
    )
    assert response.status_code == 200

    maintenance = client.post("/maintenance/process-actions").json()

    assert maintenance == {"processed": 1, "succeeded": 1, "failed": 0}
    action = client.get("/actions").json()[0]
    assert action["state"] == "succeeded"
    assert action["attempts"] == 2

    reset = client.delete("/admin/reset").json()

    assert reset["deleted"]["events"] == 1
    assert client.get("/metrics").json()["events"] == 0
