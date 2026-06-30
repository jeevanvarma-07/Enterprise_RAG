import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';

/**
 * In-app confirmation dialog — replaces the native `window.confirm`, which
 * breaks the app's visual language and isn't styleable. Portal-rendered, closes
 * on Escape or backdrop click, and focuses the confirm button on open so the
 * keyboard flow works.
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    confirmRef.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onCancel}
      className="fixed inset-0 z-[120] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
    >
      <motion.div
        initial={{ scale: 0.96, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.96, y: 10 }}
        onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="confirm-title"
        className="glass-panel w-full max-w-md rounded-2xl border border-white/10 shadow-2xl overflow-hidden"
      >
        <div className="flex items-start gap-3 px-5 py-4">
          <div className={`p-2 rounded-lg shrink-0 border ${danger
            ? 'bg-red-500/15 border-red-500/25 text-red-400'
            : 'bg-blue-500/15 border-blue-500/25 text-blue-400'}`}>
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3 id="confirm-title" className="text-sm font-semibold text-slate-100">{title}</h3>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-white/10 bg-slate-900/40">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-lg text-slate-300 hover:bg-slate-700/60 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors border ${danger
              ? 'bg-red-500/20 text-red-300 border-red-500/30 hover:bg-red-500/30'
              : 'bg-blue-500/20 text-blue-300 border-blue-500/30 hover:bg-blue-500/30'}`}
          >
            {confirmLabel}
          </button>
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  );
}
