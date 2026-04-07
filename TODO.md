Hola, te paso el contexto completo del proyecto para que lo termines.

═══════════════════════════════════════════
PROYECTO: AGENTE DE WHATSAPP PARA DENTISTAS
═══════════════════════════════════════════

Es un agente de IA que gestiona citas, recordatorios y recepción 24/7
para clínicas dentales via WhatsApp. Stack: LangGraph + Claude + FastAPI.

El ZIP que te paso contiene todo el código base ya funcionando con 51 tests passing.

─────────────────────────────────────────
ESTRUCTURA DEL PROYECTO
─────────────────────────────────────────

dental/
├── core/
│   ├── models.py       — tipos Pydantic (Appointment, Patient, Clinic...)
│   ├── database.py     — MemoryDB (in-memory, hay que reemplazar por PostgreSQL)
│   ├── tools.py        — 7 tools del agente (citas, confirmación, cancelación...)
│   ├── agent.py        — grafo LangGraph + system prompt + process_message()
│   └── scheduler.py    — recordatorios 48h/2h y reporte semanal
├── api/
│   └── webhook.py      — servidor FastAPI (recibe mensajes de WhatsApp)
├── tests/              — 51 tests passing (unitarios + webhook + scheduler)
├── schema.sql          — PostgreSQL listo para producción
├── Dockerfile
├── .env.example
└── requirements.txt

─────────────────────────────────────────
LO QUE ESTÁ HECHO ✓
─────────────────────────────────────────

- Modelos Pydantic con validación estricta
- Base de datos in-memory con seed data de demo
- 7 tools del agente con manejo de errores completo
- Grafo LangGraph (agent ↔ tools), memoria por thread_id = clinic_id + phone
- Webhook FastAPI multi-tenant con verificación de firma HMAC
- Scheduler: recordatorios 48h, 2h, reporte semanal (lunes 8am)
- 51 tests passing
- Schema PostgreSQL con tablas, índices y triggers
- Dockerfile para Railway/Render

─────────────────────────────────────────
LO QUE FALTA — EN ORDEN DE PRIORIDAD
─────────────────────────────────────────

══ BLOQUEA EL PILOTO (~5h) ══════════════

1. ENVÍO REAL DE WHATSAPP (360dialog API)

   Archivo: dental/core/scheduler.py
   La función send_whatsapp() tiene el código listo pero comentado.
   También hay que llamarla desde dental/api/webhook.py para
   responder al paciente tras procesar el mensaje.

   Lo que hay que hacer:
   - Completar send_whatsapp() en scheduler.py con la API de 360dialog
   - Crear un cliente 360dialog reutilizable (dental/core/whatsapp_client.py)
   - Llamarlo desde webhook.py después de process_message()
   - Añadir tests con mock de la API

   API de 360dialog:
   POST https://waba.360dialog.io/v1/messages
   Headers: { "D360-API-KEY": API_KEY, "Content-Type": "application/json" }
   Body: { "messaging_product": "whatsapp", "to": "+34612345678",
           "type": "text", "text": { "body": "mensaje" } }

   Variables de entorno necesarias:
   DIALOG360_API_KEY=...


2. BASE DE DATOS POSTGRESQL REAL (sustituir MemoryDB)

   Archivo: dental/core/database.py
   Ahora usa MemoryDB (in-memory) — se borra al reiniciar el servidor.
   Hay que crear PostgresDB con la misma interfaz que MemoryDB.

   La interfaz que debe implementar PostgresDB:
   - get_clinic(clinic_id) → ClinicInfo | None
   - get_patient(clinic_id, phone) → Patient | None
   - upsert_patient(patient) → Patient
   - get_patient_appointments(clinic_id, phone, only_upcoming) → list[Appointment]
   - get_available_slots(clinic_id, date) → list[TimeSlot]
   - get_appointment(appointment_id) → Appointment | None
   - save_appointment(apt) → Appointment
   - confirm_appointment(appointment_id) → Appointment | None
   - cancel_appointment(appointment_id, reason) → Appointment | None
   - create_appointment(clinic_id, patient_phone, patient_name, slot_id, treatment) → Appointment
   - get_appointments_needing_reminder(clinic_id, reminder_type) → list[Appointment]

   El schema SQL ya está en dental/schema.sql.
   Usar asyncpg para las queries.
   Supabase free tier es suficiente para el piloto.

   Cambio en get_db(): si hay DATABASE_URL en el entorno,
   devolver PostgresDB; si no, devolver MemoryDB.

   Variable de entorno necesaria:
   DATABASE_URL=postgresql://user:pass@host:5432/dental_agent


══ SEMANA 1 ══════════════════════════════

3. COLA CELERY + REDIS (desacoplar webhook)

   Ahora el webhook procesa el mensaje síncronamente.
   Si el agente tarda más de 5s, WhatsApp marca el webhook como fallido y reintenta.

   Lo que hay que hacer:
   - Crear dental/core/worker.py con Celery
   - El webhook encola la tarea en Redis y responde HTTP 200 inmediatamente
   - El worker Celery procesa el mensaje y llama a send_whatsapp() con la respuesta
   - Arrancar con: celery -A dental.core.worker worker --loglevel=info

   Variable de entorno necesaria:
   REDIS_URL=redis://localhost:6379


