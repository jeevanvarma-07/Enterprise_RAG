import { useEffect, useState, useCallback, useRef } from 'react';
import api from './api';

/**
 * Backend health/readiness, polled for the connection indicator.
 *
 * Wraps `GET /api/health` (cheap — no model loading) so the UI can show at a
 * glance whether the backend is reachable, whether an LLM provider key is
 * configured, and how big the index is. The first-run nudges and the offline
 * banner in <App> are driven entirely off this.
 *
 * `status`:
 *   - 'connecting' — first probe in flight (no verdict yet)
 *   - 'online'     — last probe succeeded
 *   - 'offline'    — last probe failed (backend down / wrong port)
 */
export interface HealthData {
  status: string;
  version: string;
  mode: string;
  index_loaded: boolean;
  document_count: number;
  providers_configured: number;
  embedding: string;
}

export type HealthStatus = 'connecting' | 'online' | 'offline';

const POLL_MS = 15000;

export function useHealth() {
  const [status, setStatus] = useState<HealthStatus>('connecting');
  const [data, setData] = useState<HealthData | null>(null);
  // Keep the last good payload visible during a transient failure so the UI
  // doesn't flicker its counts to zero on a single dropped poll.
  const lastGood = useRef<HealthData | null>(null);

  const check = useCallback(async () => {
    try {
      const res = await api.get('/api/health', { timeout: 4000 });
      lastGood.current = res.data;
      setData(res.data);
      setStatus('online');
    } catch {
      setStatus('offline');
    }
  }, []);

  useEffect(() => {
    check();
    const id = setInterval(check, POLL_MS);
    // Re-probe immediately when the tab/window regains focus (user likely just
    // started or restarted the backend in a terminal).
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener('focus', onFocus);
    };
  }, [check]);

  return { status, data: data || lastGood.current, refresh: check };
}
