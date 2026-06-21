import React, { useState } from 'react';
import { Upload, FileText, CheckCircle, AlertCircle, Loader2, Terminal } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '../api';

const PROCESSING_STEPS = [
    { icon: '📂', label: 'Reading file & detecting type' },
    { icon: '🔍', label: 'Parsing text / Running OCR' },
    { icon: '✂️', label: 'Chunking text (1000 chars, 150 overlap)' },
    { icon: '🔢', label: 'Generating vector embeddings' },
    { icon: '💾', label: 'Storing chunks in FAISS index' },
];

export default function UploadSection({ onUploadSuccess }: { onUploadSuccess?: () => void }) {
    const [files, setFiles] = useState<File[]>([]);
    const [uploading, setUploading] = useState(false);
    const [status, setStatus] = useState<'idle' | 'success' | 'error'>('idle');
    const [progress, setProgress] = useState<{ processed: number; total: number } | null>(null);
    const [statusMsg, setStatusMsg] = useState('');
    const [stepIndex, setStepIndex] = useState(-1);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            setFiles(Array.from(e.target.files));
            setStatus('idle');
            setStatusMsg('');
        }
    };

    const handleUpload = async () => {
        if (!files.length) return;
        setUploading(true);
        setStatus('idle');
        setStepIndex(0);
        setProgress({ processed: 0, total: files.length });
        setStatusMsg(`Uploading ${files.length} file(s)...`);

        // For very large batches, split into chunks of 50 to avoid payload limits
        const BATCH_SIZE = 50;
        let totalProcessed = 0;
        // Tally per-file outcomes across all batches so we can report honestly
        // (the backend returns {status: 'ok' | 'empty' | 'error'} per file).
        let okCount = 0, emptyCount = 0;
        const failed: { file: string; detail?: string }[] = [];

        try {
            for (let i = 0; i < files.length; i += BATCH_SIZE) {
                const batch = files.slice(i, i + BATCH_SIZE);
                const formData = new FormData();
                batch.forEach(f => formData.append('files', f));

                const batchNum = Math.floor(i / BATCH_SIZE) + 1;
                const totalBatches = Math.ceil(files.length / BATCH_SIZE);
                setStatusMsg(`Processing batch ${batchNum}/${totalBatches}...`);

                // Animate through processing steps while uploading
                for (let s = 0; s < PROCESSING_STEPS.length; s++) {
                    setStepIndex(s);
                    await new Promise(r => setTimeout(r, 300));
                }
                const result = await api.post('/api/upload', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                });
                const rows: { file: string; status: string; detail?: string }[] = result.data?.results || [];
                for (const r of rows) {
                    if (r.status === 'ok') okCount++;
                    else if (r.status === 'empty') emptyCount++;
                    else failed.push({ file: r.file, detail: r.detail });
                }
                totalProcessed += batch.length;
                setProgress({ processed: totalProcessed, total: files.length });
            }

            // Decide the verdict from real per-file outcomes, not just "no exception".
            if (okCount === 0 && (emptyCount > 0 || failed.length > 0)) {
                setStatus('error');
            } else {
                setStatus('success');
            }
            const parts = [`✓ ${okCount} indexed`];
            if (emptyCount) parts.push(`${emptyCount} had no extractable text`);
            if (failed.length) parts.push(`${failed.length} failed`);
            let msg = parts.join(' · ');
            if (failed.length) {
                const first = failed[0];
                msg += ` — e.g. ${first.file}${first.detail ? `: ${first.detail.slice(0, 80)}` : ''}`;
            }
            setStatusMsg(msg);
            setFiles([]);
            onUploadSuccess?.();   // notify parent to refresh Knowledge Base panel
        } catch (err) {
            console.error(err);
            setStatus('error');
            // Surface the actual reason where we can (connection vs server error).
            const detail = (err as { response?: { data?: { detail?: string } }; message?: string })
                ?.response?.data?.detail
                || (err as { message?: string })?.message;
            setStatusMsg(detail ? `Upload failed: ${detail}` : 'Upload failed — is the backend running?');
        } finally {
            setUploading(false);
            setProgress(null);
            setTimeout(() => setStepIndex(-1), 2000);
        }
    };

    const progressPct = progress ? Math.round((progress.processed / progress.total) * 100) : 0;

    return (
        <div className="glass-panel p-5 rounded-2xl flex flex-col gap-4 shadow-xl shrink-0">
            <div className="flex justify-between items-center px-1">
                <h3 className="font-semibold text-slate-200 text-sm">Ingest Knowledge</h3>
                {status === 'success' && <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}><CheckCircle className="text-green-400 w-5 h-5" /></motion.div>}
                {status === 'error' && <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}><AlertCircle className="text-red-400 w-5 h-5" /></motion.div>}
                {uploading && <Loader2 className="text-blue-400 w-5 h-5 animate-spin" />}
            </div>

            {/* Drop zone */}
            <div className="border-2 border-dashed border-slate-600 hover:border-blue-500/50 rounded-xl p-6 flex flex-col items-center justify-center text-center transition-colors relative bg-slate-800/30 group">
                <input
                    type="file"
                    multiple
                    onChange={handleFileChange}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                    accept=".pdf,.txt,.csv,.xlsx,.xls,.png,.jpg,.jpeg"
                    disabled={uploading}
                />
                <div className="w-12 h-12 rounded-full bg-slate-800/80 group-hover:bg-blue-500/10 flex items-center justify-center mb-3 transition-colors border border-slate-700 group-hover:border-blue-500/30">
                    <Upload className="text-blue-400 w-5 h-5" />
                </div>
                <p className="text-sm font-medium text-slate-300">Drag & Drop files or Browse</p>
                <p className="text-xs text-slate-500 mt-1">PDF, TXT, Excel, Images — up to 300+ files</p>
            </div>

            {/* Progress bar */}
            <AnimatePresence>
                {uploading && progress && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                        <div className="flex justify-between items-center mb-1">
                            <span className="text-xs text-slate-400">{statusMsg}</span>
                            <span className="text-xs font-bold text-blue-400">{progressPct}%</span>
                        </div>
                        <div className="w-full bg-slate-700/60 rounded-full h-1.5 overflow-hidden">
                            <motion.div
                                className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full"
                                initial={{ width: 0 }}
                                animate={{ width: `${progressPct}%` }}
                                transition={{ duration: 0.3 }}
                            />
                        </div>
                        <p className="text-xs text-slate-500 mt-1">{progress.processed}/{progress.total} files processed</p>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Processing Console */}
            <AnimatePresence>
                {uploading && stepIndex >= 0 && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
                        className="rounded-xl bg-slate-900/80 border border-slate-700 p-3 overflow-hidden">
                        <div className="flex items-center gap-1.5 mb-2">
                            <Terminal className="w-3 h-3 text-green-400" />
                            <span className="text-[10px] text-green-400 font-mono font-bold">Processing Console</span>
                        </div>
                        <div className="space-y-1.5">
                            {PROCESSING_STEPS.map((step, i) => {
                                const done = i < stepIndex;
                                const active = i === stepIndex;
                                return (
                                    <motion.div key={step.label} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                                        className={`flex items-center gap-2 text-[11px] font-mono transition-colors
                                            ${done ? 'text-green-400' : active ? 'text-blue-300' : 'text-slate-600'}`}>
                                        <span className="shrink-0 w-3 text-center">
                                            {done ? '✓' : active ? <Loader2 className="w-3 h-3 animate-spin inline" /> : '○'}
                                        </span>
                                        <span>{step.icon} {step.label}</span>
                                    </motion.div>
                                );
                            })}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* File list */}
            <AnimatePresence>
                {files.length > 0 && !uploading && (
                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} className="flex flex-col gap-2 overflow-hidden">
                        <div className="max-h-36 overflow-y-auto space-y-1 pr-1">
                            {files.slice(0, 8).map((f, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs bg-slate-800/60 p-2.5 rounded-lg border border-slate-700/50">
                                    <FileText className="w-4 h-4 text-blue-400/80 shrink-0" />
                                    <span className="truncate flex-1 text-slate-300 font-medium">{f.name}</span>
                                    <span className="text-[10px] text-slate-500 shrink-0">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                                </div>
                            ))}
                            {files.length > 8 && (
                                <p className="text-xs text-slate-400 text-center py-1 font-medium">+{files.length - 8} more files selected</p>
                            )}
                        </div>
                        <button
                            onClick={handleUpload}
                            disabled={uploading}
                            className="mt-2 w-full glass-button bg-blue-600/50 hover:bg-blue-500/60 text-white border-blue-500/30 font-medium py-2.5 rounded-xl text-sm disabled:opacity-50 shadow-lg shadow-blue-500/10 transition-all active:scale-[0.98]"
                        >
                            {`Upload ${files.length} file${files.length > 1 ? 's' : ''} to Vector Store`}
                        </button>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Status message after upload */}
            {!uploading && statusMsg && (
                <p className={`text-xs text-center font-medium ${status === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                    {statusMsg}
                </p>
            )}
        </div>
    );
}
