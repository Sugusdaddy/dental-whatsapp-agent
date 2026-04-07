"""
Tests del webhook FastAPI.
Usa TestClient de FastAPI — no necesita servidor levantado.
"""

import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset():
    from dental.core.database import reset_db
    reset_db()


@pytest.fixture
def client():
    from dental.api.webhook import app
    return TestClient(app, raise_server_exceptions=False)


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"
        assert "Sonríe" in data["clinic_demo"]


class TestWebhookVerification:
    def test_verify_ok(self, client):
        # FastAPI convierte hub.mode → hub_mode (puntos a underscores)
        r = client.get(
            "/webhook/clinic_001",
            params={
                "hub_mode":         "subscribe",
                "hub_challenge":    "abc123",
                "hub_verify_token": "dev_secret_changeme",
            },
        )
        assert r.status_code == 200
        assert "abc123" in r.text

    def test_verify_wrong_token(self, client):
        r = client.get(
            "/webhook/clinic_001",
            params={
                "hub_mode":         "subscribe",
                "hub_challenge":    "abc123",
                "hub_verify_token": "wrong_token",
            },
        )
        assert r.status_code == 403

    def test_verify_unknown_clinic(self, client):
        r = client.get(
            "/webhook/clinic_999",
            params={
                "hub.mode":         "subscribe",
                "hub.verify_token": "dev_secret_changeme",
            },
        )
        assert r.status_code == 404


class TestWebhookMessages:

    def _make_payload(self, phone: str, text: str, name: str = None) -> dict:
        """Construye un payload realista de WhatsApp Cloud API."""
        contact = {"wa_id": phone}
        if name:
            contact["profile"] = {"name": name}
        return {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": phone,
                            "id":   "wamid.test123",
                            "type": "text",
                            "text": {"body": text},
                        }],
                        "contacts": [contact],
                    }
                }]
            }]
        }

    def test_rejects_invalid_json(self, client):
        r = client.post(
            "/webhook/clinic_001",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    def test_ignores_non_text_message(self, client):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "+34612345678",
                            "id":   "wamid.test",
                            "type": "image",
                        }],
                        "contacts": [],
                    }
                }]
            }]
        }
        r = client.post("/webhook/clinic_001", json=payload)
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"

    def test_ignores_delivery_receipt(self, client):
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.test"}]}}]}]}
        r = client.post("/webhook/clinic_001", json=payload)
        assert r.status_code == 200
        assert r.json()["status"] == "ignored"

    def test_unknown_clinic_returns_404(self, client):
        payload = self._make_payload("+34612345678", "Hola")
        r = client.post("/webhook/clinic_999", json=payload)
        assert r.status_code == 404

    @pytest.mark.skipif(
        not __import__("os").getenv("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY no configurada"
    )
    def test_processes_text_message(self, client):
        payload = self._make_payload("+34699000001", "¿Cuáles son vuestros horarios?", "Test User")
        r = client.post("/webhook/clinic_001", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "processed"
        assert len(data["response"]) > 5
        print(f"\n[webhook] respuesta: {data['response'][:100]}")
