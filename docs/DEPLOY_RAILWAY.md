# Deploy en Railway

Guía paso a paso para llevar el agente dental a producción usando
**Railway** (backend FastAPI + Celery worker + Postgres + Redis) y
**Vercel** (dashboard Next.js).

Tiempo estimado: **45–60 min** la primera vez.

---

## Resumen de la arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│  WhatsApp Business (360dialog)                               │
│              │                                                │
│              │ POST /webhook/{clinic_id}                      │
│              ▼                                                │
│  ┌────────────────────────┐    ┌────────────────────────┐   │
│  │ Railway: API           │───▶│ Railway: Redis         │   │
│  │ (FastAPI + uvicorn)    │    │ (cola Celery)          │   │
│  └────────────────────────┘    └────────────────────────┘   │
│              │                              │                │
│              │                              ▼                │
│              │                  ┌────────────────────────┐   │
│              │                  │ Railway: Worker        │   │
│              │                  │ (Celery + LangGraph)   │   │
│              │                  └────────────────────────┘   │
│              │                              │                │
│              ▼                              ▼                │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Railway: PostgreSQL                                  │    │
│  │ (clínicas, citas, takeovers, conversaciones)         │    │
│  └──────────────────────────────────────────────────────┘    │
│              ▲                                                │
│              │ HTTPS                                          │
│  ┌────────────────────────┐                                  │
│  │ Vercel: Dashboard      │                                  │
│  │ (Next.js)              │                                  │
│  └────────────────────────┘                                  │
└──────────────────────────────────────────────────────────────┘
```

---

## Antes de empezar

Necesitas:

- Cuenta en [Railway](https://railway.app)
- Cuenta en [Vercel](https://vercel.com) (gratis)
- API key de [Anthropic](https://console.anthropic.com)
- Cuenta en [360dialog](https://hub.360dialog.com) con un número de WhatsApp Business aprobado
- Repositorio del proyecto en GitHub (Railway hace deploy desde Git)

---

## 1. Generar secrets

Antes de tocar Railway, genera los secrets que vas a necesitar.
**Guárdalos en un gestor de contraseñas** — los vas a pegar varias veces.

```bash
# JWT_SECRET — firma los tokens del dashboard
python -c "import secrets; print(secrets.token_hex(32))"

# WHATSAPP_WEBHOOK_SECRET — firma HMAC del webhook
python -c "import secrets; print(secrets.token_hex(32))"

# ADMIN_PASSWORD — primera contraseña del admin del panel
python -c "import secrets; print(secrets.token_urlsafe(20))"
```

---

## 2. Crear el proyecto en Railway

1. Ve a [railway.app/new](https://railway.app/new) → **Deploy from GitHub repo**
2. Conecta tu repo del proyecto
3. Railway detecta el `Dockerfile` automáticamente
4. **No despliegues todavía** — primero añade los servicios y variables.

### 2.1 Añadir Postgres

En el dashboard del proyecto:

1. **+ New** → **Database** → **Add PostgreSQL**
2. Espera a que aparezca la instancia
3. Click en el servicio Postgres → **Variables** → copia `DATABASE_URL`

### 2.2 Cargar el schema

Hay dos formas:

**Opción A — desde tu máquina (recomendada):**

```bash
# Reemplaza con la DATABASE_URL que copiaste
psql "postgresql://postgres:XXX@viaduct.proxy.rlwy.net:NNNN/railway" \
     -f schema.sql
