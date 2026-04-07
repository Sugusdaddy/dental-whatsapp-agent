'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Building2, Users, LayoutDashboard, Settings as SettingsIcon, LogOut, Plus,
  MessageSquare, Calendar, CheckCircle2, Clock, XCircle, AlertCircle,
  Search, Phone, MapPin, RefreshCw, Bot, UserCheck, X, ChevronRight,
  Activity, ArrowUpRight, MoreHorizontal, Hash, Mail, ShieldCheck, Filter,
  Sparkles, ScrollText, Bell, BellOff, ArrowLeft, Check, Stethoscope,
  AlertTriangle, Info,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────

interface AuthUser {
  user_id: string;
  email: string;
  name: string;
  role: 'admin' | 'clinic';
  clinic_id: string | null;
}

interface Clinic {
  clinic_id: string;
  name: string;
  address: string;
  phone: string;
  whatsapp_number: string;
  whatsapp_connected: boolean;
  total_appointments: number;
  active_conversations: number;
  status: 'active' | 'pending' | 'inactive';
}

interface AdminStats {
  total_clinics: number;
  active_clinics: number;
  total_users: number;
  total_appointments: number;
  today_appointments: number;
  active_conversations: number;
  confirmation_rate: number;
  confirmed_appointments: number;
  pending_appointments: number;
  cancelled_appointments: number;
}

interface ActivityItem {
  clinic_name: string;
  action: string;
  time_ago: string;
  timestamp: string;
  type: string;
}

interface UserRow {
  user_id: string;
  email: string;
  name: string;
  role: string;
  clinic_id: string | null;
  is_active: boolean;
}

interface ClinicStats {
  clinic_id: string;
  clinic_name: string;
  total_appointments: number;
  confirmed: number;
  pending: number;
  cancelled: number;
}

interface Conversation {
  phone: string;
  name: string;
  last_appointment: string;
  status: string;
  human_takeover: boolean;
}

// ─────────────────────────────────────────────────────────────
// Tiny helpers
// ─────────────────────────────────────────────────────────────

const cn = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');

async function api<T>(
  path: string,
  token: string | null,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let msg = `Error ${res.status}`;
    try {
      const j = await res.json();
      msg = j.detail || msg;
    } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function formatDateTime(iso: string) {
  try {
    const d = new Date(iso);
    return d.toLocaleString('es-ES', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

// ─────────────────────────────────────────────────────────────
// Primitives
// ─────────────────────────────────────────────────────────────

function Button({
  children,
  variant = 'default',
  size = 'md',
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'primary' | 'ghost' | 'danger';
  size?: 'sm' | 'md';
}) {
  const variants = {
    default:
      'bg-white text-neutral-900 border border-neutral-200 hover:bg-neutral-50 hover:border-neutral-300',
    primary:
      'bg-neutral-900 text-white border border-neutral-900 hover:bg-neutral-800',
    ghost:
      'bg-transparent text-neutral-700 border border-transparent hover:bg-neutral-100',
    danger:
      'bg-white text-red-600 border border-neutral-200 hover:bg-red-50 hover:border-red-200',
  };
  const sizes = {
    sm: 'h-8 px-3 text-xs',
    md: 'h-9 px-3.5 text-sm',
  };
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/10 focus-visible:ring-offset-1',
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        'w-full h-9 px-3 text-sm bg-white border border-neutral-200 rounded-md',
        'placeholder:text-neutral-400 text-neutral-900',
        'focus:outline-none focus:ring-2 focus:ring-neutral-900/10 focus:border-neutral-400',
        'transition-colors',
        props.className
      )}
    />
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-xs font-medium text-neutral-700 mb-1.5">{children}</label>;
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('bg-white border border-neutral-200 rounded-lg', className)}>{children}</div>
  );
}

function Badge({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue' | 'teal';
}) {
  const tones = {
    neutral: 'bg-neutral-100 text-neutral-700 border-neutral-200',
    green: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    teal: 'bg-teal-50 text-teal-700 border-teal-200',
  };
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 h-5 text-[11px] font-medium rounded-md border',
        tones[tone]
      )}
    >
      {children}
    </span>
  );
}

function Metric({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between mb-3">
        <span className="text-xs font-medium text-neutral-500 uppercase tracking-wide">
          {label}
        </span>
        <div className="text-neutral-400">{icon}</div>
      </div>
      <div className="text-3xl font-semibold tabular text-neutral-900 leading-none">{value}</div>
      {hint && <div className="text-xs text-neutral-500 mt-2 tabular">{hint}</div>}
    </Card>
  );
}

