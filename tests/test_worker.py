"""
Tests para Celery Worker
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestCeleryTasks:
    """Tests para las tareas de Celery"""

    def test_celery_app_configuration(self):
        """Verifica configuración de Celery"""
        from dental.core.worker import celery_app
        
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.timezone == "Europe/Madrid"
        assert celery_app.conf.enable_utc is True

    def test_health_check_task(self):
        """Health check task funciona"""
        from dental.core.worker import health_check
        
        result = health_check()
        assert result["status"] == "ok"
        assert result["worker"] == "dental"

    @patch("dental.core.worker.process_message")
    @patch("dental.core.worker.get_db")
    @patch("dental.core.worker.send_whatsapp")
    def test_process_whatsapp_message_success(
        self, mock_send, mock_get_db, mock_process
    ):
        """Procesa mensaje y envía respuesta"""
        from dental.core.worker import process_whatsapp_message
        
        # Setup mocks
        mock_clinic = MagicMock()
        mock_clinic.phone = "+34911234567"
        mock_db = MagicMock()
        mock_db.get_clinic.return_value = mock_clinic
        mock_get_db.return_value = mock_db
        
        mock_process.return_value = "Hola, ¿en qué puedo ayudarte?"
        
        # Mock async send_whatsapp
        async def mock_send_async(*args, **kwargs):
            return True
        mock_send.side_effect = mock_send_async
        
        # Execute
        result = process_whatsapp_message(
            clinic_id="clinic_001",
            patient_phone="+34612345678",
            message_text="Quiero pedir cita",
            patient_name="María",
        )
        
        assert result["status"] == "processed"
        assert "Hola" in result["response"]
        mock_process.assert_called_once()

    @patch("dental.core.worker.get_db")
    def test_process_whatsapp_message_clinic_not_found(self, mock_get_db):
        """Error si clínica no existe"""
        from dental.core.worker import process_whatsapp_message
        
        mock_db = MagicMock()
        mock_db.get_clinic.return_value = None
        mock_get_db.return_value = mock_db
        
        result = process_whatsapp_message(
            clinic_id="invalid_clinic",
            patient_phone="+34612345678",
            message_text="Hola",
        )
        
        assert result["status"] == "error"
        assert result["error"] == "clinic_not_found"

    @patch("dental.core.worker.get_db")
    @patch("dental.core.worker.send_whatsapp")
    def test_send_scheduled_reminder_48h(self, mock_send, mock_get_db):
        """Envía recordatorio 48h"""
        from dental.core.worker import send_scheduled_reminder
        from dental.core.models import Appointment, AppointmentStatus
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        MADRID_TZ = ZoneInfo("Europe/Madrid")
        
        # Setup mocks
        mock_apt = Appointment(
            appointment_id="apt_001",
            clinic_id="clinic_001",
            patient_phone="+34612345678",
            patient_name="María",
            appointment_datetime=datetime.now(MADRID_TZ),
            treatment="Limpieza",
            dentist="Dra. García",
            duration_min=30,
            status=AppointmentStatus.CONFIRMED,
        )
        
        mock_clinic = MagicMock()
        mock_clinic.name = "Clínica Test"
        mock_clinic.address = "Calle Test 1"
        
        mock_db = MagicMock()
        mock_db.get_appointment.return_value = mock_apt
        mock_db.get_clinic.return_value = mock_clinic
        mock_get_db.return_value = mock_db
        
        async def mock_send_async(*args, **kwargs):
            return True
        mock_send.side_effect = mock_send_async
        
        result = send_scheduled_reminder(
            clinic_id="clinic_001",
            appointment_id="apt_001",
            reminder_type="48h",
        )
        
        assert result["status"] == "sent"
        assert result["reminder_type"] == "48h"
        mock_db.save_appointment.assert_called_once()

    @patch("dental.core.worker.get_db")
    def test_send_scheduled_reminder_appointment_not_found(self, mock_get_db):
        """Error si cita no existe"""
        from dental.core.worker import send_scheduled_reminder
        
        mock_db = MagicMock()
        mock_db.get_appointment.return_value = None
        mock_get_db.return_value = mock_db
        
        result = send_scheduled_reminder(
            clinic_id="clinic_001",
            appointment_id="invalid",
            reminder_type="48h",
        )
        
        assert result["status"] == "error"
        assert result["error"] == "appointment_not_found"


class TestAsyncWebhook:
    """Tests para webhook en modo async"""

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"ASYNC_MODE": "true"})
    @patch("dental.api.webhook.get_db")
    @patch("dental.api.webhook.get_whatsapp_client")
    async def test_webhook_queues_message(self, mock_wa_client, mock_get_db):
        """En modo async, el webhook encola el mensaje"""
        from fastapi.testclient import TestClient
        
        # Este test requiere Redis corriendo
        # En CI, se puede mockear Celery
        pass  # TODO: implementar con mock de Celery
