"""
Tests de PostgresDB sin Postgres real — mockeamos psycopg_pool.

Cubre:
- Inicialización (pool + creación de tabla human_takeovers)
- Las queries SQL correctas se generan con los parámetros correctos
- El parsing de filas de Postgres a modelos Pydantic funciona

Esto NO sustituye al smoke test contra una DB real (scripts/smoke_postgres.py)
pero sí garantiza que cualquier refactor accidental de las queries falle
en CI sin necesidad de levantar Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


MADRID = ZoneInfo("Europe/Madrid")


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

class FakeCursor:
    """
    Cursor falso. Cada test programa una secuencia de respuestas con
    `cursor.set_responses([...])` y el código bajo test las consume en orden
    a medida que llama a fetchall().
    """

    def __init__(self):
        self._responses: list[list[dict]] = []
        self.executed: list[tuple[str, tuple]] = []
        self.description = None  # se setea por respuesta

    def set_responses(self, responses):
        self._responses = list(responses)

    def execute(self, query, params=()):
        self.executed.append((query, params))
        if self._responses:
            self._next = self._responses.pop(0)
            self.description = [("col",)] if self._next else None
        else:
            self._next = []
            self.description = None

    def fetchall(self):
        return getattr(self, "_next", [])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakePool:
    """
    Sustituye a psycopg_pool.ConnectionPool. Comparte el mismo cursor falso
    en todas las conexiones para que el test pueda inspeccionarlo.
    """

    def __init__(self, *args, **kwargs):
        self.cursor = FakeCursor()

    def connection(self):
        return FakeConnection(self.cursor)


@pytest.fixture
def fake_pool():
    """Parchea psycopg_pool.ConnectionPool y devuelve la instancia falsa."""
    with patch("psycopg_pool.ConnectionPool", FakePool) as _:
        # Importamos AQUÍ, después del patch
        from dental.core.database import PostgresDB

        # Pre-cargamos respuesta vacía para _ensure_takeover_table (CREATE TABLE
        # no devuelve filas → description=None)
        db = PostgresDB("postgresql://fake/fake")
        # Reset del registro de queries que el __init__ produjo
        db._pool.cursor.executed.clear()
        yield db


# ─────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────

class TestInit:
    def test_init_creates_pool_and_takeover_table(self):
        with patch("psycopg_pool.ConnectionPool", FakePool):
            from dental.core.database import PostgresDB

            db = PostgresDB("postgresql://fake/fake", pool_min=3, pool_max=8)

            # Una de las queries del init debe ser el CREATE TABLE
            sqls = " ".join(q for q, _ in db._pool.cursor.executed)
            assert "human_takeovers" in sqls
            assert "CREATE TABLE IF NOT EXISTS" in sqls
            assert db._takeover_table_ready is True


# ─────────────────────────────────────────────
# Clinic
# ─────────────────────────────────────────────

class TestClinic:
    def test_get_clinic_parses_row_correctly(self, fake_pool):
        db = fake_pool
        # Respuesta 1: SELECT FROM clinics → 1 fila
        # Respuesta 2: SELECT FROM clinic_services → 2 filas
        db._pool.cursor.set_responses([
            [{
                "id": "clinic_001",
                "name": "Clínica Test",
                "address": "Calle Test 1",
                "phone": "+34911111111",
                "whatsapp_number": "+34611111111",
                "hours_lv": "09:00-20:00",
                "hours_sat": "10:00-14:00",
                "insurance": ["Adeslas", "Sanitas"],
                "parking": "Sí",
            }],
            [
                {"name": "Limpieza", "price_from": 60},
                {"name": "Implante", "price_from": 900},
            ],
        ])

        clinic = db.get_clinic("clinic_001")
        assert clinic is not None
        assert clinic.clinic_id == "clinic_001"
        assert clinic.name == "Clínica Test"
        assert clinic.hours.monday_friday == "09:00-20:00"
        assert clinic.hours.saturday == "10:00-14:00"
        assert len(clinic.services) == 2
        assert clinic.services[0].name == "Limpieza"
        assert "Adeslas" in clinic.insurance_accepted

        # Verifica que la query usa la PK correcta del schema (id, no clinic_id)
        first_sql = db._pool.cursor.executed[0][0]
        assert "WHERE id = %s" in first_sql

    def test_get_clinic_returns_none_when_not_found(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[]])  # SELECT no devuelve filas
        assert db.get_clinic("nope") is None

    def test_update_clinic_only_whitelisted_fields(self, fake_pool):
        db = fake_pool
        # Respuestas: el UPDATE no devuelve nada, después get_clinic devuelve fila + servicios vacíos
        db._pool.cursor.set_responses([
            [],  # UPDATE
            [{
                "id": "clinic_001", "name": "Nuevo", "address": "addr",
                "phone": "+34911", "whatsapp_number": "+34611",
                "hours_lv": "09:00-20:00", "hours_sat": None,
                "insurance": [], "parking": "",
            }],
            [],  # services
        ])

        db.update_clinic("clinic_001", {
            "name": "Nuevo",
            "phone": "+34911",
            "evil_field": "DROP TABLE",
            "clinic_id": "hacked",
        })

        update_sql = db._pool.cursor.executed[0][0]
        update_params = db._pool.cursor.executed[0][1]
        # Solo name + phone deben aparecer
        assert "name = %s" in update_sql
        assert "phone = %s" in update_sql
        assert "evil_field" not in update_sql
        assert "clinic_id" not in update_sql
        # Los params son: (name, phone, clinic_id_pk)
        assert "clinic_001" in update_params

    def test_update_clinic_with_no_editable_fields_skips_update(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([
            [{
                "id": "clinic_001", "name": "x", "address": "x", "phone": "x",
                "whatsapp_number": "x", "hours_lv": "09:00-20:00",
                "hours_sat": None, "insurance": [], "parking": "",
            }],
            [],  # services
        ])
        db.update_clinic("clinic_001", {"evil": "y"})
        # No debe haber UPDATE — solo el SELECT del get_clinic posterior
        assert not any("UPDATE" in q for q, _ in db._pool.cursor.executed)


# ─────────────────────────────────────────────
# Patient
# ─────────────────────────────────────────────

class TestPatient:
    def test_get_patient_parses_row(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[{
            "id": 42,
            "clinic_id": "clinic_001",
            "phone": "+34612345678",
            "name": "María",
            "email": "maria@test.com",
        }]])

        p = db.get_patient("clinic_001", "+34612345678")
        assert p is not None
        assert p.patient_id == 42
        assert p.name == "María"
        assert p.phone == "+34612345678"

    def test_get_patient_not_found(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[]])
        assert db.get_patient("clinic_001", "+34600000000") is None

    def test_upsert_patient_uses_on_conflict(self, fake_pool):
        from dental.core.models import Patient

        db = fake_pool
        db._pool.cursor.set_responses([[{
            "id": 99, "clinic_id": "clinic_001", "phone": "+34699999999",
            "name": "Test", "email": None,
        }]])

        p = Patient(
            patient_id=0, clinic_id="clinic_001",
            phone="+34699999999", name="Test",
        )
        result = db.upsert_patient(p)

        sql = db._pool.cursor.executed[0][0]
        assert "ON CONFLICT" in sql
        assert "INSERT INTO patients" in sql
        assert result.patient_id == 99


# ─────────────────────────────────────────────
# Appointment
# ─────────────────────────────────────────────

class TestAppointment:
    def test_save_appointment_uses_upsert(self, fake_pool):
        from dental.core.models import Appointment, AppointmentStatus

        db = fake_pool
        db._pool.cursor.set_responses([[]])

        apt = Appointment(
            appointment_id="apt_test",
            clinic_id="clinic_001",
            patient_phone="+34612345678",
            patient_name="Test",
            appointment_datetime=datetime.now(MADRID) + timedelta(days=1),
            treatment="Test",
            dentist="Dr. Test",
            duration_min=30,
            status=AppointmentStatus.CONFIRMED,
        )
        db.save_appointment(apt)

        sql = db._pool.cursor.executed[0][0]
        assert "INSERT INTO appointments" in sql
        assert "ON CONFLICT" in sql

    def test_confirm_appointment_runs_update(self, fake_pool):
        db = fake_pool
        # 1ª resp: UPDATE; 2ª resp: SELECT del get_appointment posterior
        db._pool.cursor.set_responses([
            [],
            [{
                "appointment_id": "apt_001", "clinic_id": "clinic_001",
                "patient_phone": "+34612", "patient_name": "X",
                "appointment_datetime": datetime.now(MADRID),
                "treatment": "Limpieza", "dentist": "Dr",
                "duration_min": 30, "status": "confirmed",
                "confirmation_received": True,
                "reminder_48h_sent": True, "reminder_2h_sent": False,
            }],
        ])

        result = db.confirm_appointment("apt_001")
        assert result is not None
        assert result.confirmation_received is True

        update_sql = db._pool.cursor.executed[0][0]
        assert "UPDATE appointments" in update_sql
        assert "confirmation_received = true" in update_sql

    def test_cancel_appointment_sets_cancelled_status(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([
            [],
            [{
                "appointment_id": "apt_001", "clinic_id": "clinic_001",
                "patient_phone": "+34612", "patient_name": "X",
                "appointment_datetime": datetime.now(MADRID),
                "treatment": "X", "dentist": "X",
                "duration_min": 30, "status": "cancelled",
                "confirmation_received": False,
                "reminder_48h_sent": False, "reminder_2h_sent": False,
            }],
        ])

        result = db.cancel_appointment("apt_001", "smoke")
        update_sql = db._pool.cursor.executed[0][0]
        assert "UPDATE appointments" in update_sql
        assert "status = 'cancelled'" in update_sql
        assert result.status.value == "cancelled"


# ─────────────────────────────────────────────
# Human takeover
# ─────────────────────────────────────────────

class TestHumanTakeover:
    def test_set_enable_inserts_with_on_conflict(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[]])

        db.set_human_takeover("clinic_001", "+34612345678", True)

        sql = db._pool.cursor.executed[0][0]
        assert "INSERT INTO human_takeovers" in sql
        assert "ON CONFLICT" in sql
        assert db._pool.cursor.executed[0][1] == ("clinic_001", "+34612345678")

    def test_set_disable_deletes(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[]])

        db.set_human_takeover("clinic_001", "+34612345678", False)

        sql = db._pool.cursor.executed[0][0]
        assert "DELETE FROM human_takeovers" in sql

    def test_is_human_takeover_true(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[{"enabled": True}]])
        assert db.is_human_takeover("clinic_001", "+34612345678") is True

    def test_is_human_takeover_false_when_no_row(self, fake_pool):
        db = fake_pool
        db._pool.cursor.set_responses([[]])
        assert db.is_human_takeover("clinic_001", "+34612345678") is False
