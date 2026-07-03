from fastapi.testclient import TestClient

from sandbox_service.api import create_app, get_runner
from sandbox_service.runners.fake import FakeRunner


def _client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_runner] = lambda: FakeRunner()
    return TestClient(app)


def test_health_and_ready_endpoints() -> None:
    client = _client()

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_openapi_schema_includes_run_endpoint() -> None:
    client = _client()

    schema = client.get("/openapi.json").json()

    assert "/v1/runs" in schema["paths"]
    assert schema["info"]["title"] == "Sandbox Utility Service"


def test_run_endpoint_uses_runner() -> None:
    client = _client()

    response = client.post("/v1/runs", json={"code": "print(2 + 2)"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["stdout"].startswith("fake runner received")
    assert payload["exit_code"] == 0
    assert payload["artifacts"] == []


def test_request_validation_rejects_empty_code() -> None:
    client = _client()

    response = client.post("/v1/runs", json={"code": ""})

    assert response.status_code == 422


def test_request_validation_rejects_input_with_two_content_sources() -> None:
    client = _client()

    response = client.post(
        "/v1/runs",
        json={
            "code": "print('x')",
            "inputs": [
                {
                    "name": "input.txt",
                    "type": "text",
                    "content_inline": "hello",
                    "content_base64": "aGVsbG8=",
                }
            ],
        },
    )

    assert response.status_code == 422