4. DASHBOARD DEL DENTISTA (Next.js)

   El dentista necesita ver qué está pasando y poder tomar control
   de cualquier conversación manualmente. Sin esto no confía en el sistema.

   Lo que hay que construir (carpeta: dashboard/):
   - Una sola página con 3 secciones:
     a) Métricas del día: citas totales, confirmadas, pendientes, no-shows
     b) Lista de conversaciones activas con el último mensaje
     c) Botón "Tomar control" en cada conversación (pone flag en DB
        y el agente deja de responder a ese thread)
   - Stack: Next.js 14 + shadcn/ui + Tailwind
   - API: conecta al endpoint GET /api/conversations/{clinic_id}
     que hay que añadir a webhook.py
   - Actualización en tiempo real con polling cada 10s


5. DEPLOY EN RAILWAY

   - Crear railway.toml en la raíz del proyecto
   - El Dockerfile ya está listo
   - Variables de entorno a configurar en Railway:
     ANTHROPIC_API_KEY, DIALOG360_API_KEY, DATABASE_URL,
     REDIS_URL, WHATSAPP_WEBHOOK_SECRET, VERIFY_SIGNATURES=true
   - Dominio: configurar en 360dialog como
     https://tu-app.railway.app/webhook/clinic_001


══ MES 1 ══════════════════════════════════

6. INTEGRACIÓN DOCTORALIA O GOOGLE CALENDAR

   Ahora get_available_slots() devuelve slots simulados.
   Hay que conectar a la agenda real.

   Opción A — Google Calendar (más universal):
   - Usar google-auth + googleapiclient
   - Leer eventos del calendario de la clínica para saber qué está ocupado
   - Los huecos libres = slots base de la clínica - eventos existentes
   - OAuth2 para que cada clínica conecte su propio calendario

   Opción B — Doctoralia API:
   - GET /api/v1/facilities/{id}/available_slots
   - Requiere acuerdo comercial con Doctoralia


7. SISTEMA DE ONBOARDING DE CLÍNICAS

   Formulario web donde el dentista se registra y queda operativo en 10 min.
   Sin esto hay que onboardear cada cliente manualmente.

   Lo que hay que construir:
   - Página de registro: nombre clínica, dirección, horarios, servicios, precios
   - Conectar su número de WhatsApp Business (via 360dialog)
   - Generar webhook_secret único para esa clínica
   - Insertar en tabla clinics en PostgreSQL
   - Enviar email de bienvenida con instrucciones


══ MES 2-3 ════════════════════════════════

8. SEGUIMIENTO DE PRESUPUESTOS

   Nuevo job en scheduler.py que:
   - Cada día busca presupuestos con status='pending' y followup_count < 3
   - Manda follow-up personalizado a los 3, 7 y 14 días
   - Incrementa followup_count, actualiza last_followup
   - Si no responde tras 3 intentos → marca como expired

   Nueva tool para el agente: create_quote(patient_phone, clinic_id, treatment, amount)


9. REACTIVACIÓN DE PACIENTES DORMIDOS

   Job semanal (domingos 10:00) que:
   - Busca pacientes con last_visit < now() - 12 months
   - Manda mensaje personalizado: "Hola {nombre}, hace un año que
     no pasas por revisión. ¿Te apetece que te llamemos para ponerte al día?"
   - Registra en tabla conversations


10. BILLING CON STRIPE

    - Crear tabla subscriptions en PostgreSQL
    - Suscripción mensual por clínica: €99 starter / €249 pro / €399 complete
    - Stripe Billing + webhook de eventos (payment_succeeded, payment_failed)
    - Si payment_failed → desactivar clínica (active=false en DB)
    - Portal de cliente de Stripe para que el dentista gestione su suscripción


─────────────────────────────────────────
ARRANQUE RÁPIDO
─────────────────────────────────────────

pip install -r requirements.txt
cp .env.example .env        # añadir las API keys
python -m pytest tests/ -v  # verificar 51 tests passing
uvicorn dental.api.webhook:app --reload  # arrancar servidor

Para tests de integración con Claude real:
ANTHROPIC_API_KEY=sk-ant-... python -m pytest tests/ -v -s

─────────────────────────────────────────
VARIABLES DE ENTORNO NECESARIAS
─────────────────────────────────────────

ANTHROPIC_API_KEY=sk-ant-...          # Claude (IA del agente)
DIALOG360_API_KEY=...                 # WhatsApp Business API
WHATSAPP_WEBHOOK_SECRET=...           # firma webhooks (generar aleatorio)
DATABASE_URL=postgresql://...         # Supabase o PostgreSQL propio
REDIS_URL=redis://...                 # Redis (cola Celery + memoria)
VERIFY_SIGNATURES=false               # true en producción
ENVIRONMENT=development               # development | production

─────────────────────────────────────────
MODELO DE NEGOCIO (contexto)
─────────────────────────────────────────

Producto: agente de WhatsApp para clínicas dentales españolas/latam
Precio: €99/mes (starter) → €249/mes (pro) → €399/mes (completo)
Mercado: ~12.000 clínicas dentales en España
Objetivo: 100 clínicas en 6 meses = ~€20.000 MRR

El agente gestiona: confirmación de citas, recordatorios automáticos,
recepción 24/7, seguimiento de presupuestos, reactivación de pacientes,
reporte semanal para el dentista.

─────────────────────────────────────────
PRIORIDAD RECOMENDADA
─────────────────────────────────────────

Esta semana → tareas 1 + 2 + 5 (piloto funcionando en producción)
Semana 2    → tareas 3 + 4 (estabilidad + confianza del dentista)
Mes 1       → tareas 6 + 7 (producto escalable)
Mes 2-3     → tareas 8 + 9 + 10 (negocio completo)
