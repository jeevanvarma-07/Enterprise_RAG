import { useState, useEffect, useCallback } from 'react';
import { Trash2, Download, RefreshCw, Database, FileText, CheckSquare, Square, Search, ArrowUpDown, AlertTriangle, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api, { API_BASE_URL } from '../api';
import ConfirmDialog from './ConfirmDialog';

interface DocEntry {
    filename: string;
    chunks: number;
    timestamp: string;
}

export default function VectorStoreTab() {
    const [docs, setDocs] = useState<DocEntry[]>([]);
    const [loading, setLoading] = useState(false);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [deletingBatch, setDeletingBatch] = useState(false);
    const [deletingFile, setDeletingFile] = useState<string | null>(null);
    const [clearing, setClearing] = useState(false);
    const [search, setSearch] = useState('');
    const [sortBy, setSortBy] = useState<'chunks-desc' | 'chunks-asc' | 'date-desc' | 'date-asc'>('date-desc');
    const [error, setError] = useState<string | null>(null);
    // Pending destructive action awaiting in-app confirmation (replaces window.confirm).
    const [confirm, setConfirm] = useState<{ title: string; message: string; confirmLabel: string; onConfirm: () => void } | null>(null);

    const fetchDocs = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/index/documents');
            setDocs(res.data.documents);
            setSelected(new Set()); // reset selection on refresh
        } catch {
            setDocs([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchDocs(); }, [fetchDocs]);

    // ── Selection helpers ──
    const toggleOne = (filename: string) => {
        setSelected(prev => {
            const next = new Set(prev);
            next.has(filename) ? next.delete(filename) : next.add(filename);
            return next;
        });
    };

    const toggleAll = () => {
        if (selected.size === docs.length) {
            setSelected(new Set());
        } else {
            setSelected(new Set(docs.map(d => d.filename)));
        }
    };

    // ── Delete single ──
    const handleDeleteOne = async (filename: string) => {
        setDeletingFile(filename);
        try {
            await api.delete(`/api/index/documents/${encodeURIComponent(filename)}`);
            setDocs(prev => prev.filter(d => d.filename !== filename));
            setSelected(prev => { const n = new Set(prev); n.delete(filename); return n; });
        } catch {
            setError(`Failed to delete ${filename}.`);
        } finally {
            setDeletingFile(null);
        }
    };

    // ── Batch delete (confirm via in-app dialog) ──
    const performDeleteSelected = async () => {
        const toDelete = Array.from(selected);
        setDeletingBatch(true);
        try {
            await api.post('/api/index/documents/batch-delete', { filenames: toDelete });
            setDocs(prev => prev.filter(d => !selected.has(d.filename)));
            setSelected(new Set());
        } catch {
            setError('Batch delete failed. Check backend logs.');
        } finally {
            setDeletingBatch(false);
        }
    };

    const handleDeleteSelected = () => {
        if (selected.size === 0) return;
        setConfirm({
            title: 'Delete selected files',
            message: `Delete ${selected.size} selected file(s) from the index? This cannot be undone.`,
            confirmLabel: 'Delete',
            onConfirm: () => { setConfirm(null); performDeleteSelected(); },
        });
    };

    // ── Clear all (confirm via in-app dialog) ──
    const performClear = async () => {
        setClearing(true);
        try {
            await api.delete('/api/index/clear');
            setDocs([]);
            setSelected(new Set());
        } catch {
            setError('Failed to clear the index. Check backend logs.');
        } finally {
            setClearing(false);
        }
    };

    const handleClear = () => {
        setConfirm({
            title: 'Clear the entire index',
            message: 'This permanently removes every indexed document and cannot be undone.',
            confirmLabel: 'Clear all',
            onConfirm: () => { setConfirm(null); performClear(); },
        });
    };

    const handleDownload = () => { window.open(`${API_BASE_URL}/api/index/export`, '_blank'); };

    const totalChunks = docs.reduce((sum, d) => sum + d.chunks, 0);
    const allSelected = docs.length > 0 && selected.size === docs.length;
    const someSelected = selected.size > 0 && !allSelected;

    // Filtered + sorted derived list
    const filteredDocs = docs
        .filter(d => d.filename.toLowerCase().includes(search.toLowerCase()))
        .sort((a, b) => {
            if (sortBy === 'chunks-desc') return b.chunks - a.chunks;
            if (sortBy === 'chunks-asc') return a.chunks - b.chunks;
            if (sortBy === 'date-asc') return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
            return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(); // date-desc
        });

    return (
        <div className="flex flex-col h-full p-6 gap-5 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between shrink-0 flex-wrap gap-3">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-blue-500/20 rounded-lg border border-blue-500/20">
                        <Database className="w-4 h-4 text-blue-400" />
                    </div>
                    <div>
                        <h2 className="text-lg font-bold">Vector Store Management</h2>
                        <p className="text-xs text-slate-400">
                            {docs.length} file{docs.length !== 1 ? 's' : ''} · {totalChunks.toLocaleString()} total chunks
                        </p>
                    </div>
                </div>

                <div className="flex gap-2 flex-wrap">
                    {/* Delete selected */}
                    <AnimatePresence>
                        {selected.size > 0 && (
                            <motion.button
                                initial={{ opacity: 0, scale: 0.9 }}
                                animate={{ opacity: 1, scale: 1 }}
                                exit={{ opacity: 0, scale: 0.9 }}
                                onClick={handleDeleteSelected}
                                disabled={deletingBatch}
                                className="flex items-center gap-2 px-3 py-2 bg-red-500/20 text-red-300 border border-red-500/30 rounded-xl hover:bg-red-500/30 text-sm transition-all disabled:opacity-50"
                            >
                                {deletingBatch
                                    ? <RefreshCw className="w-4 h-4 animate-spin" />
                                    : <Trash2 className="w-4 h-4" />}
                                Delete {selected.size} selected
                            </motion.button>
                        )}
                    </AnimatePresence>

                    <button onClick={fetchDocs} disabled={loading} title="Refresh"
                        className="p-2 glass-button rounded-xl text-slate-400 hover:text-slate-200 transition-all">
                        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                    <button onClick={handleDownload} title="Download FAISS index"
                        className="flex items-center gap-2 px-3 py-2 glass-button rounded-xl text-slate-300 hover:text-white text-sm transition-all">
                        <Download className="w-4 h-4" />
                        <span className="hidden sm:inline">Export</span>
                    </button>
                    <button onClick={handleClear} disabled={clearing} title="Clear all"
                        className="flex items-center gap-2 px-3 py-2 bg-red-500/10 text-red-400 border border-red-500/20 rounded-xl hover:bg-red-500/20 text-sm transition-all">
                        <Trash2 className="w-4 h-4" />
                        <span className="hidden sm:inline">Clear All</span>
                    </button>
                </div>
            </div>

            {/* Inline error banner (replaces blocking alert()) */}
            <AnimatePresence>
                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                        className="flex items-center gap-2 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-sm shrink-0"
                    >
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                        <span className="flex-1">{error}</span>
                        <button onClick={() => setError(null)} className="p-1 rounded-lg hover:bg-red-500/20 transition-colors" title="Dismiss">
                            <X className="w-3.5 h-3.5" />
                        </button>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Search + Sort bar */}
            <div className="flex items-center gap-3 shrink-0">
                <div className="flex-1 flex items-center gap-2 bg-slate-800/60 border border-slate-700 rounded-xl px-3 py-2">
                    <Search className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                    <input
                        type="text" value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Search by filename..."
                        className="bg-transparent text-sm text-slate-200 placeholder:text-slate-500 outline-none w-full"
                    />
                </div>
                <div className="flex items-center gap-1.5 bg-slate-800/60 border border-slate-700 rounded-xl px-2 py-1">
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                    <select value={sortBy} onChange={e => setSortBy(e.target.value as typeof sortBy)}
                        className="bg-transparent text-xs text-slate-300 outline-none">
                        <option value="date-desc">Newest first</option>
                        <option value="date-asc">Oldest first</option>
                        <option value="chunks-desc">Most chunks</option>
                        <option value="chunks-asc">Fewest chunks</option>
                    </select>
                </div>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-auto rounded-xl border border-white/5 bg-slate-900/40">
                {loading ? (
                    <div className="flex items-center justify-center h-full text-slate-400 gap-2">
                        <RefreshCw className="w-4 h-4 animate-spin" /> Loading...
                    </div>
                ) : docs.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center p-8 gap-3">
                        <Database className="w-12 h-12 text-slate-600" />
                        <p className="text-slate-400 font-medium">No documents indexed yet.</p>
                        <p className="text-sm text-slate-500">Go to Chat Sessions and upload files to populate the vector store.</p>
                    </div>
                ) : (
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="text-left border-b border-white/5 text-xs text-slate-400 uppercase tracking-wider">
                                {/* Select-all checkbox */}
                                <th className="px-4 py-3 w-10">
                                    <button onClick={toggleAll} className="text-slate-400 hover:text-blue-400 transition-colors">
                                        {allSelected
                                            ? <CheckSquare className="w-4 h-4 text-blue-400" />
                                            : someSelected
                                                ? <CheckSquare className="w-4 h-4 text-blue-400/50" />
                                                : <Square className="w-4 h-4" />}
                                    </button>
                                </th>
                                <th className="px-4 py-3 font-medium">File</th>
                                <th className="px-4 py-3 font-medium text-right">Chunks</th>
                                <th className="px-4 py-3 font-medium hidden md:table-cell">Indexed At</th>
                                <th className="px-4 py-3 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <AnimatePresence>
                                {filteredDocs.map((doc, i) => {
                                    const isSelected = selected.has(doc.filename);
                                    return (
                                        <motion.tr
                                            key={doc.filename}
                                            initial={{ opacity: 0, x: -10 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            exit={{ opacity: 0, x: 10 }}
                                            transition={{ delay: i * 0.02 }}
                                            className={`border-b border-white/5 transition-colors cursor-pointer
                        ${isSelected ? 'bg-blue-500/5 border-blue-500/10' : 'hover:bg-white/[0.02]'}`}
                                            onClick={() => toggleOne(doc.filename)}
                                        >
                                            <td className="px-4 py-3 w-10">
                                                <div className="text-slate-400">
                                                    {isSelected
                                                        ? <CheckSquare className="w-4 h-4 text-blue-400" />
                                                        : <Square className="w-4 h-4" />}
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-2">
                                                    <FileText className="w-4 h-4 text-blue-400/70 shrink-0" />
                                                    <span className="text-slate-200 font-medium truncate max-w-[180px]" title={doc.filename}>
                                                        {doc.filename}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-right">
                                                <span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-300 text-xs font-mono border border-blue-500/20">
                                                    {doc.chunks.toLocaleString()}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">
                                                {new Date(doc.timestamp).toLocaleString()}
                                            </td>
                                            <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                                                <button
                                                    onClick={() => handleDeleteOne(doc.filename)}
                                                    disabled={deletingFile === doc.filename || deletingBatch}
                                                    className="p-1.5 text-slate-500 hover:text-red-400 transition-colors rounded-lg hover:bg-red-500/10 disabled:opacity-50"
                                                    title={`Delete ${doc.filename}`}
                                                >
                                                    {deletingFile === doc.filename
                                                        ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                                        : <Trash2 className="w-3.5 h-3.5" />}
                                                </button>
                                            </td>
                                        </motion.tr>
                                    );
                                })}
                            </AnimatePresence>
                        </tbody>
                    </table>
                )}
            </div>

            <AnimatePresence>
                {confirm && (
                    <ConfirmDialog
                        open
                        title={confirm.title}
                        message={confirm.message}
                        confirmLabel={confirm.confirmLabel}
                        danger
                        onConfirm={confirm.onConfirm}
                        onCancel={() => setConfirm(null)}
                    />
                )}
            </AnimatePresence>
        </div>
    );
}
