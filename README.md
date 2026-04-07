# Dental WhatsApp Agent

Agente de IA para clínicas dentales que gestiona citas, recordatorios y recepción 24/7 vía WhatsApp.

## Stack

- **Backend**: FastAPI + LangGraph + Claude (Anthropic)
- **Database**: PostgreSQL (o MemoryDB en desarrollo)
- **Queue**: Celery + Redis
- **WhatsApp**: 360dialog API
- **Dashboard**: Next.js 14 + Tailwind CSS

## Quick Start

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus API keys

# 3. Ejecutar tests
pytest tests/ -v

# 4. Arrancar servidor
uvicorn dental.api.webhook:app --reload

# 5. (Opcional) Arrancar Celery worker
celery -A dental.core.worker worker --loglevel=info
```

## Estructura

```
dental-whatsapp-agent/
├── core/
│   ├── models.py          # Tipos Pydantic
│   ├── database.py        # MemoryDB / PostgresDB
│   ├── agent.py           # LangGraph + Claude
│   ├── tools.py           # 7 tools del agente
│   ├── scheduler.py       # Recordatorios automáticos
│   ├── worker.py          # Celery tasks
│   └── whatsapp_client.py # Cliente 360dialog
├── api/
│   └── webhook.py         # FastAPI endpoints
├── dashboard/             # Next.js dashboard
├── tests/                 # 51+ tests
├── schema.sql             # PostgreSQL schema
├── Dockerfile
├── railway.toml
└── requirements.txt
```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/webhook/{clinic_id}` | Verificación 360dialog |
| POST | `/webhook/{clinic_id}` | Mensajes entrantes |
| GET | `/api/stats/{clinic_id}` | Métricas del día |
| GET | `/api/conversations/{clinic_id}` | Lista conversaciones |
| POST | `/api/conversations/{clinic_id}/{phone}/takeover` | Control manual |
| POST | `/api/conversations/{clinic_id}/{phone}/release` | Devolver al agente |

## Variables de Entorno

```env
# AI
ANTHROPIC_API_KEY=sk-ant-...

# WhatsApp
DIALOG360_API_KEY=...

# Database (opcional - usa MemoryDB si no está)
DATABASE_URL=postgresql://...

# Redis (para Celery)
REDIS_URL=redis://localhost:6379/0

# Modo async
ASYNC_MODE=false

# Security
WHATSAPP_WEBHOOK_SECRET=...
VERIFY_SIGNATURES=false
```

## Deploy en Railway

1. Conectar repo a Railway
2. Configurar variables de entorno
3. Deploy automático

El archivo `railway.toml` ya está configurado.

## Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Configurar en `.env`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_CLINIC_ID=clinic_001
```

## Roadmap

- [x] Core agent con 7 tools
- [x] WhatsApp client (360dialog)
- [x] PostgreSQL database
- [x] Celery + Redis
- [x] Dashboard Next.js
- [x] Railway deployment config
- [ ] Google Calendar integration
- [ ] Stripe billing
- [ ] Onboarding flow

## License

MIT
