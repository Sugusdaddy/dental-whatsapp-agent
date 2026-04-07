"""
Configuración global de tests.

Una fixture autouse garantiza que cada test:

1. NUNCA toque una Postgres real, aunque DATABASE_URL esté definido en
   el entorno de CI o en tu .env local. Sin esto, ejecutar `pytest` con
   un DATABASE_URL puesto haría que los tests intenten conectar a tu DB
   de producción.

2. Empiece con un singleton _db limpio. El factory `get_db()` cachea la
   instancia de MemoryDB, así que sin reset un test podría heredar el
   estado mutado por el anterior (citas creadas, takeovers activados…).

3. Tenga `JWT_SECRET` y `ADMIN_PASSWORD` predecibles, para no depender
   del entorno donde se ejecuten los tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    # 1. Aislar Postgres: garantizamos MemoryDB en TODOS los tests.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # 2. Auth determinista — evita warnings y "JWT_SECRET aleatorio"
    #    cambiando entre runs.
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET", "test-secret-do-not-use-in-prod")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-password")

    # 3. Reset del singleton de DB y de Auth (si se han cargado en otro test).
    import dental.core.database as database_mod
    database_mod._db = None

    try:
        import dental.core.auth as auth_mod
        auth_mod._user_repo = None
    except ImportError:
        pass

    yield

    # Limpieza post-test
    database_mod._db = None
    try:
        import dental.core.auth as auth_mod
        auth_mod._user_repo = None
    except ImportError:
        pass