function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-end justify-between mb-8 pb-6 border-b border-neutral-200">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900 tracking-tight">{title}</h1>
        {description && <p className="text-sm text-neutral-500 mt-1">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="text-center py-16 px-6">
      <div className="inline-flex w-12 h-12 items-center justify-center rounded-lg bg-neutral-100 text-neutral-400 mb-4">
        {icon}
      </div>
      <h3 className="text-sm font-semibold text-neutral-900">{title}</h3>
      <p className="text-sm text-neutral-500 mt-1 max-w-sm mx-auto">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

function Spinner({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center justify-center', className)}>
      <div className="w-5 h-5 border-2 border-neutral-200 border-t-neutral-900 rounded-full animate-spin" />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Login
// ─────────────────────────────────────────────────────────────

function LoginPage({ onLogin }: { onLogin: (token: string, user: AuthUser) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const data = await api<{ token: string; user: AuthUser }>(
        '/api/auth/login',
        null,
        { method: 'POST', body: JSON.stringify({ email, password }) }
      );
      onLogin(data.token, data.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error de conexión');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-50 flex">
      {/* Left side — brand panel */}
      <div className="hidden lg:flex lg:w-[42%] bg-neutral-900 text-white p-12 flex-col justify-between relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, white 1px, transparent 0)',
            backgroundSize: '24px 24px',
          }}
        />
        <div className="relative">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-md bg-white text-neutral-900 flex items-center justify-center font-bold text-sm">
              D
            </div>
            <span className="font-semibold tracking-tight">Dental Agent</span>
          </div>
        </div>

        <div className="relative max-w-md">
          <h1 className="text-3xl font-semibold tracking-tight leading-tight mb-4">
            La recepción virtual de tu clínica, siempre disponible.
          </h1>
          <p className="text-neutral-400 leading-relaxed">
            Confirma citas, atiende pacientes y gestiona la agenda 24/7 desde WhatsApp,
            sin que tu equipo levante el teléfono.
          </p>
        </div>

        <div className="relative grid grid-cols-3 gap-6 text-sm">
          {[
            ['24/7', 'Disponible'],
            ['<30s', 'Respuesta media'],
            ['98%', 'Confirmaciones'],
          ].map(([v, l]) => (
            <div key={l}>
              <div className="text-2xl font-semibold tabular">{v}</div>
              <div className="text-neutral-500 text-xs mt-1">{l}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right side — form */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="lg:hidden flex items-center gap-2.5 mb-10">
            <div className="w-8 h-8 rounded-md bg-neutral-900 text-white flex items-center justify-center font-bold text-sm">
              D
            </div>
            <span className="font-semibold tracking-tight">Dental Agent</span>
          </div>

          <h2 className="text-2xl font-semibold text-neutral-900 tracking-tight">
            Inicia sesión
          </h2>
          <p className="text-sm text-neutral-500 mt-1.5 mb-8">
            Accede al panel de control de tu clínica.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <div>
              <Label>Email</Label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@clinica.com"
                required
                autoComplete="email"
              />
            </div>

            <div>
              <Label>Contraseña</Label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                autoComplete="current-password"
              />
            </div>

            <Button
              type="submit"
              variant="primary"
              disabled={loading}
              className="w-full h-10"
            >
              {loading ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Entrando…
                </>
              ) : (
                'Entrar'
              )}
            </Button>
          </form>

          <p className="text-xs text-neutral-500 text-center mt-8">
            ¿Sin cuenta? Contacta con tu administrador.
          </p>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────

function Sidebar({
  user,
  activeTab,
  setActiveTab,
  onLogout,
}: {
  user: AuthUser;
  activeTab: string;
  setActiveTab: (t: string) => void;
  onLogout: () => void;
}) {
  const isAdmin = user.role === 'admin';

  const tabs = isAdmin
    ? [
        { id: 'overview', label: 'Resumen', icon: LayoutDashboard },
        { id: 'clinics', label: 'Clínicas', icon: Building2 },
        { id: 'users', label: 'Usuarios', icon: Users },
      ]
    : [
        { id: 'dashboard', label: 'Resumen', icon: LayoutDashboard },
        { id: 'conversations', label: 'Conversaciones', icon: MessageSquare },
        { id: 'appointments', label: 'Citas', icon: Calendar },
        { id: 'logs', label: 'Logs', icon: ScrollText },
        { id: 'settings', label: 'Configuración', icon: SettingsIcon },
      ];

  return (
    <aside className="w-60 bg-white border-r border-neutral-200 flex flex-col flex-shrink-0">
      <div className="p-5 border-b border-neutral-200">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-md bg-neutral-900 text-white flex items-center justify-center font-bold text-sm">
            D
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-neutral-900 truncate">
              Dental Agent
            </div>
            <div className="text-[11px] text-neutral-500 truncate">
              {isAdmin ? 'Administración' : 'Panel de clínica'}
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-0.5">
        <div className="text-[10px] font-semibold text-neutral-400 uppercase tracking-wider px-3 py-2">
          Menú
        </div>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'w-full flex items-center gap-2.5 px-3 h-9 rounded-md text-sm font-medium transition-colors',
                active
                  ? 'bg-neutral-100 text-neutral-900'
                  : 'text-neutral-600 hover:bg-neutral-50 hover:text-neutral-900'
              )}
            >
              <Icon className={cn('w-4 h-4', active ? 'text-neutral-900' : 'text-neutral-400')} />
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div className="p-3 border-t border-neutral-200">
        <div className="flex items-center gap-2.5 p-2 rounded-md hover:bg-neutral-50 group">
          <div className="w-8 h-8 rounded-full bg-neutral-200 text-neutral-700 flex items-center justify-center font-semibold text-xs flex-shrink-0">
            {user.name.charAt(0).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-neutral-900 truncate">{user.name}</div>
            <div className="text-[11px] text-neutral-500 truncate">{user.email}</div>
          </div>
          <button
            onClick={onLogout}
            className="p-1.5 text-neutral-400 hover:text-neutral-900 rounded opacity-0 group-hover:opacity-100 transition-opacity"
            title="Cerrar sesión"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}

// ─────────────────────────────────────────────────────────────
// Admin: Overview
// ─────────────────────────────────────────────────────────────

function AdminOverview({ token }: { token: string }) {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    setRefreshing(true);
    try {
      const [s, a] = await Promise.all([
        api<AdminStats>('/api/auth/admin/stats', token),
        api<{ activities: ActivityItem[] }>('/api/auth/admin/activity?limit=10', token),
      ]);
      setStats(s);
      setActivities(a.activities || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 30000);
    return () => clearInterval(i);
  }, [fetchData]);

  if (loading) return <Spinner className="h-64" />;

  return (
    <>
      <PageHeader
        title="Resumen general"
        description="Datos en tiempo real de todas las clínicas conectadas."
        actions={
          <Button onClick={fetchData} disabled={refreshing}>
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            Actualizar
          </Button>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        <Metric
          label="Clínicas activas"
          value={stats?.active_clinics ?? 0}
          hint={`${stats?.total_clinics ?? 0} totales`}
          icon={<Building2 className="w-4 h-4" />}
        />
        <Metric
          label="Usuarios"
          value={stats?.total_users ?? 0}
          icon={<Users className="w-4 h-4" />}
        />
        <Metric
          label="Citas hoy"
          value={stats?.today_appointments ?? 0}
          hint={`${stats?.total_appointments ?? 0} acumuladas`}
          icon={<Calendar className="w-4 h-4" />}
        />
        <Metric
          label="Conversaciones activas"
          value={stats?.active_conversations ?? 0}
          icon={<MessageSquare className="w-4 h-4" />}
        />
        <Metric
          label="Tasa de confirmación"
          value={`${stats?.confirmation_rate ?? 0}%`}
          hint={`${stats?.confirmed_appointments ?? 0} confirmadas`}
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <Metric
          label="Pendientes"
          value={stats?.pending_appointments ?? 0}
          hint={`${stats?.cancelled_appointments ?? 0} canceladas`}
          icon={<Clock className="w-4 h-4" />}
        />
      </div>

      <Card>
        <div className="px-5 py-4 border-b border-neutral-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-neutral-400" />
            <h2 className="text-sm font-semibold text-neutral-900">Actividad reciente</h2>
          </div>
          <span className="text-xs text-neutral-500 tabular">{activities.length} eventos</span>
        </div>
        {activities.length === 0 ? (
          <EmptyState
            icon={<Activity className="w-5 h-5" />}
            title="Sin actividad por ahora"
            description="Cuando los pacientes empiecen a conversar verás los eventos aquí."
          />
        ) : (
          <div className="divide-y divide-neutral-100">
            {activities.map((a, i) => (
              <div
                key={i}
                className="px-5 py-3.5 flex items-center justify-between hover:bg-neutral-50/50 transition-colors"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={cn(
                      'w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0',
                      a.type === 'appointment'
                        ? 'bg-teal-50 text-teal-600'
                        : 'bg-neutral-100 text-neutral-500'
                    )}
                  >
                    <Calendar className="w-4 h-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-neutral-900 truncate">
                      {a.clinic_name}
                    </div>
                    <div className="text-xs text-neutral-500 truncate">{a.action}</div>
                  </div>
                </div>
                <span className="text-xs text-neutral-500 tabular flex-shrink-0 ml-4">
                  {a.time_ago}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Admin: Clinics
// ─────────────────────────────────────────────────────────────

function AdminClinics({ token }: { token: string }) {
  const [clinics, setClinics] = useState<Clinic[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');

  const fetchClinics = useCallback(async () => {
    try {
      const data = await api<{ clinics: Clinic[] }>('/api/auth/clinics', token);
      setClinics(data.clinics || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchClinics();
  }, [fetchClinics]);

  const filtered = useMemo(
    () =>
      clinics.filter(
        (c) =>
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          c.clinic_id.toLowerCase().includes(search.toLowerCase())
      ),
    [clinics, search]
  );

  if (loading) return <Spinner className="h-64" />;

  return (
    <>
      <PageHeader
        title="Clínicas"
        description={`${clinics.length} ${clinics.length === 1 ? 'clínica registrada' : 'clínicas registradas'}.`}
        actions={
          <Button variant="primary" onClick={() => setShowCreate(true)}>
            <Plus className="w-3.5 h-3.5" />
            Nueva clínica
          </Button>
        }
      />

      <div className="relative mb-5 max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-neutral-400" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Buscar por nombre o ID…"
          className="pl-9"
        />
      </div>

      {filtered.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Building2 className="w-5 h-5" />}
            title={search ? 'Sin resultados' : 'Aún no hay clínicas'}
            description={
              search
                ? 'Prueba con otro término de búsqueda.'
                : 'Crea tu primera clínica para empezar a recibir mensajes.'
            }
            action={
              !search && (
                <Button variant="primary" onClick={() => setShowCreate(true)}>
                  <Plus className="w-3.5 h-3.5" />
                  Crear clínica
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-neutral-200 bg-neutral-50/50">
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Clínica
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  WhatsApp
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Contacto
                </th>
                <th className="text-right text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Citas
                </th>
                <th className="text-right text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Conversaciones
                </th>
                <th className="px-5 py-3 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr
                  key={c.clinic_id}
                  className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50/50 transition-colors"
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 bg-neutral-100 rounded-md flex items-center justify-center flex-shrink-0">
                        <Building2 className="w-4 h-4 text-neutral-500" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-neutral-900 truncate">
                          {c.name}
                        </div>
                        <div className="text-[11px] text-neutral-500 font-mono truncate">
                          {c.clinic_id}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    {c.whatsapp_connected ? (
                      <Badge tone="green">
                        <CheckCircle2 className="w-3 h-3" />
                        Conectado
                      </Badge>
                    ) : (
                      <Badge tone="amber">
                        <AlertCircle className="w-3 h-3" />
                        Sin conectar
                      </Badge>
                    )}
                  </td>
                  <td className="px-5 py-4 text-sm text-neutral-600">
                    <div className="flex items-center gap-1.5 text-xs">
                      <Phone className="w-3 h-3 text-neutral-400" />
                      {c.phone || '—'}
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-neutral-500 mt-0.5">
                      <MapPin className="w-3 h-3 text-neutral-400" />
                      <span className="truncate max-w-[200px]">{c.address || '—'}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-right text-sm font-medium text-neutral-900 tabular">
                    {c.total_appointments}
                  </td>
                  <td className="px-5 py-4 text-right text-sm font-medium text-neutral-900 tabular">
                    {c.active_conversations}
                  </td>
                  <td className="px-5 py-4 text-right">
                    <button className="p-1.5 text-neutral-400 hover:text-neutral-900 rounded">
                      <MoreHorizontal className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {showCreate && (
        <CreateClinicModal
          token={token}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            fetchClinics();
          }}
        />
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Admin: Users
// ─────────────────────────────────────────────────────────────

function AdminUsers({ token }: { token: string }) {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<UserRow[]>('/api/auth/users', token)
      .then(setUsers)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) return <Spinner className="h-64" />;

  return (
    <>
      <PageHeader
        title="Usuarios"
        description={`${users.length} ${users.length === 1 ? 'usuario registrado' : 'usuarios registrados'}.`}
      />

      {users.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Users className="w-5 h-5" />}
            title="Aún no hay usuarios"
            description="Los usuarios se crean al registrar una clínica."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-neutral-200 bg-neutral-50/50">
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Usuario
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Rol
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Clínica
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Estado
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.user_id}
                  className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50/50"
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-neutral-200 text-neutral-700 flex items-center justify-center text-xs font-semibold">
                        {u.name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div className="text-sm font-medium text-neutral-900">{u.name}</div>
                        <div className="text-xs text-neutral-500">{u.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    {u.role === 'admin' ? (
                      <Badge tone="neutral">
                        <ShieldCheck className="w-3 h-3" />
                        Admin
                      </Badge>
                    ) : (
                      <Badge tone="blue">
                        <Building2 className="w-3 h-3" />
                        Clínica
                      </Badge>
                    )}
                  </td>
                  <td className="px-5 py-4 text-xs font-mono text-neutral-500">
                    {u.clinic_id || '—'}
                  </td>
                  <td className="px-5 py-4">
                    {u.is_active ? (
                      <Badge tone="green">Activo</Badge>
                    ) : (
                      <Badge tone="red">Inactivo</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Clinic: Dashboard (resumen)
// ─────────────────────────────────────────────────────────────

function ClinicDashboard({ token, clinicId }: { token: string; clinicId: string }) {
  const [stats, setStats] = useState<ClinicStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    setRefreshing(true);
    try {
      const s = await api<ClinicStats>(`/api/stats/${clinicId}`, token);
      setStats(s);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, clinicId]);

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 10000);
    return () => clearInterval(i);
  }, [fetchData]);

  if (loading) return <Spinner className="h-64" />;

  const total = stats?.total_appointments ?? 0;
  const confirmRate = total > 0 ? Math.round(((stats?.confirmed ?? 0) / total) * 100) : 0;

  return (
    <>
      <PageHeader
        title={stats?.clinic_name || 'Mi clínica'}
        description="Resumen de actividad en tiempo real."
        actions={
          <Button onClick={fetchData} disabled={refreshing}>
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            Actualizar
          </Button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Metric
          label="Total citas"
          value={total}
          icon={<Calendar className="w-4 h-4" />}
        />
        <Metric
          label="Confirmadas"
          value={stats?.confirmed ?? 0}
          hint={`${confirmRate}% del total`}
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <Metric
          label="Pendientes"
          value={stats?.pending ?? 0}
          icon={<Clock className="w-4 h-4" />}
        />
        <Metric
          label="Canceladas"
          value={stats?.cancelled ?? 0}
          icon={<XCircle className="w-4 h-4" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2 p-6">
          <h3 className="text-sm font-semibold text-neutral-900 mb-1">
            Estado del agente
          </h3>
          <p className="text-xs text-neutral-500 mb-5">
            Tu recepción virtual está atendiendo a los pacientes ahora mismo.
          </p>
          <div className="flex items-center gap-3 p-4 bg-emerald-50 border border-emerald-200 rounded-md">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <div className="flex-1">
              <div className="text-sm font-medium text-emerald-900">Operativo</div>
              <div className="text-xs text-emerald-700">
                Procesando mensajes de WhatsApp en tiempo real
              </div>
            </div>
            <Bot className="w-5 h-5 text-emerald-600" />
          </div>
        </Card>

        <Card className="p-6">
          <h3 className="text-sm font-semibold text-neutral-900 mb-1">Tasa de confirmación</h3>
          <p className="text-xs text-neutral-500 mb-5">Sobre el total de citas.</p>
          <div className="flex items-end gap-2 mb-3">
            <div className="text-4xl font-semibold tabular text-neutral-900 leading-none">
              {confirmRate}%
            </div>
            {confirmRate >= 80 && (
              <ArrowUpRight className="w-5 h-5 text-emerald-500 mb-1" />
            )}
          </div>
          <div className="w-full h-1.5 bg-neutral-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-neutral-900 rounded-full transition-all duration-500"
              style={{ width: `${confirmRate}%` }}
            />
          </div>
        </Card>
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Clinic: Conversations
// ─────────────────────────────────────────────────────────────

function ClinicConversations({ token, clinicId }: { token: string; clinicId: string }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const seenPhonesRef = useRef<Set<string>>(new Set());
  const isFirstLoadRef = useRef(true);

  const fetchData = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await api<{ conversations: Conversation[] }>(
        `/api/conversations/${clinicId}`,
        token
      );
      const fresh = data.conversations || [];

      // Detección de nuevas conversaciones para notificación browser.
      // Nota: solo dispara cuando la pestaña está abierta. Para
      // notificaciones reales con la pestaña cerrada hace falta Web
      // Push (VAPID + service worker), que es trabajo de otro turno.
      if (
        !isFirstLoadRef.current &&
        typeof window !== 'undefined' &&
        'Notification' in window &&
        Notification.permission === 'granted'
      ) {
        const previous = seenPhonesRef.current;
        const newOnes = fresh.filter((c) => !previous.has(c.phone));
        for (const c of newOnes) {
          try {
            new Notification('Nueva conversación', {
              body: `${c.name || 'Paciente'} (${c.phone})`,
              tag: `dental-${c.phone}`,
              icon: '/favicon.ico',
            });
          } catch {
            /* algunos browsers son estrictos con notifications fuera de gestures */
          }
        }
      }

      seenPhonesRef.current = new Set(fresh.map((c) => c.phone));
      isFirstLoadRef.current = false;
      setConversations(fresh);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, clinicId]);

  useEffect(() => {
    fetchData();
    const i = setInterval(fetchData, 10000);
    return () => clearInterval(i);
  }, [fetchData]);

  const handleTakeover = async (phone: string, currentlyTaken: boolean) => {
    setBusy(phone);
    try {
      await api(`/api/takeover/${clinicId}`, token, {
        method: 'POST',
        body: JSON.stringify({ phone, enable: !currentlyTaken }),
      });
      // Optimistic update
      setConversations((prev) =>
        prev.map((c) =>
          c.phone === phone ? { ...c, human_takeover: !currentlyTaken } : c
        )
      );
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <Spinner className="h-64" />;

  return (
    <>
      <PageHeader
        title="Conversaciones"
        description="Pacientes en contacto con tu clínica vía WhatsApp."
        actions={
          <Button onClick={fetchData} disabled={refreshing}>
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            Actualizar
          </Button>
        }
      />

      {conversations.length === 0 ? (
        <Card>
          <EmptyState
            icon={<MessageSquare className="w-5 h-5" />}
            title="Sin conversaciones activas"
            description="Cuando un paciente escriba a tu WhatsApp, la conversación aparecerá aquí."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="px-5 py-3 border-b border-neutral-200 flex items-center justify-between bg-neutral-50/50">
            <span className="text-xs text-neutral-500 tabular">
              {conversations.length} {conversations.length === 1 ? 'paciente' : 'pacientes'}
            </span>
            <span className="text-[11px] text-neutral-400">
              Actualización automática cada 10s
            </span>
          </div>
          <div className="divide-y divide-neutral-100">
            {conversations.map((conv) => (
              <div
                key={conv.phone}
                className="px-5 py-4 flex items-center gap-4 hover:bg-neutral-50/50 transition-colors"
              >
                <div
                  className={cn(
                    'w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0',
                    conv.human_takeover
                      ? 'bg-amber-50 text-amber-600 border border-amber-200'
                      : 'bg-neutral-100 text-neutral-500'
                  )}
                >
                  {conv.human_takeover ? (
                    <UserCheck className="w-4 h-4" />
                  ) : (
                    <Bot className="w-4 h-4" />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-neutral-900 truncate">
                      {conv.name || 'Paciente'}
                    </span>
                    {conv.human_takeover && <Badge tone="amber">Manual</Badge>}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-neutral-500 mt-0.5">
                    <span className="flex items-center gap-1 tabular">
                      <Phone className="w-3 h-3" />
                      {conv.phone}
                    </span>
                    <span className="flex items-center gap-1 tabular">
                      <Calendar className="w-3 h-3" />
                      {formatDateTime(conv.last_appointment)}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  <Badge
                    tone={
                      conv.status === 'confirmed'
                        ? 'green'
                        : conv.status === 'pending'
                          ? 'amber'
                          : 'neutral'
                    }
                  >
                    {conv.status}
                  </Badge>
                  <Button
                    size="sm"
                    variant={conv.human_takeover ? 'primary' : 'default'}
                    onClick={() => handleTakeover(conv.phone, conv.human_takeover)}
                    disabled={busy === conv.phone}
                  >
                    {busy === conv.phone ? (
                      <RefreshCw className="w-3 h-3 animate-spin" />
                    ) : conv.human_takeover ? (
                      'Devolver al bot'
                    ) : (
                      'Tomar control'
                    )}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Clinic: Appointments
// ─────────────────────────────────────────────────────────────

type AppointmentRow = {
  appointment_id: string;
  patient_phone: string;
  patient_name: string;
  datetime: string;
  treatment: string;
  dentist: string;
  duration_min: number;
  status: string;
  confirmation_received: boolean;
};

function ClinicAppointments({ token, clinicId }: { token: string; clinicId: string }) {
  const [stats, setStats] = useState<ClinicStats | null>(null);
  const [rows, setRows] = useState<AppointmentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [whenFilter, setWhenFilter] = useState<'all' | 'upcoming' | 'past' | 'today'>('upcoming');
  const [selectedApt, setSelectedApt] = useState<AppointmentRow | null>(null);

  const fetchData = useCallback(async () => {
    setRefreshing(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.set('status', statusFilter);
      params.set('when', whenFilter);
      params.set('limit', '100');

      const [s, list] = await Promise.all([
        api<ClinicStats>(`/api/stats/${clinicId}`, token),
        api<{ total: number; appointments: AppointmentRow[] }>(
          `/api/appointments/${clinicId}?${params.toString()}`,
          token
        ),
      ]);
      setStats(s);
      setRows(list.appointments);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, clinicId, statusFilter, whenFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) return <Spinner className="h-64" />;

  const statusTone = (s: string): 'green' | 'amber' | 'red' | 'neutral' | 'blue' => {
    if (s === 'confirmed') return 'green';
    if (s === 'pending') return 'amber';
    if (s === 'cancelled' || s === 'no_show') return 'red';
    if (s === 'completed') return 'blue';
    return 'neutral';
  };

  const statusLabel = (s: string): string =>
    ({
      confirmed: 'Confirmada',
      pending: 'Pendiente',
      cancelled: 'Cancelada',
      no_show: 'No-show',
      completed: 'Completada',
    }[s] || s);

  const formatFullDateTime = (iso: string) => {
    try {
      const d = new Date(iso);
      return d.toLocaleString('es-ES', {
        weekday: 'short',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  return (
    <>
      <PageHeader
        title="Citas"
        description="Estado de todas las citas gestionadas por el agente."
        actions={
          <Button onClick={fetchData} disabled={refreshing}>
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
            Actualizar
          </Button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Metric
          label="Total"
          value={stats?.total_appointments ?? 0}
          icon={<Calendar className="w-4 h-4" />}
        />
        <Metric
          label="Confirmadas"
          value={stats?.confirmed ?? 0}
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <Metric
          label="Pendientes"
          value={stats?.pending ?? 0}
          icon={<Clock className="w-4 h-4" />}
        />
        <Metric
          label="Canceladas"
          value={stats?.cancelled ?? 0}
          icon={<XCircle className="w-4 h-4" />}
        />
      </div>

      {/* Filtros */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <div className="flex items-center gap-1 text-xs text-neutral-500 mr-2">
          <Filter className="w-3.5 h-3.5" />
          Filtros:
        </div>
        {(['upcoming', 'today', 'past', 'all'] as const).map((w) => (
          <button
            key={w}
            onClick={() => setWhenFilter(w)}
            className={cn(
              'h-8 px-3 text-xs font-medium rounded-md border transition-colors',
              whenFilter === w
                ? 'bg-neutral-900 text-white border-neutral-900'
                : 'bg-white text-neutral-700 border-neutral-200 hover:bg-neutral-50'
            )}
          >
            {w === 'upcoming' ? 'Próximas' : w === 'today' ? 'Hoy' : w === 'past' ? 'Pasadas' : 'Todas'}
          </button>
        ))}
        <div className="w-px h-5 bg-neutral-200 mx-1" />
        {(['all', 'confirmed', 'pending', 'cancelled'] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={cn(
              'h-8 px-3 text-xs font-medium rounded-md border transition-colors',
              statusFilter === s
                ? 'bg-neutral-900 text-white border-neutral-900'
                : 'bg-white text-neutral-700 border-neutral-200 hover:bg-neutral-50'
            )}
          >
            {s === 'all'
              ? 'Cualquier estado'
              : s === 'confirmed'
                ? 'Confirmadas'
                : s === 'pending'
                  ? 'Pendientes'
                  : 'Canceladas'}
          </button>
        ))}
      </div>

      {/* Tabla */}
      {rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Calendar className="w-5 h-5" />}
            title="Sin citas"
            description="No hay citas que coincidan con los filtros seleccionados."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-neutral-200 bg-neutral-50/50">
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Paciente
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Fecha y hora
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Tratamiento
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Doctor
                </th>
                <th className="text-right text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Duración
                </th>
                <th className="text-left text-[11px] font-semibold text-neutral-500 uppercase tracking-wider px-5 py-3">
                  Estado
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.appointment_id}
                  onClick={() => setSelectedApt(row)}
                  className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50 transition-colors cursor-pointer"
                >
                  <td className="px-5 py-3.5">
                    <div className="text-sm font-medium text-neutral-900">{row.patient_name}</div>
                    <div className="text-xs text-neutral-500 tabular">{row.patient_phone}</div>
                  </td>
                  <td className="px-5 py-3.5 text-sm text-neutral-700 tabular">
                    {formatFullDateTime(row.datetime)}
                  </td>
                  <td className="px-5 py-3.5 text-sm text-neutral-700">{row.treatment}</td>
                  <td className="px-5 py-3.5 text-sm text-neutral-600">{row.dentist || '—'}</td>
                  <td className="px-5 py-3.5 text-sm text-neutral-600 text-right tabular">
                    {row.duration_min} min
                  </td>
                  <td className="px-5 py-3.5">
                    <Badge tone={statusTone(row.status)}>{statusLabel(row.status)}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {selectedApt && (
        <AppointmentDetailModal
          token={token}
          appointment={selectedApt}
          onClose={() => setSelectedApt(null)}
          onChanged={() => {
            setSelectedApt(null);
            fetchData();
          }}
        />
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Notification settings (browser notifications)
// ─────────────────────────────────────────────────────────────

function NotificationSettings() {
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    'default'
  );
  const [requesting, setRequesting] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      setPermission('unsupported');
      return;
    }
    setPermission(Notification.permission);
  }, []);

  const handleRequest = async () => {
    if (permission === 'unsupported') return;
    setRequesting(true);
    try {
      const result = await Notification.requestPermission();
      setPermission(result);
      if (result === 'granted') {
        // Notif de prueba para confirmar que funciona
        try {
          new Notification('Notificaciones activadas', {
            body: 'Te avisaremos cuando llegue una nueva conversación.',
            icon: '/favicon.ico',
          });
        } catch {}
      }
    } finally {
      setRequesting(false);
    }
  };

  const tone =
    permission === 'granted'
      ? 'green'
      : permission === 'denied' || permission === 'unsupported'
        ? 'red'
        : 'amber';

  const label = {
    granted: 'Activadas',
    denied: 'Bloqueadas',
    default: 'Sin configurar',
    unsupported: 'No soportadas',
  }[permission];

  return (
    <Card className="p-6">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-md bg-blue-50 border border-blue-200 flex items-center justify-center flex-shrink-0">
          {permission === 'granted' ? (
            <Bell className="w-4 h-4 text-blue-600" />
          ) : (
            <BellOff className="w-4 h-4 text-blue-600" />
          )}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-neutral-900">
              Notificaciones del navegador
            </h2>
            <Badge tone={tone}>{label}</Badge>
          </div>
          <p className="text-xs text-neutral-500 mt-0.5">
            Recibe un aviso del navegador cuando llegue una nueva conversación.
          </p>
        </div>
      </div>

      <div className="text-xs text-neutral-600 leading-relaxed bg-neutral-50 border border-neutral-200 rounded-md p-3 mb-4">
        <strong className="text-neutral-900">Importante:</strong> las
        notificaciones solo funcionan mientras tengas esta pestaña abierta.
        Para avisos con la pestaña cerrada hace falta una integración Web Push
        (en construcción).
      </div>

      {permission === 'default' && (
        <Button
          type="button"
          variant="primary"
          onClick={handleRequest}
          disabled={requesting}
        >
          {requesting ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              Pidiendo permiso…
            </>
          ) : (
            <>
              <Bell className="w-3.5 h-3.5" />
              Activar notificaciones
            </>
          )}
        </Button>
      )}

      {permission === 'denied' && (
        <p className="text-xs text-neutral-600">
          Las notificaciones están bloqueadas en tu navegador. Tienes que
          activarlas manualmente en la barra de direcciones (icono del candado
          → Permisos → Notificaciones).
        </p>
      )}

      {permission === 'unsupported' && (
        <p className="text-xs text-neutral-600">
          Tu navegador no soporta notificaciones. Prueba con una versión
          reciente de Chrome, Firefox o Safari.
        </p>
      )}

      {permission === 'granted' && (
        <p className="text-xs text-emerald-700 flex items-center gap-1.5">
          <CheckCircle2 className="w-3.5 h-3.5" />
          Recibirás un aviso del navegador cada vez que un paciente nuevo
          escriba a tu WhatsApp.
        </p>
      )}
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Clinic: Settings
// ─────────────────────────────────────────────────────────────

function ClinicSettings({ token, clinicId }: { token: string; clinicId: string }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [config, setConfig] = useState({
    clinic_name: '',
    address: '',
    phone: '',
    whatsapp_number: '',
    api_key: '',
  });

  // Precarga: /api/clinics/{id} devuelve el detalle completo de la clínica.
  useEffect(() => {
    let cancelled = false;
    api<{
      clinic_id: string;
      name: string;
      address: string;
      phone: string;
      whatsapp_number: string;
    }>(`/api/clinics/${clinicId}`, token)
      .then((c) => {
        if (cancelled) return;
        setConfig((prev) => ({
          ...prev,
          clinic_name: c.name || '',
          address: c.address || '',
          phone: c.phone || '',
          whatsapp_number: c.whatsapp_number || '',
        }));
      })
      .catch((err) => {
        if (!cancelled) {
          console.error('No se pudo cargar la clínica:', err);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, clinicId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    setError('');
    try {
      // Mapeamos clinic_name → name (lo que espera el backend).
      const payload: Record<string, string> = {
        name: config.clinic_name,
        address: config.address,
        phone: config.phone,
        whatsapp_number: config.whatsapp_number,
      };
      await api(`/api/clinics/${clinicId}`, token, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'No se pudo guardar. Verifica tu conexión.'
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Spinner className="h-64" />;

  return (
    <>
      <PageHeader
        title="Configuración"
        description="Ajustes de tu clínica y conexión con WhatsApp Business."
      />

      <form onSubmit={handleSubmit} className="space-y-5 max-w-3xl">
        {/* WhatsApp section */}
        <Card className="p-6">
          <div className="flex items-start gap-3 mb-5">
            <div className="w-9 h-9 rounded-md bg-emerald-50 border border-emerald-200 flex items-center justify-center flex-shrink-0">
              <MessageSquare className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="flex-1">
              <h2 className="text-sm font-semibold text-neutral-900">WhatsApp Business</h2>
              <p className="text-xs text-neutral-500 mt-0.5">
                Conecta tu número de WhatsApp Business vía 360dialog.
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <Label>Número de WhatsApp</Label>
              <Input
                type="tel"
                value={config.whatsapp_number}
                onChange={(e) => setConfig({ ...config, whatsapp_number: e.target.value })}
                placeholder="+34 600 000 000"
              />
            </div>
            <div>
              <Label>API Key (360dialog)</Label>
              <Input
                type="password"
                value={config.api_key}
                onChange={(e) => setConfig({ ...config, api_key: e.target.value })}
                placeholder="••••••••••••••••"
              />
              <p className="text-xs text-neutral-500 mt-1.5">
                Obtén tu clave en{' '}
                <a
                  href="https://hub.360dialog.com"
                  target="_blank"
                  rel="noreferrer"
                  className="text-neutral-900 underline underline-offset-2 hover:no-underline"
                >
                  hub.360dialog.com
                </a>
                .
              </p>
            </div>
          </div>
        </Card>

        {/* Clinic info */}
        <Card className="p-6">
          <div className="flex items-start gap-3 mb-5">
            <div className="w-9 h-9 rounded-md bg-neutral-100 flex items-center justify-center flex-shrink-0">
              <Building2 className="w-4 h-4 text-neutral-500" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-neutral-900">Información de la clínica</h2>
              <p className="text-xs text-neutral-500 mt-0.5">
                Estos datos aparecen en los mensajes que envía el agente.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="md:col-span-2">
              <Label>Nombre</Label>
              <Input
                value={config.clinic_name}
                onChange={(e) => setConfig({ ...config, clinic_name: e.target.value })}
                placeholder="Clínica Dental Madrid"
              />
            </div>
            <div>
              <Label>Teléfono</Label>
              <Input
                value={config.phone}
                onChange={(e) => setConfig({ ...config, phone: e.target.value })}
                placeholder="+34 91 234 56 78"
              />
            </div>
            <div>
              <Label>ID de clínica</Label>
              <Input value={clinicId} disabled className="font-mono text-xs bg-neutral-50" />
            </div>
            <div className="md:col-span-2">
              <Label>Dirección</Label>
              <Input
                value={config.address}
                onChange={(e) => setConfig({ ...config, address: e.target.value })}
                placeholder="Calle Gran Vía 45, 28013 Madrid"
              />
            </div>
          </div>
        </Card>

        {/* Notifications */}
        <NotificationSettings />

        <div className="flex items-center justify-end gap-3">
          {error && (
            <span className="text-xs text-red-600 flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {error}
            </span>
          )}
          {saved && (
            <span className="text-xs text-emerald-600 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              Guardado
            </span>
          )}
          <Button type="submit" variant="primary" disabled={saving}>
            {saving ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Guardando…
              </>
            ) : (
              'Guardar cambios'
            )}
          </Button>
        </div>
      </form>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Appointment detail modal
// ─────────────────────────────────────────────────────────────

function AppointmentDetailModal({
  token,
  appointment,
  onClose,
  onChanged,
}: {
  token: string;
  appointment: AppointmentRow;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<'confirm' | 'cancel' | null>(null);
  const [error, setError] = useState('');
  const [reason, setReason] = useState('');
  const [showReason, setShowReason] = useState(false);

  const fmt = (iso: string) => {
    try {
      return new Date(iso).toLocaleString('es-ES', {
        weekday: 'long',
        day: '2-digit',
        month: 'long',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  const tone = (s: string): 'green' | 'amber' | 'red' | 'neutral' | 'blue' => {
    if (s === 'confirmed') return 'green';
    if (s === 'pending') return 'amber';
    if (s === 'cancelled' || s === 'no_show') return 'red';
    if (s === 'completed') return 'blue';
    return 'neutral';
  };

  const label: Record<string, string> = {
    confirmed: 'Confirmada',
    pending: 'Pendiente',
    cancelled: 'Cancelada',
    no_show: 'No-show',
    completed: 'Completada',
  };

  const handleConfirm = async () => {
    setBusy('confirm');
    setError('');
    try {
      await api(`/api/appointments/${appointment.appointment_id}/confirm`, token, {
        method: 'POST',
      });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al confirmar');
      setBusy(null);
    }
  };

  const handleCancel = async () => {
    setBusy('cancel');
    setError('');
    try {
      await api(`/api/appointments/${appointment.appointment_id}/cancel`, token, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al cancelar');
      setBusy(null);
    }
  };

  const isFinalState =
    appointment.status === 'cancelled' ||
    appointment.status === 'completed' ||
    appointment.status === 'no_show';

  return (
    <div
      className="fixed inset-0 bg-neutral-900/40 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg w-full max-w-md shadow-2xl border border-neutral-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-200">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-neutral-400" />
            <h2 className="text-sm font-semibold text-neutral-900">Cita</h2>
            <Badge tone={tone(appointment.status)}>
              {label[appointment.status] || appointment.status}
            </Badge>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-neutral-400 hover:text-neutral-900 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* Patient */}
          <div>
            <div className="text-[10px] font-semibold text-neutral-400 uppercase tracking-wider mb-1">
              Paciente
            </div>
            <div className="text-sm font-medium text-neutral-900">
              {appointment.patient_name}
            </div>
            <div className="text-xs text-neutral-500 tabular flex items-center gap-1 mt-0.5">
              <Phone className="w-3 h-3" />
              {appointment.patient_phone}
            </div>
          </div>

          <div className="border-t border-neutral-100" />

          {/* Datetime */}
          <div>
            <div className="text-[10px] font-semibold text-neutral-400 uppercase tracking-wider mb-1">
              Fecha y hora
            </div>
            <div className="text-sm text-neutral-900 capitalize">
              {fmt(appointment.datetime)}
            </div>
            <div className="text-xs text-neutral-500 tabular mt-0.5">
              Duración: {appointment.duration_min} min
            </div>
          </div>

          {/* Treatment */}
          <div>
            <div className="text-[10px] font-semibold text-neutral-400 uppercase tracking-wider mb-1">
              Tratamiento
            </div>
            <div className="text-sm text-neutral-900">{appointment.treatment}</div>
            {appointment.dentist && (
              <div className="text-xs text-neutral-500 flex items-center gap-1 mt-0.5">
                <Stethoscope className="w-3 h-3" />
                {appointment.dentist}
              </div>
            )}
          </div>

          {/* Confirmation status */}
          <div>
            <div className="text-[10px] font-semibold text-neutral-400 uppercase tracking-wider mb-1">
              Confirmación del paciente
            </div>
            <div className="text-sm">
              {appointment.confirmation_received ? (
                <span className="text-emerald-700 flex items-center gap-1">
                  <Check className="w-3.5 h-3.5" />
                  Confirmada por el paciente
                </span>
              ) : (
                <span className="text-neutral-500">Pendiente de respuesta</span>
              )}
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Cancel reason input */}
          {showReason && (
            <div>
              <Label>Motivo de cancelación (opcional)</Label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Ej: Imprevisto del paciente"
                className="w-full px-3 py-2 text-sm bg-white border border-neutral-200 rounded-md placeholder:text-neutral-400 text-neutral-900 focus:outline-none focus:ring-2 focus:ring-neutral-900/10 focus:border-neutral-400 resize-none"
                rows={3}
              />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="px-5 py-4 border-t border-neutral-200 flex items-center gap-2">
          {isFinalState ? (
            <Button onClick={onClose} className="w-full">
              Cerrar
            </Button>
          ) : showReason ? (
            <>
              <Button
                onClick={() => {
                  setShowReason(false);
                  setReason('');
                }}
                disabled={busy !== null}
                className="flex-1"
              >
                Volver
              </Button>
              <Button
                variant="danger"
                onClick={handleCancel}
                disabled={busy !== null}
                className="flex-1"
              >
                {busy === 'cancel' ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Cancelando…
                  </>
                ) : (
                  'Confirmar cancelación'
                )}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="danger"
                onClick={() => setShowReason(true)}
                disabled={busy !== null}
                className="flex-1"
              >
                <XCircle className="w-3.5 h-3.5" />
                Cancelar cita
              </Button>
              <Button
                variant="primary"
                onClick={handleConfirm}
                disabled={busy !== null || appointment.confirmation_received}
                className="flex-1"
              >
                {busy === 'confirm' ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Confirmando…
                  </>
                ) : (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    Confirmar
                  </>
                )}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Clinic: Logs
// ─────────────────────────────────────────────────────────────

interface LogEvent {
  ts: string;
  clinic_id: string;
  type: string;
  level: string;
  phone: string | null;
  summary: string;
  extra: Record<string, unknown>;
}

function ClinicLogs({ token, clinicId }: { token: string; clinicId: string }) {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchData = useCallback(async () => {
    setRefreshing(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (typeFilter) params.set('type', typeFilter);
      const data = await api<{ events: LogEvent[] }>(
        `/api/logs/${clinicId}?${params.toString()}`,
        token
      );
      setEvents(data.events || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, clinicId, typeFilter]);

  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const i = setInterval(fetchData, 5000);
    return () => clearInterval(i);
  }, [fetchData, autoRefresh]);

  const typeIcon = (type: string) => {
    switch (type) {
      case 'message_in':
        return <ArrowLeft className="w-3.5 h-3.5 text-blue-600" />;
      case 'message_out':
        return <ChevronRight className="w-3.5 h-3.5 text-emerald-600" />;
      case 'takeover_on':
      case 'takeover_off':
        return <UserCheck className="w-3.5 h-3.5 text-amber-600" />;
      case 'error':
        return <AlertTriangle className="w-3.5 h-3.5 text-red-600" />;
      case 'action':
        return <Sparkles className="w-3.5 h-3.5 text-neutral-600" />;
      default:
        return <Info className="w-3.5 h-3.5 text-neutral-400" />;
    }
  };

  const typeLabel: Record<string, string> = {
    message_in: 'Entrada',
    message_out: 'Respuesta',
    takeover_on: 'Toma de control',
    takeover_off: 'Liberar control',
    error: 'Error',
    action: 'Acción',
  };

  const fmt = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString('es-ES', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  if (loading) return <Spinner className="h-64" />;

  return (
    <>
      <PageHeader
        title="Logs de actividad"
        description="Eventos recientes del agente — útil para debug y auditoría rápida."
        actions={
          <>
            <Button
              size="sm"
              variant={autoRefresh ? 'primary' : 'default'}
              onClick={() => setAutoRefresh((v) => !v)}
            >
              <Activity className={cn('w-3.5 h-3.5', autoRefresh && 'animate-pulse')} />
              {autoRefresh ? 'Live' : 'Pausado'}
            </Button>
            <Button onClick={fetchData} disabled={refreshing}>
              <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
              Actualizar
            </Button>
          </>
        }
      />

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <div className="flex items-center gap-1 text-xs text-neutral-500 mr-2">
          <Filter className="w-3.5 h-3.5" />
          Tipo:
        </div>
        {[
          ['', 'Todos'],
          ['message_in', 'Entradas'],
          ['message_out', 'Respuestas'],
          ['error', 'Errores'],
          ['action', 'Acciones'],
        ].map(([value, lab]) => (
          <button
            key={value || 'all'}
            onClick={() => setTypeFilter(value)}
            className={cn(
              'h-8 px-3 text-xs font-medium rounded-md border transition-colors',
              typeFilter === value
                ? 'bg-neutral-900 text-white border-neutral-900'
                : 'bg-white text-neutral-700 border-neutral-200 hover:bg-neutral-50'
            )}
          >
            {lab}
          </button>
        ))}
        <span className="text-xs text-neutral-500 tabular ml-auto">
          {events.length} {events.length === 1 ? 'evento' : 'eventos'}
        </span>
      </div>

      {events.length === 0 ? (
        <Card>
          <EmptyState
            icon={<ScrollText className="w-5 h-5" />}
            title="Sin eventos"
            description="Cuando lleguen mensajes a tu WhatsApp aparecerán aquí en tiempo real."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="divide-y divide-neutral-100">
            {events.map((e, i) => (
              <div
                key={i}
                className={cn(
                  'flex items-start gap-3 px-5 py-3 hover:bg-neutral-50/50 transition-colors',
                  e.level === 'error' && 'bg-red-50/30'
                )}
              >
                <div className="w-7 h-7 rounded-md bg-neutral-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                  {typeIcon(e.type)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-[11px] font-semibold text-neutral-700 uppercase tracking-wide">
                      {typeLabel[e.type] || e.type}
                    </span>
                    {e.phone && (
                      <span className="text-[11px] text-neutral-500 tabular font-mono">
                        {e.phone}
                      </span>
                    )}
                  </div>
                  <p
                    className={cn(
                      'text-sm break-words',
                      e.level === 'error' ? 'text-red-700' : 'text-neutral-700'
                    )}
                  >
                    {e.summary}
                  </p>
                </div>
                <span className="text-[11px] text-neutral-400 tabular flex-shrink-0">
                  {fmt(e.ts)}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// Create clinic modal
// ─────────────────────────────────────────────────────────────

function CreateClinicModal({
  token,
  onClose,
  onCreated,
}: {
  token: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({
    name: '',
    email: '',
    password: '',
    address: '',
    phone: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [step, setStep] = useState<'form' | 'success'>('form');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await api('/api/auth/users', token, {
        method: 'POST',
        body: JSON.stringify(form),
      });
      setStep('success');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al crear la clínica');
    } finally {
      setLoading(false);
    }
  };

  const handleDone = () => {
    onCreated();
  };

  return (
    <div
      className="fixed inset-0 bg-neutral-900/40 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg w-full max-w-md shadow-2xl border border-neutral-200"
        onClick={(e) => e.stopPropagation()}
      >
        {step === 'form' ? (
          <>
            <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-200">
              <div>
                <h2 className="text-sm font-semibold text-neutral-900">Nueva clínica</h2>
                <p className="text-xs text-neutral-500 mt-0.5">
                  Crea la clínica y su usuario administrador.
                </p>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 text-neutral-400 hover:text-neutral-900 rounded"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-5 space-y-4">
              {error && (
                <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <div>
                <Label>Nombre de la clínica</Label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Clínica Dental Madrid"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label>Email de acceso</Label>
                  <Input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm({ ...form, email: e.target.value })}
                    placeholder="clinica@email.com"
                    required
                  />
                </div>
                <div>
                  <Label>Contraseña</Label>
                  <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder="Mín. 8 caracteres"
                    required
                    minLength={8}
                  />
                </div>
              </div>

              <div>
                <Label>Dirección</Label>
                <Input
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  placeholder="Calle Gran Vía 45, Madrid"
                />
              </div>

              <div>
                <Label>Teléfono</Label>
                <Input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  placeholder="+34 91 234 56 78"
                />
              </div>

              {/* Hint sobre WhatsApp */}
              <div className="flex gap-2 p-3 bg-neutral-50 border border-neutral-200 rounded-md">
                <Sparkles className="w-3.5 h-3.5 text-neutral-500 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-neutral-600 leading-relaxed">
                  La conexión con WhatsApp Business se configura después
                  desde <strong>Configuración</strong> dentro del panel de la clínica.
                </p>
              </div>

              <div className="flex items-center gap-2 pt-2">
                <Button type="button" onClick={onClose} className="flex-1">
                  Cancelar
                </Button>
                <Button type="submit" variant="primary" disabled={loading} className="flex-1">
                  {loading ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Creando…
                    </>
                  ) : (
                    'Crear clínica'
                  )}
                </Button>
              </div>
            </form>
          </>
        ) : (
          // SUCCESS STEP
          <div className="p-6">
            <div className="text-center mb-6">
              <div className="inline-flex w-14 h-14 items-center justify-center rounded-full bg-emerald-50 border border-emerald-200 mb-4">
                <CheckCircle2 className="w-7 h-7 text-emerald-600" />
              </div>
              <h2 className="text-base font-semibold text-neutral-900">
                ¡Clínica creada!
              </h2>
              <p className="text-sm text-neutral-500 mt-1">
                <strong className="text-neutral-900">{form.name}</strong> está lista.
              </p>
            </div>

            <div className="space-y-3 mb-6">
              <div className="flex items-start gap-3 p-3 bg-neutral-50 rounded-md border border-neutral-200">
                <div className="w-6 h-6 rounded-full bg-neutral-900 text-white text-xs font-semibold flex items-center justify-center flex-shrink-0 mt-0.5">
                  1
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-neutral-900">Compartir credenciales</div>
                  <div className="text-xs text-neutral-500 mt-0.5">
                    Envía a la clínica el email <span className="font-mono text-neutral-700">{form.email}</span> y la contraseña que has elegido.
                  </div>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-neutral-50 rounded-md border border-neutral-200">
                <div className="w-6 h-6 rounded-full bg-neutral-900 text-white text-xs font-semibold flex items-center justify-center flex-shrink-0 mt-0.5">
                  2
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-neutral-900">Conectar WhatsApp Business</div>
                  <div className="text-xs text-neutral-500 mt-0.5">
                    Desde el panel de la clínica → Configuración → introducir API key de 360dialog.
                  </div>
                </div>
              </div>
              <div className="flex items-start gap-3 p-3 bg-neutral-50 rounded-md border border-neutral-200">
                <div className="w-6 h-6 rounded-full bg-neutral-900 text-white text-xs font-semibold flex items-center justify-center flex-shrink-0 mt-0.5">
                  3
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-neutral-900">Apuntar el webhook</div>
                  <div className="text-xs text-neutral-500 mt-0.5">
                    En el dashboard de 360dialog, configurar el webhook a la URL pública del agente.
                  </div>
                </div>
              </div>
            </div>

            <Button variant="primary" onClick={handleDone} className="w-full">
              Entendido
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Main shell
// ─────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const t = localStorage.getItem('dental_token');
    const u = localStorage.getItem('dental_user');
    if (t && u) {
      try {
        const parsed = JSON.parse(u) as AuthUser;
        setToken(t);
        setUser(parsed);
        setActiveTab(parsed.role === 'admin' ? 'overview' : 'dashboard');
      } catch {}
    }
    setHydrated(true);
  }, []);

  const handleLogin = (t: string, u: AuthUser) => {
    setToken(t);
    setUser(u);
    localStorage.setItem('dental_token', t);
    localStorage.setItem('dental_user', JSON.stringify(u));
    setActiveTab(u.role === 'admin' ? 'overview' : 'dashboard');
  };

  const handleLogout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('dental_token');
    localStorage.removeItem('dental_user');
  };

  if (!hydrated) return null;

  if (!token || !user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  const renderContent = () => {
    if (user.role === 'admin') {
      switch (activeTab) {
        case 'overview':
          return <AdminOverview token={token} />;
        case 'clinics':
          return <AdminClinics token={token} />;
        case 'users':
          return <AdminUsers token={token} />;
        default:
          return <AdminOverview token={token} />;
      }
    }
    const clinicId = user.clinic_id || 'clinic_001';
    switch (activeTab) {
      case 'dashboard':
        return <ClinicDashboard token={token} clinicId={clinicId} />;
      case 'conversations':
        return <ClinicConversations token={token} clinicId={clinicId} />;
      case 'appointments':
        return <ClinicAppointments token={token} clinicId={clinicId} />;
      case 'logs':
        return <ClinicLogs token={token} clinicId={clinicId} />;
      case 'settings':
        return <ClinicSettings token={token} clinicId={clinicId} />;
      default:
        return <ClinicDashboard token={token} clinicId={clinicId} />;
    }
  };

  return (
    <div className="min-h-screen bg-neutral-50 flex">
      <Sidebar
        user={user}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onLogout={handleLogout}
      />
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-8 py-10">{renderContent()}</div>
      </main>
    </div>
  );
}
