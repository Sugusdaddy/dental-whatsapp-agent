# Agente Dental — WhatsApp AI para Clínicas

Agente de WhatsApp que gestiona citas, recordatorios y recepción 24/7 para clínicas dentales.
Construido con LangGraph + Claude + FastAPI.

## Estructura del proyecto

```
dental/
├── core/
│   ├── models.py       — tipos Pydantic (Appointment, Patient, Clinic...)
│   ├── database.py     — capa de datos (MemoryDB para MVP, reemplazable por PostgreSQL)
│   ├── tools.py        — 7 tools del agente (check_slots, book, confirm, cancel...)
│   ├── agent.py        — grafo LangGraph, system prompt, process_message()
│   └── scheduler.py    — recordatorios 48h/2h y reporte semanal
├── api/
│   └── webhook.py      — servidor FastAPI (recibe mensajes de WhatsApp)
├── tests/
│   ├── test_agent.py   — 30 tests unitarios + 9 integración + 3 e2e
│   ├── test_webhook.py — 8 tests del webhook
│   └── test_scheduler.py — 13 tests del scheduler
├── schema.sql          — PostgreSQL (tablas, índices, triggers)
├── .env.example        — variables de entorno
└── README.md
```

## Arranque en 5 minutos

### 1. Instalar dependencias
```bash
pip install langgraph langchain-anthropic langchain-core fastapi uvicorn \
            apscheduler httpx pydantic python-dotenv pytest
```

### 2. Configurar variables de entorno
```bash
cp .env.example .env
# Edita .env — mínimo necesario para arrancar:
#   ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Ejecutar tests (sin API key — 51 tests unitarios)
```bash
python -m pytest tests/ -v
```

### 4. Arrancar el servidor
```bash
uvicorn dental.api.webhook:app --reload --port 8000
```

### 5. Probar localmente con un mensaje de prueba
```bash
curl -X POST http://localhost:8000/webhook/clinic_001 \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{"from": "+34612345678", "id": "test1", "type": "text", "text": {"body": "Hola, quiero pedir cita"}}],
          "contacts": [{"wa_id": "+34612345678", "profile": {"name": "Test User"}}]
        }
      }]
    }]
  }'
```

### 6. Exponer al exterior para conectar 360dialog
```bash
ngrok http 8000
# En 360dialog dashboard: configura el webhook a
# https://tu-subdominio.ngrok.io/webhook/clinic_001
```

## Ejecutar tests

```bash
# Solo unitarios (sin API key, rápidos)
python -m pytest tests/test_agent.py::TestModels tests/test_agent.py::TestDatabase tests/test_agent.py::TestTools -v

# Webhook
python -m pytest tests/test_webhook.py -v

# Scheduler
python -m pytest tests/test_scheduler.py -v

# TODOS (unitarios + webhook + scheduler)
python -m pytest tests/ -v

# Con integración Claude real (requiere ANTHROPIC_API_KEY)
ANTHROPIC_API_KEY=sk-ant-... python -m pytest tests/ -v -s
```

## Resultados de tests actuales

```
✓ 30 tests unitarios    (models, database, tools)
✓  8 tests webhook      (health, verificación, parsing)
✓ 13 tests scheduler    (mensajes, ventanas, jobs)
── 51 tests PASSED ─────────────────────────────
+  9 tests integración  (requieren ANTHROPIC_API_KEY)
+  3 tests e2e          (requieren ANTHROPIC_API_KEY)
```

## Cómo añadir una clínica nueva

1. Inserta en PostgreSQL:
```sql
INSERT INTO clinics (id, name, address, phone, whatsapp_number, webhook_secret)
VALUES ('clinic_002', 'Dental Madrid Norte', 'Calle X', '+34...', '+34...', 'secret2');
```

2. En `database.py` → `MemoryDB._seed()` añade la clínica (o conecta a PostgreSQL).

3. Configura el webhook en 360dialog apuntando a `/webhook/clinic_002`.

El agente es multi-tenant desde el día 1 — `clinic_id` separa todos los datos.

## Arquitectura del agente

```
WhatsApp → Webhook (FastAPI) → process_message()
                                      ↓
                              LangGraph (ReAct loop)
                              ┌─────────────────────┐
                              │  agent_node (Claude) │
                              │        ↕             │
                              │   ToolNode (7 tools) │
                              └─────────────────────┘
                                      ↓
                              Respuesta → WhatsApp

Memoria: MemorySaver por thread_id = clinic_id + phone
         (cada paciente de cada clínica = conversación independiente)
```

## Tools disponibles

| Tool | Cuándo se usa |
|------|--------------|
| `get_clinic_info` | Preguntas sobre horarios, precios, seguros |
| `get_patient_appointments` | Ver citas existentes del paciente |
| `check_available_slots` | Buscar huecos libres para agendar |
| `confirm_appointment` | Registrar confirmación de asistencia |
| `cancel_appointment` | Cancelar una cita (siempre confirma antes) |
| `book_appointment` | Crear nueva cita |
| `escalate_to_human` | Urgencias, enfados, preguntas médicas |

## Próximos pasos (fase 2)

- [ ] Conectar `database.py` a PostgreSQL real (sustituir `MemoryDB` por `PostgresDB`)
- [ ] Integrar 360dialog API para envío real de mensajes en `scheduler.py`
- [ ] Conectar Doctoralia API en `get_available_slots` y `book_appointment`
- [ ] Mover procesamiento del webhook a Celery (cola Redis)
- [ ] Dashboard Next.js para que el dentista vea conversaciones en tiempo real
- [ ] Seguimiento automático de presupuestos (fase 3)
- [ ] Reactivación de pacientes dormidos (fase 4)
