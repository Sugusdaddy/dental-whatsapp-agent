"""
Tests para los métodos nuevos de MemoryDB:
- update_clinic
- set_human_takeover / is_human_takeover
"""

import pytest


@pytest.fixture
def db():
    from dental.core.database import MemoryDB
    return MemoryDB()


class TestUpdateClinic:
    def test_update_clinic_changes_fields(self, db):
        updated = db.update_clinic("clinic_001", {"name": "Nueva Clínica"})
        assert updated is not None
        assert updated.name == "Nueva Clínica"
        assert db.get_clinic("clinic_001").name == "Nueva Clínica"

    def test_update_clinic_partial(self, db):
        original = db.get_clinic("clinic_001")
        original_address = original.address

        updated = db.update_clinic("clinic_001", {"phone": "+34999000000"})
        assert updated.phone == "+34999000000"
        assert updated.address == original_address  # no tocado

    def test_update_clinic_ignores_protected_fields(self, db):
        # clinic_id no debe poder cambiarse vía update
        updated = db.update_clinic("clinic_001", {"clinic_id": "hacked"})
        assert updated.clinic_id == "clinic_001"

    def test_update_clinic_returns_none_for_unknown(self, db):
        assert db.update_clinic("nope", {"name": "x"}) is None

    def test_update_clinic_drops_none_values(self, db):
        original_name = db.get_clinic("clinic_001").name
        # Si pasamos name=None, no debería sobrescribir
        updated = db.update_clinic("clinic_001", {"name": None, "phone": "+34111"})
        assert updated.name == original_name
        assert updated.phone == "+34111"


class TestHumanTakeover:
    def test_takeover_default_off(self, db):
        assert db.is_human_takeover("clinic_001", "+34612345678") is False

    def test_takeover_enable_disable(self, db):
        db.set_human_takeover("clinic_001", "+34612345678", True)
        assert db.is_human_takeover("clinic_001", "+34612345678") is True

        db.set_human_takeover("clinic_001", "+34612345678", False)
        assert db.is_human_takeover("clinic_001", "+34612345678") is False

    def test_takeover_isolated_per_phone(self, db):
        db.set_human_takeover("clinic_001", "+34611111111", True)
        assert db.is_human_takeover("clinic_001", "+34611111111") is True
        assert db.is_human_takeover("clinic_001", "+34622222222") is False

    def test_takeover_isolated_per_clinic(self, db):
        db.set_human_takeover("clinic_001", "+34612345678", True)
        assert db.is_human_takeover("clinic_002", "+34612345678") is False
