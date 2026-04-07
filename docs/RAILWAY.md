# Deploy en Railway

Guía paso a paso para llevar el agente de WhatsApp a producción en
Railway. Asume que el código ya está en un repo GitHub.

## TL;DR

```
1. Crear proyecto en Railway
2. Añadir Postgres + Redis (templates)
3. Conectar repo → Railway despliega webhook + worker
4. Cargar schema.sql en Postgres
5. Configurar variables de entorno
6. Apuntar 360dialog al webhook
```

Tiempo estimado: **30 minutos** la primera vez.

---

## 1. Preparativos

Antes de tocar Railway, asegúrate de tener:

- Cuenta en [Railway](https://railway.app) (Hobby plan, $5/mes)
- Repo GitHub con este código
- Cuenta y API key de [Anthropic](https://console.anthropic.com)
- Cuenta y API key de [360dialog](https://hub.360dialog.com)
- Un email de admin y una contraseña segura (no la que usas en otros sitios)
- Un `JWT_SECRET` generado:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```

## 2. Crear proyecto Railway

1. **New Project → Deploy from GitHub repo** → selecciona tu repo
2. Railway detecta el `Dockerfile` y construye automáticamente
3. **Antes de que termine**, ve a *Settings → Networking* y genera un dominio:
   `https://tu-app.up.railway.app`

## 3. Añadir Postgres

1. En el mismo proyecto: **+ New → Database → Add PostgreSQL**
2. Railway provisiona una instancia y expone `DATABASE_URL` automáticamente
3. Conecta a la base de datos para cargar el schema:

   ```bash
   # Copia DATABASE_URL desde Railway → Postgres → Variables
   psql "$DATABASE_URL" -f schema.sql
   ```

   O desde Railway directamente:
   - Postgres service → **Data** tab → **Query** → pega el contenido de `schema.sql`

## 4. Añadir Redis

1. **+ New → Database → Add Redis**
2. Railway expone `REDIS_URL` automáticamente

## 5. Variables de entorno

En el servicio principal (el del Dockerfile), añade en **Variables**:

| Variable | Valor | Notas |
|---|---|---|
| `ENVIRONMENT` | `production` | **Crítico**: activa los guards de auth |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Tu key de Claude |
| `DIALOG360_API_KEY` | `…` | Tu key de 360dialog |
| `WHATSAPP_WEBHOOK_SECRET` | `…` (genera con `openssl rand -hex 32`) | Para HMAC |
| `VERIFY_SIGNATURES` | `true` | **Crítico** en producción |
| `JWT_SECRET` | (el que generaste arriba) | **Obligatorio** en `production` |
| `ADMIN_EMAIL` | `admin@tudominio.com` | |
| `ADMIN_PASSWORD` | `…` (contraseña fuerte) | **Obligatorio** en `production` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Reference variable |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Reference variable |
| `ASYNC_MODE` | `true` | Activa cola Celery |

> **Importante**: si `ENVIRONMENT=production` y falta `JWT_SECRET` o
> `ADMIN_PASSWORD`, el servidor abortará el arranque con un mensaje
> claro. Es a propósito — evita que un piloto quede expuesto con la
> contraseña por defecto.

## 6. Worker Celery (segundo servicio)

El webhook y el worker corren en procesos distintos. En Railway:

1. **+ New → Empty Service** dentro del mismo proyecto
2. **Settings → Source** → mismo repo de GitHub
3. **Settings → Deploy → Custom Start Command**:
   ```
   celery -A dental.core.worker worker --loglevel=info --concurrency=2
   ```
4. Copia las **mismas** variables de entorno del servicio webhook (Railway tiene "Shared Variables" si quieres centralizarlas)

## 7. Configurar 360dialog

En [hub.360dialog.com](https://hub.360dialog.com):

1. Tu canal de WhatsApp → **Webhook Configuration**
2. **URL**: `https://tu-app.up.railway.app/webhook/clinic_001`
3. **Verify Token**: el `WHATSAPP_WEBHOOK_SECRET` que definiste arriba
4. Suscribirte a los eventos: `messages`, `message_status`

## 8. Smoke test final

```bash
# 1. Health check
curl https://tu-app.up.railway.app/health
# → {"status":"ok","db":"ok","clinic_demo":"Clínica Dental Sonríe"}

# 2. Login admin
curl -X POST https://tu-app.up.railway.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@tudominio.com","password":"…"}'
# → {"token":"eyJ…","user":{...}}

# 3. Smoke test PostgresDB (desde tu máquina, no desde Railway)
DATABASE_URL="<copia de Railway>" python scripts/smoke_postgres.py
# → debería imprimir 24 ✓ verdes
```

## 9. Dashboard (Vercel)

El dashboard Next.js es estático — recomiendo Vercel:

1. **vercel.com → Import Project → tu repo**
2. **Root Directory**: `dashboard/`
3. **Environment Variable**: `NEXT_PUBLIC_API_URL=https://tu-app.up.railway.app`
4. Deploy

## Troubleshooting

**El servidor se reinicia en bucle**
→ Falta `JWT_SECRET` o `ADMIN_PASSWORD` en producción. Mira los logs:
   `JWT_SECRET es obligatorio en producción.`

**360dialog devuelve 401 al webhook**
→ `VERIFY_SIGNATURES=true` pero el `WHATSAPP_WEBHOOK_SECRET` no
   coincide con el verify token configurado en 360dialog.

**Mensajes llegan pero el agente no responde**
→ Comprueba que el worker Celery está corriendo (segundo servicio) y
   que `ASYNC_MODE=true`. Ver logs del worker.

**`active_conversations` siempre es 0**
→ Necesitas que entren mensajes reales por el webhook. El agente
   actualiza `last_contact` en cada mensaje recibido, y el dashboard
   cuenta pacientes con `last_contact` < 24h.

**El dashboard muestra "Network error" al hacer login**
→ CORS o `NEXT_PUBLIC_API_URL` mal configurado en Vercel. Verifica
   que apunta al dominio de Railway con `https://`.

## Coste estimado

- Railway Hobby: $5/mes (incluye servicio + Postgres + Redis hasta cierto uso)
- Vercel Hobby: $0/mes (dashboard estático)
- 360dialog: ~$5/mes + variable por mensaje
- Anthropic Claude: pay-per-use, ~$0.01-0.05 por conversación
- **Total piloto (1 clínica)**: ~$15-25/mes
