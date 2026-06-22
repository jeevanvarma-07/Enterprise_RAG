import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Gauge, Layers, Zap, Cpu, CheckCircle2, AlertTriangle, KeyRound, Database, RefreshCw, Loader2, MemoryStick, ScanText, Wand2 } from 'lucide-react';
import api from '../api';

interface Settings {
  mode: string;
  rerank: string;
  ocr?: string;
  active_provider?: string;
  active_model?: string;
  embedding_backend?: string;
  embedding_model?: string;
  rerank_enabled?: boolean;
  rerank_available?: boolean;
  top_k?: number;
  fetch_k?: number;
  mmr_lambda?: number;
  bm25_k?: number;
  final_k?: number;
  rerank_candidates?: number;
  // Prompt-size budget (caps each request to stay under a provider's TPM limit).
  history_turns?: number;
  context_chars?: number;
}

// Tunable knobs (ranges mirror the server-side clamps in config.py).
type TuneKey =
  | 'top_k' | 'fetch_k' | 'mmr_lambda' | 'bm25_k' | 'final_k' | 'rerank_candidates'
  | 'history_turns' | 'context_chars';
const TUNERS: { key: TuneKey; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: 'top_k', label: 'Dense hits (k)', min: 1, max: 20, step: 1, hint: 'MMR results kept per query variation.' },
  { key: 'fetch_k', label: 'MMR pool (fetch_k)', min: 1, max: 80, step: 1, hint: 'Candidates weighed before diversity pruning.' },
  { key: 'mmr_lambda', label: 'Diversity ↔ Relevance (λ)', min: 0, max: 1, step: 0.05, hint: '0 = most diverse, 1 = most relevant.' },
  { key: 'bm25_k', label: 'Keyword hits (BM25)', min: 0, max: 20, step: 1, hint: '0 disables sparse search (dense only).' },
  { key: 'final_k', label: 'Chunks sent to LLM', min: 1, max: 20, step: 1, hint: 'Final context chunks per answer.' },
  { key: 'rerank_candidates', label: 'Rerank candidates', min: 1, max: 50, step: 1, hint: 'Fused chunks fed to the reranker.' },
];
// Request-size budget — the knobs that keep a request under the provider's
// tokens-per-minute limit (Groq free tier = 6,000 TPM → the 413 error).
const PROMPT_TUNERS: { key: TuneKey; label: string; min: number; max: number; step: number; hint: string }[] = [
  { key: 'history_turns', label: 'Chat history sent', min: 0, max: 20, step: 1, hint: 'Prior Q&A turns re-sent each message. Lower = smaller requests. 0 = none.' },
  { key: 'context_chars', label: 'Context size (chars)', min: 500, max: 60000, step: 500, hint: 'Max retrieved text per request. ~4 chars ≈ 1 token. Lower to avoid rate limits.' },
];
const TUNE_DEFAULTS: Record<TuneKey, number> = {
  top_k: 5, fetch_k: 20, mmr_lambda: 0.6, bm25_k: 8, final_k: 6, rerank_candidates: 12,
  history_turns: 3, context_chars: 6000,
};

// Embedding backends. `sentence-transformers` is the default (accurate, but pulls
// in torch ~2 GB); `fastembed` is the torch-free ONNX path for Lite installs.
// Same all-MiniLM-L6-v2 model, same 384-dim space — switching still needs a rebuild.
const EMBEDDING_BACKENDS = [
  { id: 'sentence-transformers', label: 'Accurate', hint: 'Default. PyTorch-based.' },
  { id: 'fastembed', label: 'Light (ONNX)', hint: 'No torch — best for Lite.' },
];

interface ProviderInfo {
  name: string;
  label: string;
  type: string;
  configured: boolean;
  needs_key: boolean;
  has_stored_key?: boolean;
  model_count: number;
}

// Detected hardware + the profile the backend recommends for it.
interface SystemInfo {
  ram_gb: number | null;
  cpu_count: number | null;
  gpu: string | null;
  has_gpu: boolean;
  suggested_mode: string;
  current_mode: string;
}

