import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ShieldCheck, Gauge, Layers, Zap, KeyRound, Loader2, CheckCircle2, ArrowRight, Sparkles,
} from 'lucide-react';
import api from '../api';

/**
 * First-run welcome wizard.
 *
 * Shown once (gated on the `onboarded` setting) the first time the workspace
 * opens. Three quick steps: a privacy-first welcome, a performance mode pick
 * (pre-selected from detected hardware), and an optional API key (saved to the
 * encrypted in-app store). Completing it persists `onboarded: true` so it never
 * reappears. Everything here is optional — the user can skip straight through.
 */

interface SystemInfo {
  ram_gb: number | null;
  cpu_count: number | null;
  gpu: string | null;
  has_gpu: boolean;
  suggested_mode: string;
}

interface ProviderInfo {
  name: string;
  label: string;
  needs_key: boolean;
}

const MODES = [
  { id: 'lite', label: 'Lite', icon: Gauge, blurb: 'Fastest. Best for 8 GB / no-GPU machines.' },
  { id: 'balanced', label: 'Balanced', icon: Layers, blurb: 'Adds reranking for sharper answers.' },
  { id: 'power', label: 'Power', icon: Zap, blurb: 'Everything on. For 16 GB + GPU.' },
];

export default function FirstRunWizard({ open, onComplete }: { open: boolean; onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [keyStorageOk, setKeyStorageOk] = useState(true);
  const [mode, setMode] = useState('lite');
  const [provider, setProvider] = useState('groq');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [finishing, setFinishing] = useState(false);

  const load = useCallback(async () => {
    try {
      const sys = await api.get('/api/system');
      setSystem(sys.data);
      if (sys.data?.suggested_mode) setMode(sys.data.suggested_mode);
    } catch { /* hardware detect is best-effort */ }
    try {
      const p = await api.get('/api/providers');
      const list: ProviderInfo[] = (p.data.providers || []).filter((x: ProviderInfo) => x.needs_key);
      setProviders(list);
      setKeyStorageOk(p.data.key_storage_available !== false);
      if (list.length && !list.find(x => x.name === 'groq')) setProvider(list[0].name);
    } catch { /* backend offline — wizard still works, just can't save remotely */ }
  }, []);

  useEffect(() => { if (open) { setStep(0); load(); } }, [open, load]);

  const applyMode = async (m: string) => {
    setMode(m);
    try { await api.post('/api/settings', { mode: m }); } catch { /* persisted on finish anyway */ }
  };

  const saveKey = async () => {
    const value = apiKey.trim();
    if (!value) return false;
    setBusy(true);
    try {
      await api.post(`/api/providers/${provider}/key`, { api_key: value });
      return true;
    } catch {
      return false;
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    setFinishing(true);
    try {
      if (apiKey.trim()) await saveKey();
      await api.post('/api/settings', { mode, onboarded: true });
    } catch { /* even if persistence fails, don't trap the user on the wizard */ }
    finally {
      setFinishing(false);
      onComplete();
    }
  };

  if (!open) return null;

  const STEPS = 3;

  return createPortal(
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      >
        <motion.div
          className="w-full max-w-lg glass-panel rounded-2xl border border-white/10 overflow-hidden"
          initial={{ scale: 0.95, y: 12 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95, opacity: 0 }}
        >
          {/* Progress dots */}
          <div className="flex items-center gap-1.5 px-6 pt-5">
            {Array.from({ length: STEPS }).map((_, i) => (
              <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${i <= step ? 'bg-blue-500' : 'bg-slate-700'}`} />
            ))}
          </div>

          <div className="p-6">
            {/* ── Step 0: Welcome ───────────────────────────────── */}
            {step === 0 && (
              <div className="text-center">
                <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-blue-500/15 border border-blue-500/30 flex items-center justify-center">
                  <Sparkles className="w-7 h-7 text-blue-400" />
                </div>
                <h2 className="text-xl font-bold text-gradient mb-2">Welcome to Enterprise RAG</h2>
                <p className="text-sm text-slate-400 leading-relaxed">
                  Upload your documents and chat with them — answers are grounded only in your
                  content, with citations.
                </p>
                <div className="mt-4 flex items-start gap-2.5 text-left px-4 py-3 rounded-xl bg-slate-800/50 border border-white/5">
                  <ShieldCheck className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-slate-300 leading-relaxed">
                    <span className="font-semibold text-slate-200">Local-first &amp; private.</span> Your
                    documents, index, and chat history stay on this machine. Only your chosen LLM
                    request leaves your computer — or nothing at all in offline mode.
                  </p>
                </div>
              </div>
            )}

            {/* ── Step 1: Performance mode ──────────────────────── */}
            {step === 1 && (
              <div>
                <h2 className="text-lg font-bold text-slate-100 mb-1">Pick a performance mode</h2>
                <p className="text-xs text-slate-400 mb-4">
                  {system
                    ? <>Detected{system.ram_gb ? ` ${system.ram_gb} GB RAM` : ''}{system.cpu_count ? ` · ${system.cpu_count} cores` : ''}{system.gpu ? ` · ${system.gpu}` : ' · no GPU'}. We recommend <span className="text-blue-300 font-semibold capitalize">{system.suggested_mode}</span>.</>
                    : 'You can change this anytime in Settings.'}
                </p>
                <div className="space-y-2">
                  {MODES.map((m) => {
                    const Icon = m.icon;
                    const selected = mode === m.id;
                    const suggested = system?.suggested_mode === m.id;
                    return (
                      <button
                        key={m.id}
                        onClick={() => applyMode(m.id)}
                        className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-colors ${selected ? 'bg-blue-500/15 border-blue-500/50' : 'bg-slate-800/40 border-white/5 hover:border-white/15'}`}
                      >
                        <Icon className={`w-5 h-5 shrink-0 ${selected ? 'text-blue-400' : 'text-slate-400'}`} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-200">{m.label}</span>
                            {suggested && <span className="text-[9px] uppercase tracking-wide text-green-300 bg-green-500/10 border border-green-500/20 rounded px-1 py-0.5">Suggested</span>}
                          </div>
                          <p className="text-[11px] text-slate-500">{m.blurb}</p>
                        </div>
                        {selected && <CheckCircle2 className="w-4 h-4 text-blue-400 shrink-0" />}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Step 2: API key ───────────────────────────────── */}
            {step === 2 && (
              <div>
                <h2 className="text-lg font-bold text-slate-100 mb-1">Add an LLM key <span className="text-xs font-normal text-slate-500">(optional)</span></h2>
                <p className="text-xs text-slate-400 mb-4">
                  Paste a free API key to start chatting. It's encrypted and stored on this
                  machine only. You can skip this and add it later, or use a local model.
                </p>
                {keyStorageOk ? (
                  <div className="space-y-2">
                    <select
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                      className="w-full bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-blue-500/40"
                    >
                      {providers.map((p) => <option key={p.name} value={p.name}>{p.label}</option>)}
                    </select>
                    <div className="flex items-center gap-1.5">
                      <KeyRound className="w-4 h-4 text-slate-500 shrink-0" />
                      <input
                        type="password"
                        autoComplete="off"
                        value={apiKey}
                        placeholder="Paste API key (optional)"
                        onChange={(e) => setApiKey(e.target.value)}
                        className="flex-1 min-w-0 text-sm bg-slate-900/70 border border-white/10 rounded-lg px-3 py-2 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-blue-500/50"
                      />
                    </div>
                    <p className="text-[11px] text-slate-500">
                      No key? Groq and several providers offer free tiers. You can also run fully
                      offline with Ollama or a local model.
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-amber-300/90 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    Encrypted key storage isn't available in this build — set keys via environment
                    variables instead.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Footer nav */}
          <div className="flex items-center justify-between px-6 py-4 border-t border-white/5">
            <button
              onClick={finish}
              className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              Skip
            </button>
            <div className="flex items-center gap-2">
              {step > 0 && (
                <button
                  onClick={() => setStep(s => s - 1)}
                  className="text-sm px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 text-slate-300 hover:border-white/20 transition-colors"
                >
                  Back
                </button>
              )}
              {step < STEPS - 1 ? (
                <button
                  onClick={() => setStep(s => s + 1)}
                  className="text-sm px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white flex items-center gap-1.5 transition-colors"
                >
                  Next <ArrowRight className="w-3.5 h-3.5" />
                </button>
              ) : (
                <button
                  onClick={finish}
                  disabled={busy || finishing}
                  className="text-sm px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white flex items-center gap-1.5 transition-colors"
                >
                  {(busy || finishing) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Get started
                </button>
              )}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
}
