import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Upload, KeyRound, MessageSquare, ShieldCheck, Gauge, FileText, ExternalLink,
} from 'lucide-react';

/**
 * In-app help / about panel.
 *
 * A lightweight reference reachable from the header: how to get started, what
 * the privacy model is, and what each performance mode does. Pairs with the
 * first-run wizard for users who dismissed it or want a refresher.
 */

interface Step {
  icon: typeof Upload;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  {
    icon: Upload,
    title: '1 · Add your documents',
    body: 'Use the Ingest panel to upload PDFs, Excel/CSV, text, images, or a URL. They\'re indexed locally into a searchable knowledge base.',
  },
  {
    icon: KeyRound,
    title: '2 · Connect a model',
    body: 'Open Settings → LLM Providers and paste a free API key (e.g. Groq), or point at a local Ollama / offline model. Keys are encrypted on this machine.',
  },
  {
    icon: MessageSquare,
    title: '3 · Chat with your data',
    body: 'Ask questions in plain language. Answers are grounded only in your documents, with clickable source citations you can open to see the exact passage.',
  },
];

const MODES = [
  { name: 'Lite', body: 'Fastest, lowest memory. Great for 8 GB / no-GPU machines. Dense + keyword search, no reranking.' },
  { name: 'Balanced', body: 'Adds cross-encoder reranking for sharper, better-ordered results.' },
  { name: 'Power', body: 'Everything on, for 16 GB + GPU. Best quality, heaviest.' },
];

export default function HelpModal({ open, onClose, version }: { open: boolean; onClose: () => void; version?: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/75 backdrop-blur-sm p-4"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="w-full max-w-lg max-h-[85vh] flex flex-col glass-panel rounded-2xl border border-white/10 overflow-hidden"
          initial={{ scale: 0.96, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.96, opacity: 0 }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/10 bg-slate-900/60 shrink-0">
            <h2 className="text-base font-bold text-gradient">Help &amp; About</h2>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-700/60 text-slate-400 hover:text-slate-200 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="overflow-y-auto p-5 space-y-5">
            {/* Getting started */}
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2.5">Getting started</h3>
              <div className="space-y-2.5">
                {STEPS.map((s) => {
                  const Icon = s.icon;
                  return (
                    <div key={s.title} className="flex items-start gap-3 px-3 py-2.5 rounded-xl bg-slate-800/40 border border-white/5">
                      <div className="w-8 h-8 rounded-lg bg-blue-500/15 border border-blue-500/30 flex items-center justify-center shrink-0">
                        <Icon className="w-4 h-4 text-blue-400" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-slate-200">{s.title}</p>
                        <p className="text-xs text-slate-400 leading-relaxed">{s.body}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Privacy */}
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2.5">Privacy</h3>
              <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-xl bg-green-500/5 border border-green-500/15">
                <ShieldCheck className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
                <p className="text-xs text-slate-300 leading-relaxed">
                  Your documents, search index, and chat history stay on this machine. The only
                  thing that leaves your computer is the prompt sent to your chosen cloud LLM — and
                  in offline mode (Ollama / local model) nothing leaves at all.
                </p>
              </div>
            </section>

            {/* Performance modes */}
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2.5 flex items-center gap-1.5">
                <Gauge className="w-3.5 h-3.5" /> Performance modes
              </h3>
              <div className="space-y-1.5">
                {MODES.map((m) => (
                  <div key={m.name} className="px-3 py-2 rounded-lg bg-slate-800/40 border border-white/5">
                    <p className="text-xs"><span className="font-semibold text-slate-200">{m.name}</span>
                      <span className="text-slate-400"> — {m.body}</span></p>
                  </div>
                ))}
              </div>
              <p className="text-[11px] text-slate-500 mt-2">Change anytime in Settings → Performance.</p>
            </section>

            {/* Links / about */}
            <section className="pt-1 border-t border-white/5">
              <div className="flex items-center justify-between pt-3">
                <a
                  href="https://github.com/jeevanvarma-07/Enterprise_RAG"
                  target="_blank" rel="noreferrer"
                  className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1.5 transition-colors"
                >
                  <FileText className="w-3.5 h-3.5" /> Project &amp; docs <ExternalLink className="w-3 h-3" />
                </a>
                <span className="text-[11px] text-slate-600 font-mono">
                  Enterprise RAG{version ? ` v${version}` : ''}
                </span>
              </div>
            </section>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
}
