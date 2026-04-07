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


# ─────────────────────────────────────────────
# NUEVOS ENDPOINTS: clinic detail, update, takeover
# ─────────────────────────────────────────────

class TestClinicDetail:
    def test_get_clinic_detail_ok(self, client):
        r = client.get("/api/clinics/clinic_001")
        assert r.status_code == 200
        data = r.json()
        assert data["clinic_id"] == "clinic_001"
        assert "Sonríe" in data["name"]
        assert data["whatsapp_connected"] is True
        assert isinstance(data["services"], list)
        assert len(data["services"]) > 0

    def test_get_clinic_detail_404(self, client):
        r = client.get("/api/clinics/does_not_exist")
        assert r.status_code == 404

    def test_patch_clinic_updates_fields(self, client):
        r = client.patch(
            "/api/clinics/clinic_001",
            json={"name": "Nueva Sonríe", "phone": "+34999888777"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Nueva Sonríe"
        assert data["phone"] == "+34999888777"

        # Verifica que persiste
        r2 = client.get("/api/clinics/clinic_001")
        assert r2.json()["name"] == "Nueva Sonríe"

    def test_patch_clinic_404(self, client):
        r = client.patch("/api/clinics/nope", json={"name": "X"})
        assert r.status_code == 404

    def test_patch_clinic_ignores_unknown_fields(self, client):
        # Campos no editables se ignoran silenciosamente
        r = client.patch(
            "/api/clinics/clinic_001",
            json={"name": "Foo", "evil": "drop table"},
        )
        assert r.status_code == 200


class TestHumanTakeover:
    def test_takeover_persists(self, client):
        # 1. Inicialmente no hay takeover
        r = client.get("/api/conversations/clinic_001")
        convs = r.json()["conversations"]
        assert all(not c["human_takeover"] for c in convs)

        # 2. Activar takeover para el paciente demo
        r = client.post(
            "/api/takeover/clinic_001",
            json={"phone": "+34612345678", "enable": True},
        )
        assert r.status_code == 200
        assert r.json()["human_takeover"] is True

        # 3. Ahora aparece como en takeover
        r = client.get("/api/conversations/clinic_001")
        convs = r.json()["conversations"]
        target = next(c for c in convs if c["phone"] == "+34612345678")
        assert target["human_takeover"] is True

        # 4. Liberar
        r = client.post(
            "/api/takeover/clinic_001",
            json={"phone": "+34612345678", "enable": False},
        )
        assert r.json()["human_takeover"] is False

        r = client.get("/api/conversations/clinic_001")
        target = next(c for c in r.json()["conversations"] if c["phone"] == "+34612345678")
        assert target["human_takeover"] is False

    def test_takeover_requires_phone(self, client):
        r = client.post("/api/takeover/clinic_001", json={})
        assert r.status_code == 400

    def test_takeover_404_clinic(self, client):
        r = client.post(
            "/api/takeover/nope",
            json={"phone": "+34612345678", "enable": True},
        )
        assert r.status_code == 404


class TestStatsAggregation:
    def test_stats_returns_correct_shape(self, client):
        r = client.get("/api/stats/clinic_001")
        assert r.status_code == 200
        data = r.json()
        # El frontend espera estos campos:
        for key in (
            "clinic_id", "clinic_name", "total_appointments",
            "confirmed", "pending", "cancelled",
        ):
            assert key in data
        assert data["total_appointments"] >= 1  # cita demo


class TestAppointmentsList:
    def test_list_appointments_returns_array(self, client):
        r = client.get("/api/appointments/clinic_001")
        assert r.status_code == 200
        data = r.json()
        assert "appointments" in data
        assert data["total"] >= 1
        # Verifica forma del item
        item = data["appointments"][0]
        for key in ("appointment_id", "patient_name", "datetime", "status", "treatment"):
            assert key in item

    def test_list_appointments_filter_by_status(self, client):
        r = client.get("/api/appointments/clinic_001?status=confirmed")
        assert r.status_code == 200
        for a in r.json()["appointments"]:
            assert a["status"] == "confirmed"

    def test_list_appointments_invalid_status(self, client):
        r = client.get("/api/appointments/clinic_001?status=garbage")
        assert r.status_code == 400

    def test_list_appointments_filter_when_upcoming(self, client):
        r = client.get("/api/appointments/clinic_001?when=upcoming")
        assert r.status_code == 200
        # La cita demo es a +2 días, debe aparecer
        assert r.json()["total"] >= 1

    def test_list_appointments_clinic_404(self, client):
        r = client.get("/api/appointments/nope")
        assert r.status_code == 404

    def test_list_appointments_limit(self, client):
        r = client.get("/api/appointments/clinic_001?limit=0")
        assert r.json()["total"] == 0


# ─────────────────────────────────────────────
# APPOINTMENTS LIST endpoint
# ─────────────────────────────────────────────

class TestAppointmentsList:
    def test_list_default(self, client):
        r = client.get("/api/appointments/clinic_001")
        assert r.status_code == 200
        data = r.json()
        assert "appointments" in data
        assert "total" in data
        assert isinstance(data["appointments"], list)

    def test_list_404(self, client):
        r = client.get("/api/appointments/nope")
        assert r.status_code == 404

    def test_filter_by_status(self, client):
        r = client.get("/api/appointments/clinic_001?status=confirmed")
        assert r.status_code == 200
        data = r.json()
        for a in data["appointments"]:
            assert a["status"] == "confirmed"

    def test_invalid_status_400(self, client):
        r = client.get("/api/appointments/clinic_001?status=invalid_status")
        assert r.status_code == 400

    def test_filter_when_upcoming(self, client):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Madrid"))
        r = client.get("/api/appointments/clinic_001?when=upcoming")
        assert r.status_code == 200
        for a in r.json()["appointments"]:
            assert datetime.fromisoformat(a["datetime"]) >= now

    def test_filter_when_past(self, client):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Europe/Madrid"))
        r = client.get("/api/appointments/clinic_001?when=past")
        for a in r.json()["appointments"]:
            assert datetime.fromisoformat(a["datetime"]) < now

    def test_limit(self, client):
        r = client.get("/api/appointments/clinic_001?limit=1")
        assert r.status_code == 200
        assert len(r.json()["appointments"]) <= 1

    def test_response_shape(self, client):
        r = client.get("/api/appointments/clinic_001")
        for a in r.json()["appointments"]:
            for key in (
                "appointment_id", "patient_phone", "patient_name", "datetime",
                "treatment", "dentist", "duration_min", "status",
                "confirmation_received",
            ):
                assert key in a


# ─────────────────────────────────────────────
# APPOINTMENT ACTIONS (confirm/cancel desde dashboard)
# ─────────────────────────────────────────────

class TestAppointmentActions:
    def test_confirm_appointment_ok(self, client):
        # apt_006 es la cita de hoy de María López en el seed
        r = client.post("/api/appointments/apt_006/confirm")
        assert r.status_code == 200
        data = r.json()
        assert data["appointment_id"] == "apt_006"
        assert data["confirmation_received"] is True

    def test_confirm_appointment_404(self, client):
        r = client.post("/api/appointments/no_existe/confirm")
        assert r.status_code == 404

    def test_cancel_appointment_ok(self, client):
        r = client.post(
            "/api/appointments/apt_010/cancel",
            json={"reason": "Imprevisto del paciente"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "cancelled"
        assert data["reason"] == "Imprevisto del paciente"

    def test_cancel_appointment_no_reason(self, client):
        r = client.post("/api/appointments/apt_011/cancel", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"

    def test_cancel_appointment_404(self, client):
        r = client.post("/api/appointments/nope/cancel", json={"reason": "x"})
        assert r.status_code == 404


# ─────────────────────────────────────────────
# EVENT LOGS (ring buffer)
# ─────────────────────────────────────────────

class TestEventLogs:
    def test_logs_404_for_unknown_clinic(self, client):
        r = client.get("/api/logs/no_existe")
        assert r.status_code == 404

    def test_logs_response_shape(self, client):
        r = client.get("/api/logs/clinic_001")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert "total" in data
        assert isinstance(data["events"], list)

    def test_logs_records_takeover_event(self, client):
        # Activar takeover → debe quedar registrado en logs
        client.post(
            "/api/takeover/clinic_001",
            json={"phone": "+34612345678", "enable": True},
        )
        r = client.get("/api/logs/clinic_001?type=takeover_on")
        assert r.status_code == 200
        events = r.json()["events"]
        assert len(events) >= 1
        assert any(e["phone"] == "+34612345678" for e in events)

    def test_logs_records_action_on_confirm(self, client):
        client.post("/api/appointments/apt_006/confirm")
        r = client.get("/api/logs/clinic_001?type=action")
        events = r.json()["events"]
        assert any("apt_006" in e["summary"] for e in events)

    def test_logs_filter_by_type(self, client):
        client.post(
            "/api/takeover/clinic_001",
            json={"phone": "+34611222333", "enable": True},
        )
        # Sin filtro
        r1 = client.get("/api/logs/clinic_001")
        # Con filtro
        r2 = client.get("/api/logs/clinic_001?type=takeover_on")
        assert len(r2.json()["events"]) <= len(r1.json()["events"])
        for e in r2.json()["events"]:
            assert e["type"] == "takeover_on"

    def test_logs_isolated_per_clinic(self, client):
        # Activar takeover en clinic_001
        client.post(
            "/api/takeover/clinic_001",
            json={"phone": "+34699001122", "enable": True},
        )
        # clinic_002 no debe ver ese evento
        r = client.get("/api/logs/clinic_002")
        events = r.json()["events"]
        assert all(e["clinic_id"] == "clinic_002" for e in events)
        assert not any(e["phone"] == "+34699001122" for e in events)


# ─────────────────────────────────────────────
# SEED DATA — verificar que el seed enriquecido se cargó
# ─────────────────────────────────────────────

class TestSeedData:
    def test_two_clinics(self, client):
        # Ambas clínicas deben existir
        r1 = client.get("/api/clinics/clinic_001")
        r2 = client.get("/api/clinics/clinic_002")
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_multiple_appointments(self, client):
        r = client.get("/api/appointments/clinic_001?when=all&limit=100")
        assert r.status_code == 200
        # El seed crea ≥10 citas en clinic_001
        assert len(r.json()["appointments"]) >= 10

    def test_active_conversations_not_zero(self, client):
        # El seed pone last_contact reciente en varios pacientes
        # → la lista de clínicas (admin) debe ver active_conversations > 0
        # Para llegar a /api/auth/clinics necesitamos login admin.
        login = client.post(
            "/api/auth/login",
            json={"email": "admin@dental.softlogic.ee", "password": "test-admin-password"},
        )
        assert login.status_code == 200
        token = login.json()["token"]
        r = client.get("/api/auth/clinics", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        clinics = r.json()["clinics"]
        total_active = sum(c["active_conversations"] for c in clinics)
        assert total_active > 0