```

**Opción B — desde Railway CLI:**

```bash
npm i -g @railway/cli
railway login
railway link  # selecciona tu proyecto
railway connect Postgres  # abre psql interactivo
\i schema.sql
\q
```

### 2.3 Añadir Redis

1. **+ New** → **Database** → **Add Redis**
2. Click en el servicio Redis → **Variables** → copia `REDIS_URL`

### 2.4 Variables del servicio API

Click en el servicio principal (el de tu repo) → **Variables** → añade:

| Variable | Valor | Notas |
|---|---|---|
| `ENVIRONMENT` | `production` | **Activa los guards de seguridad** |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Tu API key de Claude |
| `DIALOG360_API_KEY` | `…` | Desde [hub.360dialog.com](https://hub.360dialog.com) |
| `WHATSAPP_WEBHOOK_SECRET` | (el del paso 1) | Firma HMAC entrante |
| `JWT_SECRET` | (el del paso 1) | **Sin esto el arranque falla** |
| `ADMIN_EMAIL` | `tu-admin@email.com` | El email del primer admin |
| `ADMIN_PASSWORD` | (el del paso 1) | **Sin esto el arranque falla** |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Referencia al servicio |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Referencia al servicio |
| `VERIFY_SIGNATURES` | `true` | Verificar firmas HMAC |
| `ASYNC_MODE` | `true` | Encolar mensajes en Celery |

> **Importante:** las referencias `${{Postgres.DATABASE_URL}}` se autocompletan
> en Railway — empieza a teclear `${{` y aparecen los servicios.

### 2.5 Añadir el worker de Celery

1. **+ New** → **Empty Service**
2. Settings → **Source** → conecta el mismo repo
3. Settings → **Deploy** → **Custom Start Command**:
   ```
   celery -A dental.core.worker worker --loglevel=info --concurrency=2
   ```
4. **Variables** → copia las MISMAS variables del paso 2.4
   (puedes usar **Service Variables** → **Shared Variables** para no duplicar)

### 2.6 Generar dominio público para la API

1. Click en el servicio API → **Settings** → **Networking**
2. **Generate Domain** → copia la URL (ej: `https://dental-api-production.up.railway.app`)
3. Esta es la URL que apuntará 360dialog y consumirá el dashboard

---

## 3. Verificar que el backend arranca

```bash
curl https://TU-URL.up.railway.app/health
```

Respuesta esperada:

```json
{
  "status": "ok",
  "db": "ok",
  "clinic_demo": "Clínica Dental Sonríe",
  "timestamp": "2026-..."
}
```

Si responde **500** → revisa los logs en Railway. Causas más comunes:

- **`JWT_SECRET es obligatorio en producción`** → no configuraste el secret en variables
- **`ADMIN_PASSWORD es obligatorio en producción`** → idem
- **`could not connect to server`** → la `DATABASE_URL` no es válida o no se cargó el schema
- **`relation "clinics" does not exist`** → falta cargar `schema.sql` (paso 2.2)

---

## 4. Configurar el webhook en 360dialog

1. Entra a [hub.360dialog.com](https://hub.360dialog.com)
2. **Channels** → tu número → **Webhooks**
3. **URL**: `https://TU-URL.up.railway.app/webhook/clinic_001`
4. **Verify token**: el `WHATSAPP_WEBHOOK_SECRET` del paso 1
5. **Subscribed fields**: `messages`, `message_status`
6. Guardar y hacer **Test webhook**

---

## 5. Deploy del dashboard en Vercel

```bash
cd dashboard
npx vercel
```

En el wizard:

- **Set up and deploy?** → Y
- **Which scope?** → tu cuenta
- **Link to existing project?** → N
- **Project name?** → `dental-dashboard`
- **Directory?** → `./`
- **Override settings?** → N

Después del deploy, en el panel de Vercel del proyecto:

- **Settings** → **Environment Variables** → añade:
  - `NEXT_PUBLIC_API_URL` = `https://TU-URL.up.railway.app`
- **Deployments** → **Redeploy** (para que tome la variable)

---

## 6. Smoke test del flujo completo

### 6.1 Test de la base de datos (desde tu máquina)

```bash
DATABASE_URL="postgresql://..." python scripts/smoke_postgres.py
```

Debe imprimir todos los checks en verde. Si alguno falla, **NO sigas** —
arregla primero la conexión a Postgres.

### 6.2 Login en el dashboard

1. Abre la URL de Vercel del dashboard
2. Entra con `ADMIN_EMAIL` y `ADMIN_PASSWORD`
3. Verás el panel de admin con la clínica demo (`Clínica Dental Sonríe`)

### 6.3 Mensaje de prueba por WhatsApp

Desde tu propio WhatsApp, envía un mensaje al número de la clínica:

```
Hola, quiero pedir cita para una limpieza
```

En menos de 30 segundos deberías recibir respuesta del agente. En el
dashboard de Railway → logs del worker, verás algo como:

```
[clinic_001] Mensaje de +34XXX: Hola, quiero pedir cita...
[clinic_001] Respuesta enviada a +34XXX: Hola, claro...
```

### 6.4 Test del botón "Tomar control"

1. En el dashboard, ve a **Conversaciones**
2. Click en **Tomar control** sobre tu conversación
3. Envía otro mensaje desde WhatsApp
4. **NO debes recibir respuesta** del agente
5. En los logs del worker debe aparecer:
   ```
   [clinic_001] Takeover activo para +34XXX — agente silenciado
   ```
6. Click en **Devolver al bot** → el agente vuelve a responder

---

## ✅ Checklist final antes de pasar a un cliente real

Marca cada uno antes de cobrar:

- [ ] `/health` responde 200
- [ ] `scripts/smoke_postgres.py` pasa todos los checks contra la Postgres de producción
- [ ] Login en el dashboard funciona con `ADMIN_EMAIL` / `ADMIN_PASSWORD`
- [ ] Webhook de 360dialog configurado y verificado
- [ ] Mensaje de WhatsApp recibe respuesta del agente
- [ ] Logs del worker muestran que Celery está procesando
- [ ] Botón "Tomar control" silencia el agente correctamente
- [ ] Botón "Devolver al bot" reactiva al agente
- [ ] La clínica aparece en el panel admin con sus datos correctos
- [ ] Settings → guardar cambios → recargar → cambios persistidos
- [ ] La página de Citas muestra la cita demo
- [ ] El cron de recordatorios está corriendo (revisa logs cada 5 min)
- [ ] **`ENVIRONMENT=production`** confirmado en variables (no `development`)
- [ ] **`VERIFY_SIGNATURES=true`** confirmado
- [ ] La contraseña del admin **no es** `admin123456`
- [ ] El `JWT_SECRET` está guardado en el gestor de contraseñas
- [ ] El backup automático de Postgres está activado en Railway
- [ ] Has probado un reinicio del servicio API y todo sigue funcionando

---

## Troubleshooting

### El bot responde varias veces al mismo mensaje

WhatsApp reintenta cuando no recibe HTTP 200 en <5s. Verifica que
`ASYNC_MODE=true` esté puesto — sin esto el webhook procesa síncronamente
y puede pasarse del timeout cuando Claude tarda más de la cuenta.

### Las sesiones del dashboard se invalidan al reiniciar el servicio

`JWT_SECRET` no está configurado y se está generando uno aleatorio en
cada arranque. Configúralo como variable de entorno permanente.

### `relation "human_takeovers" does not exist`

La tabla se crea automáticamente al instanciar `PostgresDB`, pero puede
fallar si el usuario de la DB no tiene permisos `CREATE TABLE`. Créala
manualmente con `psql`:

```sql
CREATE TABLE IF NOT EXISTS human_takeovers (
    clinic_id      VARCHAR(50)  NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    patient_phone  VARCHAR(20)  NOT NULL,
    enabled        BOOLEAN      NOT NULL DEFAULT true,
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (clinic_id, patient_phone)
);
```

### El dashboard muestra "Error de conexión" en login

`NEXT_PUBLIC_API_URL` no está configurado en Vercel, o está apuntando a
`http://` en vez de `https://`. Recuerda hacer **redeploy** después de
cambiar variables — Vercel no las recarga en caliente.

### Los recordatorios 48h/2h no se envían

El scheduler de APScheduler corre en el proceso del worker de Celery.
Verifica:

1. El servicio worker está arriba (no solo el API)
2. Hay citas con `status=confirmed` en la ventana de la próxima 48h
3. Los logs del worker no muestran errores del scheduler

---

## Costes estimados

Para los primeros 10 clientes, tu factura mensual aproximada:

| Servicio | Coste |
|---|---|
| Railway (API + Worker + Postgres + Redis) | **~$15** |
| Vercel (dashboard) | **$0** (free tier) |
| 360dialog (WhatsApp Business API) | **~€49 + €0.005/mensaje** |
| Anthropic (Claude API) | **~$30** (estimado para 10 clínicas activas) |
| **Total** | **~$95–120/mes** |

A €99/clínica × 10 clínicas = **€990 ingresos** → margen ~88%.
