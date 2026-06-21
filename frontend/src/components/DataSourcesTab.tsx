import { useState, useEffect, useCallback } from 'react';
import { Globe, HardDrive, FileText, FileSpreadsheet, Image, File, RefreshCw, Plus, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '../api';

interface SourceFile {
    filename: string;
    size_bytes: number;
    type: string;
    modified: number;
}

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(ts: number): string {
    return new Date(ts * 1000).toLocaleDateString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
    });
}

function FileIcon({ type }: { type: string }) {
    const cls = "w-4 h-4 shrink-0";
    if (type === 'pdf') return <FileText className={`${cls} text-red-400`} />;
    if (['xls', 'xlsx', 'csv'].includes(type)) return <FileSpreadsheet className={`${cls} text-green-400`} />;
    if (['png', 'jpg', 'jpeg', 'bmp', 'tiff', 'webp'].includes(type)) return <Image className={`${cls} text-purple-400`} />;
    if (type === 'txt') return <FileText className={`${cls} text-blue-400`} />;
    return <File className={`${cls} text-slate-400`} />;
}

export default function DataSourcesTab() {
    const [files, setFiles] = useState<SourceFile[]>([]);
    const [totalBytes, setTotalBytes] = useState(0);
    const [loading, setLoading] = useState(false);

    // URL scraping state
    const [url, setUrl] = useState('');
    const [scraping, setScraping] = useState(false);
    const [scrapeStatus, setScrapeStatus] = useState<'idle' | 'success' | 'error'>('idle');
    const [scrapeMsg, setScrapeMsg] = useState('');

    const fetchSources = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/sources');
            setFiles(res.data.files || []);
            setTotalBytes(res.data.total_bytes || 0);
        } catch {
            setFiles([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchSources(); }, [fetchSources]);

    const handleScrape = async () => {
        if (!url.trim()) return;
        setScraping(true);
        setScrapeStatus('idle');
        setScrapeMsg('Fetching and indexing URL...');
        try {
            const res = await api.post('/api/sources/scrape', { url: url.trim() });
            setScrapeStatus('success');
            setScrapeMsg(`✓ Indexed ${res.data.chunks} chunks from ${res.data.source}`);
            setUrl('');
            fetchSources();
        } catch (err: any) {
            setScrapeStatus('error');
            setScrapeMsg(err?.response?.data?.detail || 'Failed to scrape URL.');
        } finally {
            setScraping(false);
        }
    };

    // Group by file type
    const typeCounts: Record<string, number> = {};
    files.forEach(f => { typeCounts[f.type] = (typeCounts[f.type] || 0) + 1; });

    return (
        <div className="flex-1 flex flex-col h-full overflow-hidden p-6 gap-5">

            {/* ── Header ── */}
            <div className="flex items-center justify-between shrink-0">
                <div>
                    <h2 className="text-lg font-bold text-slate-100">Data Sources</h2>
                    <p className="text-xs text-slate-400 mt-0.5">Manage where your knowledge base data comes from</p>
                </div>
                <button onClick={fetchSources} className="text-slate-500 hover:text-slate-300 transition-colors p-2 rounded-lg hover:bg-slate-800">
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* ── Stats Row ── */}
            <div className="grid grid-cols-3 gap-3 shrink-0">
                <div className="glass-panel rounded-xl p-4 flex items-center gap-3">
                    <div className="p-2 bg-blue-500/20 rounded-lg"><HardDrive className="w-4 h-4 text-blue-400" /></div>
                    <div>
                        <p className="text-[10px] text-slate-400 uppercase tracking-wide">Storage Used</p>
                        <p className="text-base font-bold text-slate-100">{formatBytes(totalBytes)}</p>
                    </div>
                </div>
                <div className="glass-panel rounded-xl p-4 flex items-center gap-3">
                    <div className="p-2 bg-purple-500/20 rounded-lg"><FileText className="w-4 h-4 text-purple-400" /></div>
                    <div>
                        <p className="text-[10px] text-slate-400 uppercase tracking-wide">Total Files</p>
                        <p className="text-base font-bold text-slate-100">{files.length}</p>
                    </div>
                </div>
                <div className="glass-panel rounded-xl p-4 flex items-center gap-3">
                    <div className="p-2 bg-green-500/20 rounded-lg"><Globe className="w-4 h-4 text-green-400" /></div>
                    <div>
                        <p className="text-[10px] text-slate-400 uppercase tracking-wide">File Types</p>
                        <p className="text-base font-bold text-slate-100">{Object.keys(typeCounts).length}</p>
                    </div>
                </div>
            </div>

            {/* ── URL Scraper ── */}
            <div className="glass-panel rounded-xl p-4 shrink-0">
                <div className="flex items-center gap-2 mb-3">
                    <Globe className="w-4 h-4 text-green-400" />
                    <h3 className="text-sm font-semibold text-slate-200">Index from URL</h3>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-green-500/10 border border-green-500/20 text-green-300">NEW</span>
                </div>
                <p className="text-xs text-slate-400 mb-3">Paste any public webpage URL — the system will scrape, extract text, and index it into your knowledge base automatically.</p>
                <div className="flex gap-2">
                    <input
                        type="url"
                        value={url}
                        onChange={e => { setUrl(e.target.value); setScrapeStatus('idle'); }}
                        onKeyDown={e => e.key === 'Enter' && handleScrape()}
                        placeholder="https://en.wikipedia.org/wiki/Artificial_intelligence"
                        className="flex-1 bg-slate-800/80 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder:text-slate-500 outline-none focus:ring-2 focus:ring-green-500/40 focus:border-green-500/50 transition-all"
                    />
                    <button
                        onClick={handleScrape}
                        disabled={scraping || !url.trim()}
                        className="px-4 py-2.5 bg-green-600/70 hover:bg-green-500/80 border border-green-500/30 text-white text-sm font-medium rounded-xl flex items-center gap-2 disabled:opacity-50 transition-all"
                    >
                        {scraping ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                        {scraping ? 'Indexing...' : 'Index URL'}
                    </button>
                </div>
                <AnimatePresence>
                    {scrapeMsg && (
                        <motion.p
                            initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                            className={`text-xs mt-2 flex items-center gap-1.5 ${scrapeStatus === 'success' ? 'text-green-400' : scrapeStatus === 'error' ? 'text-red-400' : 'text-slate-400'}`}
                        >
                            {scrapeStatus === 'success' && <CheckCircle className="w-3 h-3" />}
                            {scrapeStatus === 'error' && <AlertCircle className="w-3 h-3" />}
                            {scrapeMsg}
                        </motion.p>
                    )}
                </AnimatePresence>
            </div>

            {/* ── File Browser ── */}
            <div className="glass-panel rounded-xl flex flex-col overflow-hidden flex-1 min-h-0">
                <div className="px-4 py-3 border-b border-white/5 shrink-0 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-200">Uploaded Files</h3>
                    <div className="flex gap-2">
                        {Object.entries(typeCounts).map(([t, n]) => (
                            <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700 text-slate-300 font-mono">
                                .{t} ({n})
                            </span>
                        ))}
                    </div>
                </div>

                {/* Table header */}
                <div className="grid grid-cols-[2fr_1fr_1fr_1fr] px-4 py-2 text-[10px] text-slate-500 uppercase tracking-wide border-b border-white/5 shrink-0">
                    <span>File Name</span>
                    <span>Type</span>
                    <span>Size</span>
                    <span>Uploaded</span>
                </div>

                {/* Rows */}
                <div className="flex-1 overflow-y-auto min-h-0">
                    {loading ? (
                        <div className="flex items-center justify-center h-32 text-slate-500 text-sm gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" /> Loading files...
                        </div>
                    ) : files.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-32 text-center">
                            <HardDrive className="w-8 h-8 text-slate-700 mb-2" />
                            <p className="text-xs text-slate-500">No files uploaded yet.<br />Go to Chat Sessions to upload files.</p>
                        </div>
                    ) : (
                        files.map((f, i) => (
                            <motion.div
                                key={f.filename}
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                transition={{ delay: i * 0.02 }}
                                className="grid grid-cols-[2fr_1fr_1fr_1fr] px-4 py-3 border-b border-white/5 hover:bg-slate-800/40 transition-colors items-center"
                            >
                                <div className="flex items-center gap-2 min-w-0">
                                    <FileIcon type={f.type} />
                                    <span className="text-xs text-slate-300 truncate font-medium" title={f.filename}>{f.filename}</span>
                                </div>
                                <span className="text-xs text-slate-400 font-mono uppercase">.{f.type}</span>
                                <span className="text-xs text-slate-400">{formatBytes(f.size_bytes)}</span>
                                <span className="text-xs text-slate-400">{formatDate(f.modified)}</span>
                            </motion.div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}
