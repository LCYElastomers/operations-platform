from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "operations-platform-api"
    assert body["version"]


def test_health_rejects_non_get(client: TestClient) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