const MODES = [
  {
    id: 'lite',
    label: 'Lite',
    icon: Gauge,
    blurb: 'Fastest. For 8 GB / no-GPU machines. Hybrid search on, reranking off.',
  },
  {
    id: 'balanced',
    label: 'Balanced',
    icon: Layers,
    blurb: 'Adds cross-encoder reranking for sharper answers. Good default on capable PCs.',
  },
  {
    id: 'power',
    label: 'Power',
    icon: Zap,
    blurb: 'Everything on. For 16 GB + GPU machines. Heaviest, highest quality.',
  },
];

/**
 * Settings dialog: performance mode (Lite/Balanced/Power), reranking control,
 * and a read-only provider configuration overview. Persists to /api/settings.
 * Rendered in a portal so it overlays the whole app.
 */
export default function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [saving, setSaving] = useState(false);
  // Encrypted in-app API-key store: per-provider draft input + which provider
  // is mid-save, plus whether the backend even supports encrypted storage.
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});
  const [keyBusy, setKeyBusy] = useState<string | null>(null);
  const [keyStorageOk, setKeyStorageOk] = useState(true);
  // Live slider positions while dragging; cleared per-key once committed so the
  // value falls back to the (refetched, clamped) server setting.
  const [draft, setDraft] = useState<Partial<Record<TuneKey, number>>>({});
  const [tuneOpen, setTuneOpen] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildMsg, setRebuildMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.get('/api/settings'), api.get('/api/providers')]);
      setSettings(s.data);
      setProviders(p.data.providers || []);
      setKeyStorageOk(p.data.key_storage_available !== false);
    } catch {
      /* backend offline — modal shows nothing actionable */
    }
    // Hardware detection is best-effort and independent — never block settings.
    try {
      const sys = await api.get('/api/system');
      setSystem(sys.data);
    } catch {
      setSystem(null);
    }
  }, []);

  useEffect(() => { if (open) load(); }, [open, load]);

  // Persist a partial settings change, then refetch resolved flags.
  const patch = async (values: Partial<Settings>) => {
    setSettings(prev => (prev ? { ...prev, ...values } : prev)); // optimistic
    setSaving(true);
    try {
      await api.post('/api/settings', values);
      const s = await api.get('/api/settings');
      setSettings(s.data);
    } catch {
      /* keep optimistic value; backend will reconcile on next open */
    } finally {
      setSaving(false);
    }
  };

  // Save a provider's API key into the encrypted in-app store, then refresh the
  // provider list so its "Configured" state reflects the new key.
  const saveKey = async (name: string) => {
    const value = (keyDrafts[name] || '').trim();
    if (!value) return;
    setKeyBusy(name);
    try {
      await api.post(`/api/providers/${name}/key`, { api_key: value });
      setKeyDrafts(prev => { const next = { ...prev }; delete next[name]; return next; });
      await load();
    } catch {
      /* leave the draft so the user can retry */
    } finally {
      setKeyBusy(null);
    }
  };

  // Remove a provider's stored key from the encrypted store.
  const clearKey = async (name: string) => {
    setKeyBusy(name);
    try {
      await api.delete(`/api/providers/${name}/key`);
      await load();
    } catch {
      /* no-op */
    } finally {
      setKeyBusy(null);
    }
  };

  // Commit a single tuning knob: persist it, then drop the local draft so the
  // slider tracks the server's clamped value again.
  const commitTune = async (key: TuneKey, value: number) => {
    await patch({ [key]: value } as Partial<Settings>);
    setDraft(prev => { const next = { ...prev }; delete next[key]; return next; });
  };

  const tuneValue = (key: TuneKey): number =>
    draft[key] ?? (settings?.[key] as number | undefined) ?? TUNE_DEFAULTS[key];

  const resetTuning = () => { setDraft({}); patch(TUNE_DEFAULTS as Partial<Settings>); };

  // Re-embed every indexed chunk with the active backend. Required after switching
  // embeddings (vectors from different models aren't comparable). Chunk text and
  // citations are preserved server-side; only the vectors are recomputed.
  const rebuildIndex = async () => {
    setRebuilding(true);
    setRebuildMsg(null);
    try {
      const r = await api.post('/api/index/rebuild');
      setRebuildMsg(r.data?.message || 'Index rebuilt.');
      await load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setRebuildMsg(detail || 'Rebuild failed — see backend logs.');
    } finally {
      setRebuilding(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.96, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.96, opacity: 0 }}
          onClick={(e) => e.stopPropagation()}
          className="glass-panel rounded-2xl w-full max-w-lg max-h-[85vh] overflow-y-auto border border-white/10 shadow-2xl"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 sticky top-0 bg-slate-900/80 backdrop-blur-md z-10">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-indigo-400" />
              <h2 className="font-semibold text-slate-200 text-sm">Settings</h2>
              {saving && <span className="text-[10px] text-slate-500 animate-pulse">saving…</span>}
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-700/60 text-slate-400 hover:text-slate-200 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-5 space-y-6">
            {/* Performance mode */}
            <section>
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">Performance Mode</h3>

              {/* Detected hardware + suggested profile */}
              {system && (
                <div className="mb-3 px-3 py-2.5 rounded-xl bg-slate-800/40 border border-white/5">
                  <div className="flex items-center gap-3 text-[11px] text-slate-400 flex-wrap">
                    <span className="flex items-center gap-1.5">
                      <MemoryStick className="w-3 h-3 text-slate-500" />
                      {system.ram_gb != null ? `${system.ram_gb} GB RAM` : 'RAM unknown'}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Cpu className="w-3 h-3 text-slate-500" />
                      {system.cpu_count ? `${system.cpu_count} cores` : 'CPU unknown'}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Zap className={`w-3 h-3 ${system.has_gpu ? 'text-green-400' : 'text-slate-600'}`} />
                      {system.gpu || 'No GPU detected'}
                    </span>
                  </div>
                  {settings && settings.mode !== system.suggested_mode && (
                    <button
                      onClick={() => patch({ mode: system.suggested_mode })}
                      className="mt-2 w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-medium border border-blue-500/30 bg-blue-500/10 text-blue-200 hover:bg-blue-500/20 transition-colors"
                    >
                      <Wand2 className="w-3 h-3" />
                      Apply suggested: <span className="capitalize font-semibold">{system.suggested_mode}</span>
                    </button>
                  )}
                  {settings && settings.mode === system.suggested_mode && (
                    <p className="mt-2 flex items-center gap-1.5 text-[11px] text-green-300">
                      <CheckCircle2 className="w-3 h-3" /> Using the recommended profile for this machine.
                    </p>
                  )}
                </div>
              )}

              <div className="space-y-2">
                {MODES.map((m) => {
                  const active = settings?.mode === m.id;
                  const suggested = system?.suggested_mode === m.id;
                  const Icon = m.icon;
                  return (
                    <button
                      key={m.id}
                      onClick={() => patch({ mode: m.id })}
                      className={`w-full text-left flex items-start gap-3 p-3 rounded-xl border transition-colors ${
                        active ? 'bg-blue-500/15 border-blue-500/40' : 'bg-slate-800/40 border-white/5 hover:bg-slate-800/80'
                      }`}
                    >
                      <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${active ? 'text-blue-300' : 'text-slate-500'}`} />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-medium ${active ? 'text-blue-200' : 'text-slate-300'}`}>{m.label}</span>
                          {active && <CheckCircle2 className="w-3.5 h-3.5 text-blue-400" />}
                          {suggested && !active && (
                            <span className="text-[9px] font-semibold uppercase tracking-wide text-blue-300/80 bg-blue-500/10 border border-blue-500/20 rounded px-1 py-0.5">Suggested</span>
                          )}
                        </div>
                        <p className="text-[11px] text-slate-500 leading-snug mt-0.5">{m.blurb}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>

            {/* Reranking */}
            <section>
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">Reranking</h3>
              <div className="flex gap-2 mb-2">
                {['auto', 'on', 'off'].map((opt) => {
                  const active = (settings?.rerank || 'auto') === opt;
                  return (
                    <button
                      key={opt}
                      onClick={() => patch({ rerank: opt })}
                      className={`flex-1 py-2 rounded-lg text-xs font-medium capitalize border transition-colors ${
                        active ? 'bg-blue-500/15 border-blue-500/40 text-blue-200' : 'bg-slate-800/40 border-white/5 text-slate-400 hover:bg-slate-800/80'
                      }`}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-slate-500 leading-snug">
                A cross-encoder re-scores retrieved chunks for sharper relevance. <span className="text-slate-400">Auto</span> turns it on for Balanced/Power.
              </p>
              {/* Effective / availability status */}
              <div className="mt-2 flex flex-col gap-1">
                <div className="flex items-center gap-1.5 text-[11px]">
                  {settings?.rerank_enabled
                    ? <><CheckCircle2 className="w-3 h-3 text-green-400" /><span className="text-green-300">Active for this mode</span></>
                    : <><span className="w-3 h-3 rounded-full border border-slate-600 inline-block" /><span className="text-slate-500">Inactive for this mode</span></>}
                </div>
                {settings && settings.rerank_available === false && (
                  <div className="flex items-center gap-1.5 text-[11px] text-amber-400/90">
                    <AlertTriangle className="w-3 h-3" />
                    <span>Reranker package not installed — falls back to fusion order.</span>
                  </div>
                )}
              </div>
            </section>

            {/* OCR (scanned PDFs / images) */}
            <section>
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <ScanText className="w-3.5 h-3.5 text-slate-400" /> Document OCR
              </h3>
              <div className="flex gap-2 mb-2">
                {['auto', 'on', 'off'].map((opt) => {
                  const active = (settings?.ocr || 'auto') === opt;
                  return (
                    <button
                      key={opt}
                      onClick={() => patch({ ocr: opt })}
                      className={`flex-1 py-2 rounded-lg text-xs font-medium capitalize border transition-colors ${
                        active ? 'bg-blue-500/15 border-blue-500/40 text-blue-200' : 'bg-slate-800/40 border-white/5 text-slate-400 hover:bg-slate-800/80'
                      }`}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-slate-500 leading-snug">
                Reads text from scanned PDFs and images via Tesseract — heavy on RAM/CPU.
                <span className="text-slate-400"> Auto</span> keeps it off on Lite, on for Balanced/Power.
              </p>
            </section>

            {/* Request size / token budget — caps each LLM request so a long
                chat or big index can't blow past a provider's TPM limit. */}
            <section>
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                <Gauge className="w-3.5 h-3.5 text-slate-400" /> Request Size
              </h3>
              <p className="text-[11px] text-slate-500 leading-snug mb-3">
                Smaller requests avoid the <span className="text-amber-300">“Request too large” (413)</span> rate-limit
                error on free tiers like Groq (6,000 tokens/min). Lower these if you hit it.
              </p>
              <div className="space-y-3.5">
                {PROMPT_TUNERS.map((t) => {
                  const val = tuneValue(t.key);
                  return (
                    <div key={t.key}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-slate-300">{t.label}</span>
                        <span className="text-[11px] font-mono text-blue-300 bg-slate-800 rounded px-1.5 py-0.5">
                          {t.key === 'history_turns' && val === 0 ? 'off' : val}
                        </span>
                      </div>
                      <input
                        type="range"
                        min={t.min} max={t.max} step={t.step} value={val}
                        onChange={(e) => setDraft(prev => ({ ...prev, [t.key]: Number(e.target.value) }))}
                        onPointerUp={(e) => commitTune(t.key, Number((e.target as HTMLInputElement).value))}
                        onKeyUp={(e) => commitTune(t.key, Number((e.target as HTMLInputElement).value))}
                        className="w-full accent-blue-500 cursor-pointer"
                      />
                      <p className="text-[10px] text-slate-500 leading-snug mt-0.5">{t.hint}</p>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Retrieval tuning (advanced) */}
            <section>
              <button
                onClick={() => setTuneOpen(o => !o)}
                className="w-full flex items-center justify-between mb-3"
              >
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Retrieval Tuning</h3>
                <span className="text-[10px] text-slate-500">{tuneOpen ? 'Hide' : 'Advanced'}</span>
              </button>
              <AnimatePresence initial={false}>
                {tuneOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="space-y-3.5">
                      {TUNERS.map((t) => {
                        const val = tuneValue(t.key);
                        return (
                          <div key={t.key}>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-xs text-slate-300">{t.label}</span>
                              <span className="text-[11px] font-mono text-blue-300 bg-slate-800 rounded px-1.5 py-0.5">
                                {t.step < 1 ? val.toFixed(2) : val}
                              </span>
                            </div>
                            <input
                              type="range"
                              min={t.min} max={t.max} step={t.step} value={val}
                              onChange={(e) => setDraft(prev => ({ ...prev, [t.key]: Number(e.target.value) }))}
                              onPointerUp={(e) => commitTune(t.key, Number((e.target as HTMLInputElement).value))}
                              onKeyUp={(e) => commitTune(t.key, Number((e.target as HTMLInputElement).value))}
                              className="w-full accent-blue-500 cursor-pointer"
                            />
                            <p className="text-[10px] text-slate-500 leading-snug mt-0.5">{t.hint}</p>
                          </div>
                        );
                      })}
                    </div>
                    <button
                      onClick={resetTuning}
                      className="mt-3 text-[11px] text-slate-400 hover:text-blue-300 underline-offset-2 hover:underline transition-colors"
                    >
                      Reset to defaults
                    </button>
                    <p className="text-[10px] text-slate-500 leading-snug mt-2">
                      Affects retrieval immediately — no re-indexing needed. Higher values improve recall but cost more time/tokens.
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </section>

            {/* Embeddings */}
            <section>
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5 text-slate-400" /> Embeddings
              </h3>
              <div className="flex gap-2 mb-2">
                {EMBEDDING_BACKENDS.map((b) => {
                  const active = (settings?.embedding_backend || 'sentence-transformers') === b.id;
                  return (
                    <button
                      key={b.id}
                      onClick={() => patch({ embedding_backend: b.id })}
                      className={`flex-1 py-2 px-2 rounded-lg text-xs font-medium border transition-colors ${
                        active ? 'bg-blue-500/15 border-blue-500/40 text-blue-200' : 'bg-slate-800/40 border-white/5 text-slate-400 hover:bg-slate-800/80'
                      }`}
                    >
                      <span className="block">{b.label}</span>
                      <span className="block text-[10px] font-normal text-slate-500 mt-0.5">{b.hint}</span>
                    </button>
                  );
                })}
              </div>
              <button
                onClick={rebuildIndex}
                disabled={rebuilding}
                className="w-full mt-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium border border-white/10 bg-slate-800/40 text-slate-300 hover:bg-slate-800/80 disabled:opacity-60 disabled:cursor-wait transition-colors"
              >
                {rebuilding
                  ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Re-embedding all chunks…</>
                  : <><RefreshCw className="w-3.5 h-3.5" /> Rebuild index</>}
              </button>
              {rebuildMsg && (
                <p className="text-[11px] text-slate-400 leading-snug mt-2">{rebuildMsg}</p>
              )}
              <p className="text-[11px] text-slate-500 leading-snug mt-2">
                After switching backend you must <span className="text-slate-400">rebuild</span> — vectors from different
                models aren't comparable. Re-embeds every chunk; text &amp; citations are preserved.
              </p>
            </section>

            {/* Providers + API keys */}
            <section>
              <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">LLM Providers</h3>
              <div className="space-y-1.5">
                {providers.map((p) => (
                  <div key={p.name} className="px-3 py-2 rounded-lg bg-slate-800/40 border border-white/5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs text-slate-300 truncate">{p.label}</span>
                        <span className="text-[10px] text-slate-600 font-mono shrink-0">{p.model_count} model{p.model_count !== 1 ? 's' : ''}</span>
                      </div>
                      {p.configured ? (
                        <span className="flex items-center gap-1 text-[10px] text-green-300 shrink-0">
                          <CheckCircle2 className="w-3 h-3" /> {p.needs_key ? (p.has_stored_key ? 'Key saved' : 'Configured') : (p.type === 'ollama' ? 'Running' : 'Local')}
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-[10px] text-slate-500 shrink-0">
                          {p.needs_key
                            ? <><KeyRound className="w-3 h-3" /> Needs key</>
                            : <><span className="w-2 h-2 rounded-full bg-slate-600 inline-block" /> {p.type === 'ollama' ? 'Not running' : 'Unavailable'}</>}
                        </span>
                      )}
                    </div>

                    {/* Ollama: free local models, no key. Show how to connect it. */}
                    {p.type === 'ollama' && (
                      <div className="mt-2 text-[11px] leading-snug">
                        {p.configured ? (
                          <p className="text-green-300/90 flex items-center gap-1.5">
                            <CheckCircle2 className="w-3 h-3 shrink-0" />
                            {p.model_count} local model{p.model_count !== 1 ? 's' : ''} detected — pick one in the model menu (top bar). No rate limits.
                          </p>
                        ) : (
                          <div className="text-slate-500 space-y-1">
                            <p>Run unlimited models locally, fully offline — no API key, no token limits.</p>
                            <ol className="list-decimal list-inside space-y-0.5 text-slate-400">
                              <li>Install from <span className="text-blue-300">ollama.com</span></li>
                              <li>Run <code className="bg-slate-900/70 px-1 rounded text-[10px]">ollama pull llama3.2</code> in a terminal</li>
                              <li>Click <span className="text-slate-300">Refresh</span> below — the model appears in the menu</li>
                            </ol>
                            <button
                              onClick={load}
                              className="mt-1 inline-flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-slate-700/60 hover:bg-slate-700 text-slate-300"
                            >
                              <RefreshCw className="w-3 h-3" /> Refresh
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Key entry — only for providers that take an API key */}
                    {p.needs_key && keyStorageOk && (
                      <div className="flex items-center gap-1.5 mt-2">
                        <input
                          type="password"
                          autoComplete="off"
                          value={keyDrafts[p.name] ?? ''}
                          placeholder={p.has_stored_key ? '•••••••• saved — paste to replace' : `Paste ${p.label} API key`}
                          onChange={(e) => setKeyDrafts(prev => ({ ...prev, [p.name]: e.target.value }))}
                          onKeyDown={(e) => { if (e.key === 'Enter') saveKey(p.name); }}
                          className="flex-1 min-w-0 text-[11px] bg-slate-900/70 border border-white/10 rounded px-2 py-1 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500/50"
                        />
                        <button
                          onClick={() => saveKey(p.name)}
                          disabled={!((keyDrafts[p.name] || '').trim()) || keyBusy === p.name}
                          className="text-[10px] px-2 py-1 rounded bg-blue-600/80 hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed text-white shrink-0 flex items-center gap-1"
                        >
                          {keyBusy === p.name ? <Loader2 className="w-3 h-3 animate-spin" /> : null} Save
                        </button>
                        {p.has_stored_key && (
                          <button
                            onClick={() => clearKey(p.name)}
                            disabled={keyBusy === p.name}
                            title="Remove stored key"
                            className="text-[10px] px-1.5 py-1 rounded bg-slate-700/60 hover:bg-slate-700 text-slate-300 shrink-0"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-slate-500 leading-snug mt-2">
                {keyStorageOk
                  ? 'Keys are encrypted and stored on this machine only — never in the project or a plaintext file.'
                  : 'Encrypted key storage is unavailable; set keys via environment variables instead.'}
              </p>
            </section>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
}
