"""Проверки системных endpoint приложения."""

from fastapi.testclient import TestClient

from app.main import app, asgi_app

client = TestClient(app)


def test_health_returns_service_status() -> None:
    """Health-check возвращает успешный статус сервиса."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "training-simulator-112",
    }


def test_socket_wrapper_passes_rest_requests_to_fastapi() -> None:
    response = TestClient(asgi_app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
