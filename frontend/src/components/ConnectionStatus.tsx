import { Wifi, WifiOff, Loader2, RefreshCw } from 'lucide-react';
import type { HealthData, HealthStatus } from '../useHealth';

/**
 * Compact backend-connection pill for the app header.
 *
 * Replaces the old always-green dot (which lied when the backend was down) with
 * a real verdict from `GET /api/health`, plus a hover tooltip summarising mode,
 * index size, providers, and version. Clicking re-probes immediately.
 */
export default function ConnectionStatus({
  status,
  data,
  onRefresh,
}: {
  status: HealthStatus;
  data: HealthData | null;
  onRefresh: () => void;
}) {
  const styles: Record<HealthStatus, string> = {
    connecting: 'bg-slate-800 border-slate-700 text-slate-400',
    online: 'bg-green-500/10 border-green-500/30 text-green-300',
    offline: 'bg-red-500/10 border-red-500/30 text-red-300',
  };
  const label = { connecting: 'Connecting…', online: 'Connected', offline: 'Offline' }[status];

  return (
    <div className="relative group">
      <button
        onClick={onRefresh}
        title="Backend connection — click to re-check"
        className={`text-[11px] px-3 py-1.5 flex items-center gap-1.5 rounded-full border font-medium transition-colors ${styles[status]}`}
      >
        {status === 'connecting' ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : status === 'online' ? (
          <Wifi className="w-3 h-3" />
        ) : (
          <WifiOff className="w-3 h-3" />
        )}
        {label}
        <RefreshCw className="w-2.5 h-2.5 opacity-0 group-hover:opacity-60 transition-opacity" />
      </button>

      {/* Hover tooltip — one-glance backend summary */}
      <div className="absolute right-0 top-full mt-2 w-56 p-3 rounded-xl bg-slate-900 border border-white/10 shadow-2xl text-[11px] text-slate-300 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 pointer-events-none">
        {status === 'offline' ? (
          <p className="text-slate-400 leading-relaxed">
            Can't reach the backend. Start it with{' '}
            <code className="text-blue-300 bg-slate-800 px-1 rounded">uvicorn main:app --port 8000</code>{' '}
            then click to retry.
          </p>
        ) : data ? (
          <div className="space-y-1.5">
            <Row k="Mode" v={data.mode} />
            <Row k="Documents" v={`${data.document_count.toLocaleString()} chunks`} />
            <Row k="Providers" v={data.providers_configured > 0 ? `${data.providers_configured} configured` : 'none — add a key'} />
            <Row k="Embedding" v={data.embedding} />
            <Row k="Version" v={`v${data.version}`} />
          </div>
        ) : (
          <p className="text-slate-500">Checking backend…</p>
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-500">{k}</span>
      <span className="text-slate-300 font-medium truncate text-right">{v}</span>
    </div>
  );
}
