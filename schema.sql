-- ══════════════════════════════════════════════
-- SCHEMA POSTGRESQL — Agente Dental v1.0
-- ══════════════════════════════════════════════
-- Ejecutar: psql -U postgres -d dental_agent -f schema.sql

-- ── extensiones ──────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ── clinics ──────────────────────────────────
CREATE TABLE IF NOT EXISTS clinics (
    id               VARCHAR(50)  PRIMARY KEY,
    name             VARCHAR(200) NOT NULL,
    address          TEXT         NOT NULL,
    phone            VARCHAR(20)  NOT NULL,
    whatsapp_number  VARCHAR(20)  NOT NULL,
    webhook_secret   VARCHAR(100) NOT NULL,
    hours_lv         VARCHAR(20)  DEFAULT '09:00-20:00',
    hours_sat        VARCHAR(20)  DEFAULT '09:00-14:00',
    insurance        TEXT[]       DEFAULT '{}',
    parking          TEXT         DEFAULT '',
    active           BOOLEAN      DEFAULT true,
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  DEFAULT NOW()
);

-- ── patients ─────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    id           SERIAL       PRIMARY KEY,
    clinic_id    VARCHAR(50)  NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    phone        VARCHAR(20)  NOT NULL,
    name         VARCHAR(200),
    email        VARCHAR(200),
    last_visit   DATE,
    notes        TEXT,
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (clinic_id, phone)
);

-- ── clinic_services ──────────────────────────
CREATE TABLE IF NOT EXISTS clinic_services (
    id           SERIAL       PRIMARY KEY,
    clinic_id    VARCHAR(50)  NOT NULL REFERENCES clinics(id) ON DELETE CASCADE,
    name         VARCHAR(200) NOT NULL,
    price_from   INTEGER      NOT NULL,  -- euros
    active       BOOLEAN      DEFAULT true
);

-- ── appointments ─────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
    id                    VARCHAR(50)  PRIMARY KEY DEFAULT 'apt_' || gen_random_uuid()::text,
    clinic_id             VARCHAR(50)  NOT NULL REFERENCES clinics(id),
    patient_id            INTEGER      REFERENCES patients(id),
    patient_phone         VARCHAR(20)  NOT NULL,
    appointment_datetime  TIMESTAMPTZ  NOT NULL,
    treatment             VARCHAR(200) NOT NULL,
    dentist               VARCHAR(200) NOT NULL DEFAULT 'Sin asignar',
    duration_minutes      INTEGER      DEFAULT 30,
    status                VARCHAR(20)  NOT NULL DEFAULT 'confirmed'
                              CHECK (status IN ('confirmed','cancelled','completed','no_show','pending')),
    reminder_48h_sent     BOOLEAN      DEFAULT false,
    reminder_2h_sent      BOOLEAN      DEFAULT false,
    confirmation_received BOOLEAN      DEFAULT false,
    cancellation_reason   TEXT,
    created_at            TIMESTAMPTZ  DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  DEFAULT NOW()
);

-- ── conversations ─────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id             BIGSERIAL    PRIMARY KEY,
    clinic_id      VARCHAR(50)  NOT NULL REFERENCES clinics(id),
    patient_phone  VARCHAR(20)  NOT NULL,
    thread_id      VARCHAR(100) NOT NULL,    -- clinic_id + '_' + patient_phone
    role           VARCHAR(10)  NOT NULL CHECK (role IN ('user','assistant','system')),
    message        TEXT         NOT NULL,
    escalated      BOOLEAN      DEFAULT false,
    created_at     TIMESTAMPTZ  DEFAULT NOW()
);

-- ── quotes ───────────────────────────────────
CREATE TABLE IF NOT EXISTS quotes (
    id             SERIAL       PRIMARY KEY,
    clinic_id      VARCHAR(50)  NOT NULL REFERENCES clinics(id),
    patient_id     INTEGER      REFERENCES patients(id),
    patient_phone  VARCHAR(20)  NOT NULL,
    treatment      VARCHAR(200) NOT NULL,
    amount         DECIMAL(10,2),
    status         VARCHAR(20)  DEFAULT 'pending'
                       CHECK (status IN ('pending','accepted','rejected','expired')),
    sent_at        TIMESTAMPTZ  DEFAULT NOW(),
    followup_count INTEGER      DEFAULT 0,
    last_followup  TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ  DEFAULT NOW() + INTERVAL '30 days'
);

-- ══════════════════════════════════════════════
-- ÍNDICES
-- ══════════════════════════════════════════════

-- Citas: búsqueda por fecha (job recordatorios)
CREATE INDEX IF NOT EXISTS idx_apt_datetime
    ON appointments (clinic_id, appointment_datetime)
    WHERE status = 'confirmed';

-- Citas: recordatorios pendientes
CREATE INDEX IF NOT EXISTS idx_apt_reminders
    ON appointments (clinic_id, appointment_datetime, reminder_48h_sent, reminder_2h_sent)
    WHERE status = 'confirmed';

-- Pacientes: lookup por teléfono
CREATE INDEX IF NOT EXISTS idx_patients_phone
    ON patients (clinic_id, phone);

-- Conversaciones: historial por thread
CREATE INDEX IF NOT EXISTS idx_conv_thread
    ON conversations (thread_id, created_at DESC);

-- Presupuestos: seguimiento
CREATE INDEX IF NOT EXISTS idx_quotes_status
    ON quotes (clinic_id, status, expires_at);

-- ══════════════════════════════════════════════
-- FUNCIÓN: updated_at automático
-- ══════════════════════════════════════════════

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_clinics_updated_at
    BEFORE UPDATE ON clinics
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_appointments_updated_at
    BEFORE UPDATE ON appointments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ══════════════════════════════════════════════
-- DATOS DE DEMO
-- ══════════════════════════════════════════════

INSERT INTO clinics (id, name, address, phone, whatsapp_number, webhook_secret, insurance)
VALUES (
    'clinic_001',
    'Clínica Dental Sonríe',
    'Calle Gran Vía 45, 28013 Madrid',
    '+34 91 234 56 78',
    '+34 600 000 001',
    'CHANGE_THIS_SECRET_IN_PRODUCTION',
    ARRAY['Adeslas','Sanitas','Asisa','Mapfre']
) ON CONFLICT (id) DO NOTHING;

INSERT INTO clinic_services (clinic_id, name, price_from) VALUES
    ('clinic_001', 'Revisión + limpieza',  60),
    ('clinic_001', 'Ortodoncia invisible', 2500),
    ('clinic_001', 'Implante dental',      900),
    ('clinic_001', 'Blanqueamiento',       250),
    ('clinic_001', 'Endodoncia',           180),
    ('clinic_001', 'Urgencia dental',      50)
ON CONFLICT DO NOTHING;
