'use client';

import { useState, useEffect } from 'react';
import { 
  CalendarCheck, Clock, XCircle, AlertTriangle, 
  MessageCircle, User, Phone, ArrowRight, RefreshCw,
  Hand, Bot
} from 'lucide-react';

// Types
interface ClinicStats {
  clinic_id: string;
  clinic_name: string;
  date: string;
  total_appointments: number;
  confirmed: number;
  pending: number;
  cancelled: number;
  no_shows: number;
}

interface Conversation {
  phone: string;
  name: string;
  last_appointment: string;
  status: string;
  human_takeover: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const CLINIC_ID = process.env.NEXT_PUBLIC_CLINIC_ID || 'clinic_001';

export default function DashboardPage() {
  const [stats, setStats] = useState<ClinicStats | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = async () => {
    try {
      const [statsRes, convRes] = await Promise.all([
        fetch(`${API_BASE}/api/stats/${CLINIC_ID}`),
        fetch(`${API_BASE}/api/conversations/${CLINIC_ID}`),
      ]);

      if (!statsRes.ok || !convRes.ok) {
        throw new Error('Error cargando datos');
      }

      const statsData = await statsRes.json();
      const convData = await convRes.json();

      setStats(statsData);
      setConversations(convData.conversations || []);
      setError(null);
    } catch (e) {
      setError('No se pudo conectar con el servidor');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
    // Auto-refresh cada 10 segundos
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleTakeover = async (phone: string) => {
    try {
      const res = await fetch(
        `${API_BASE}/api/conversations/${CLINIC_ID}/${phone}/takeover`,
        { method: 'POST' }
      );
      if (res.ok) {
        setConversations(prev =>
          prev.map(c => c.phone === phone ? { ...c, human_takeover: true } : c)
        );
      }
    } catch (e) {
      console.error('Error taking over:', e);
    }
  };

  const handleRelease = async (phone: string) => {
    try {
      const res = await fetch(
        `${API_BASE}/api/conversations/${CLINIC_ID}/${phone}/release`,
        { method: 'POST' }
      );
      if (res.ok) {
        setConversations(prev =>
          prev.map(c => c.phone === phone ? { ...c, human_takeover: false } : c)
        );
      }
    } catch (e) {
      console.error('Error releasing:', e);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <AlertTriangle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <p className="text-gray-600 dark:text-gray-400">{error}</p>
          <button
            onClick={handleRefresh}
            className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  return (
    <main className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            {stats?.clinic_name || 'Dashboard'}
          </h1>
          <p className="text-gray-500 dark:text-gray-400">
            {new Date().toLocaleDateString('es-ES', {
              weekday: 'long',
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="p-2 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
        >
          <RefreshCw className={`h-5 w-5 ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        <StatCard
          icon={<CalendarCheck className="h-5 w-5" />}
          label="Total citas"
          value={stats?.total_appointments || 0}
          color="blue"
        />
        <StatCard
          icon={<CalendarCheck className="h-5 w-5" />}
          label="Confirmadas"
          value={stats?.confirmed || 0}
          color="green"
        />
        <StatCard
          icon={<Clock className="h-5 w-5" />}
          label="Pendientes"
          value={stats?.pending || 0}
          color="yellow"
        />
        <StatCard
          icon={<XCircle className="h-5 w-5" />}
          label="Canceladas"
          value={stats?.cancelled || 0}
          color="red"
        />
        <StatCard
          icon={<AlertTriangle className="h-5 w-5" />}
          label="No-shows"
          value={stats?.no_shows || 0}
          color="gray"
        />
      </div>

      {/* Conversations */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <MessageCircle className="h-5 w-5 text-blue-600" />
            Conversaciones activas
          </h2>
        </div>

        {conversations.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            No hay conversaciones recientes
          </div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            {conversations.map((conv) => (
              <div
                key={conv.phone}
                className="p-4 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className="h-10 w-10 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center">
                    <User className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">
                      {conv.name}
                    </p>
                    <p className="text-sm text-gray-500 flex items-center gap-1">
                      <Phone className="h-3 w-3" />
                      {conv.phone}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  <span
                    className={`px-2 py-1 text-xs rounded-full ${
                      conv.status === 'confirmed'
                        ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                        : conv.status === 'cancelled'
                        ? 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300'
                        : 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300'
                    }`}
                  >
                    {conv.status}
                  </span>

                  {conv.human_takeover ? (
                    <button
                      onClick={() => handleRelease(conv.phone)}
                      className="flex items-center gap-1 px-3 py-1.5 text-sm bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300 rounded-lg hover:bg-green-200 dark:hover:bg-green-800 transition-colors"
                    >
                      <Bot className="h-4 w-4" />
                      Devolver al agente
                    </button>
                  ) : (
                    <button
                      onClick={() => handleTakeover(conv.phone)}
                      className="flex items-center gap-1 px-3 py-1.5 text-sm bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 rounded-lg hover:bg-blue-200 dark:hover:bg-blue-800 transition-colors"
                    >
                      <Hand className="h-4 w-4" />
                      Tomar control
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="mt-8 text-center text-sm text-gray-500">
        Actualización automática cada 10 segundos
      </div>
    </main>
  );
}

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  color: 'blue' | 'green' | 'yellow' | 'red' | 'gray';
}) {
  const colors = {
    blue: 'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400',
    green: 'bg-green-100 text-green-600 dark:bg-green-900 dark:text-green-400',
    yellow: 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900 dark:text-yellow-400',
    red: 'bg-red-100 text-red-600 dark:bg-red-900 dark:text-red-400',
    gray: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-200 dark:border-gray-700">
      <div className={`inline-flex p-2 rounded-lg ${colors[color]} mb-2`}>
        {icon}
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
    </div>
  );
}
