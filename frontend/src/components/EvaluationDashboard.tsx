import { useState, useEffect, useCallback } from 'react';
import {
    BarChart3, RefreshCw, AlertTriangle, Play, Target, Sparkles,
    Coins, Clock, ListChecks,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '../api';

/**
 * Evaluation Dashboard — the answer-QUALITY view (RAGAS metrics) that complements
 * the token/latency telemetry already collected per chat.
 *
 * Four hand-rolled, Lite-safe metrics (see backend/services/evaluation.py):
 *   faithfulness · answer relevancy · context precision · context recall
 * scored 0..1 by the configured LLM judge + local embeddings. Charts are
 * hand-rolled bar gauges — the app ships zero chart dependencies on purpose to
 * keep the Lite bundle small.
 */

interface EvalSummary {
    runs: number;
    avg_faithfulness: number | null;
    avg_answer_relevancy: number | null;
    avg_context_precision: number | null;
    avg_context_recall: number | null;
}

interface MetricsSummary {
    requests: number;
    avg_tokens: number;
    avg_total_ms: number;
}

interface EvalResult {
    id?: number;
    question: string;
    faithfulness: number | null;
    answer_relevancy: number | null;
    context_precision: number | null;
    context_recall: number | null;
    eval_provider?: string | null;
    eval_tokens?: number;
    eval_latency_ms?: number;
    answer?: string;
}

const METRICS: { key: keyof EvalResult; label: string; help: string }[] = [
    { key: 'faithfulness', label: 'Faithfulness', help: 'Answer claims grounded in the retrieved context' },
    { key: 'answer_relevancy', label: 'Answer Relevancy', help: 'Answer actually addresses the question' },
    { key: 'context_precision', label: 'Context Precision', help: 'Retrieved chunks are on-topic & well-ranked' },
    { key: 'context_recall', label: 'Context Recall', help: 'Retrieval covers the reference answer (needs ground truth)' },
];

// 0..1 → color band. Red < 0.5 < amber < 0.8 < green.
function bandColor(v: number | null): string {
    if (v == null) return 'bg-slate-600';
    if (v >= 0.8) return 'bg-emerald-500';
    if (v >= 0.5) return 'bg-amber-500';
    return 'bg-red-500';
}
function bandText(v: number | null): string {
    if (v == null) return 'text-slate-500';
    if (v >= 0.8) return 'text-emerald-400';
    if (v >= 0.5) return 'text-amber-400';
    return 'text-red-400';
}
function pct(v: number | null | undefined): string {
    return v == null ? '—' : `${Math.round(v * 100)}%`;
}

/** A labelled 0..1 horizontal bar gauge. */
function Gauge({ label, value, help }: { label: string; value: number | null; help?: string }) {
    return (
        <div className="space-y-1.5">
            <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-300" title={help}>{label}</span>
                <span className={`text-xs font-mono font-semibold ${bandText(value)}`}>{pct(value)}</span>
            </div>
            <div className="h-2 rounded-full bg-slate-700/60 overflow-hidden">
                <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: value == null ? '0%' : `${Math.max(2, value * 100)}%` }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                    className={`h-full rounded-full ${bandColor(value)}`}
                />
            </div>
        </div>
    );
}

export default function EvaluationDashboard() {
    const [summary, setSummary] = useState<EvalSummary | null>(null);
    const [telemetry, setTelemetry] = useState<MetricsSummary | null>(null);
    const [recent, setRecent] = useState<EvalResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Single-answer run panel
    const [question, setQuestion] = useState('');
    const [groundTruth, setGroundTruth] = useState('');
    const [running, setRunning] = useState(false);
    const [lastResult, setLastResult] = useState<EvalResult | null>(null);

    // Dataset run
    const [datasetRunning, setDatasetRunning] = useState(false);
    const [datasetAggregate, setDatasetAggregate] = useState<Record<string, number | null> | null>(null);

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [s, m, r] = await Promise.all([
                api.get('/api/eval/summary'),
                api.get('/api/metrics/summary'),
                api.get('/api/eval/recent?limit=25'),
            ]);
            setSummary(s.data);
            setTelemetry(m.data);
            setRecent(r.data.runs || []);
        } catch {
            setError('Failed to load evaluation data. Is the backend running?');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { refresh(); }, [refresh]);

    const runSingle = async () => {
        if (!question.trim() || running) return;
        setRunning(true);
        setError(null);
        try {
            const res = await api.post('/api/eval/run', {
                question: question.trim(),
                ground_truth: groundTruth.trim() || undefined,
            });
            setLastResult(res.data);
            refresh();
        } catch (e: unknown) {
            const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            setError(detail || 'Evaluation failed. Check that a document is indexed and a provider key is set.');
        } finally {
            setRunning(false);
        }
    };

    const runExampleDataset = async () => {
        if (datasetRunning) return;
        setDatasetRunning(true);
        setError(null);
        setDatasetAggregate(null);
        try {
            // The bundled example lives in the backend repo; the dashboard ships its
            // own copy of the questions so a user can run it with one click.
            const items = EXAMPLE_ITEMS;
            const res = await api.post('/api/eval/dataset', { items });
            setDatasetAggregate(res.data.aggregate);
            refresh();
        } catch (e: unknown) {
            const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            setError(detail || 'Dataset evaluation failed.');
        } finally {
            setDatasetRunning(false);
        }
    };

    const headerAvgs: (number | null)[] = [
        summary?.avg_faithfulness ?? null,
        summary?.avg_answer_relevancy ?? null,
        summary?.avg_context_precision ?? null,
        summary?.avg_context_recall ?? null,
    ];

    return (
        <div className="flex flex-col h-full p-6 gap-5 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between shrink-0 flex-wrap gap-3">
                <div className="flex items-center gap-3">
                    <div className="p-2 bg-indigo-500/20 rounded-lg border border-indigo-500/20">
                        <BarChart3 className="w-4 h-4 text-indigo-400" />
                    </div>
                    <div>
                        <h2 className="text-lg font-bold text-slate-100">Evaluation Dashboard</h2>
                        <p className="text-xs text-slate-400">RAGAS answer-quality metrics · judged by your configured LLM</p>
                    </div>
                </div>
                <button
                    onClick={refresh}
                    disabled={loading}
                    className="p-2 glass-button rounded-xl text-slate-400 hover:text-slate-200 transition-all"
                    title="Refresh"
                >
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* Error banner */}
            <AnimatePresence>
                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: -6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -6 }}
                        className="flex items-center gap-2 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-sm shrink-0"
                    >
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                        <span>{error}</span>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Scrollable body */}
            <div className="flex-1 overflow-auto space-y-5 pr-1">
                {/* Aggregate header cards */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                    {METRICS.map((m, i) => (
                        <div key={m.key} className="glass-panel rounded-xl p-4">
                            <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">{m.label}</p>
                            <p className={`text-2xl font-bold ${bandText(headerAvgs[i])}`}>{pct(headerAvgs[i])}</p>
                            <div className="h-1.5 rounded-full bg-slate-700/60 overflow-hidden mt-2">
                                <div
                                    className={`h-full rounded-full ${bandColor(headerAvgs[i])}`}
                                    style={{ width: headerAvgs[i] == null ? '0%' : `${Math.max(2, (headerAvgs[i] as number) * 100)}%` }}
                                />
                            </div>
                        </div>
                    ))}
                </div>

                {/* Telemetry strip (reuses existing /api/metrics) */}
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-slate-400 px-1">
                    <span className="flex items-center gap-1.5"><ListChecks className="w-3.5 h-3.5" /> {summary?.runs ?? 0} evaluations</span>
                    <span className="flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-indigo-400/70" /> {telemetry?.requests ?? 0} chat requests</span>
                    <span className="flex items-center gap-1.5"><Coins className="w-3.5 h-3.5 text-amber-400/70" /> {telemetry?.avg_tokens ?? 0} avg tokens</span>
                    <span className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-sky-400/70" /> {telemetry?.avg_total_ms ?? 0} ms avg latency</span>
                </div>

                {/* Run panel */}
                <div className="glass-panel rounded-xl p-4 space-y-3">
                    <div className="flex items-center gap-2">
                        <Target className="w-4 h-4 text-indigo-400" />
                        <h3 className="text-sm font-semibold text-slate-200">Evaluate an answer</h3>
                    </div>
                    <p className="text-xs text-slate-400">
                        Ask a question about your indexed documents. The app generates an answer,
                        then scores it. Add a ground-truth answer to also compute context recall.
                    </p>
                    <input
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) runSingle(); }}
                        placeholder="Question (e.g. What is the refund window?)"
                        className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500/40"
                    />
                    <input
                        value={groundTruth}
                        onChange={(e) => setGroundTruth(e.target.value)}
                        placeholder="Ground-truth answer (optional — enables context recall)"
                        className="w-full bg-slate-800/60 border border-white/10 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500/40"
                    />
                    <div className="flex items-center gap-2">
                        <button
                            onClick={runSingle}
                            disabled={running || !question.trim()}
                            className="flex items-center gap-2 px-3 py-2 bg-indigo-600/70 hover:bg-indigo-500/80 disabled:opacity-40 disabled:cursor-not-allowed border border-indigo-500/30 text-white text-sm font-medium rounded-xl transition-all"
                        >
                            {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                            {running ? 'Evaluating…' : 'Run evaluation'}
                        </button>
                        <button
                            onClick={runExampleDataset}
                            disabled={datasetRunning}
                            className="flex items-center gap-2 px-3 py-2 glass-button rounded-xl text-slate-300 hover:text-white text-sm transition-all"
                            title="Run the 6-question example dataset (with ground truths)"
                        >
                            {datasetRunning ? <RefreshCw className="w-4 h-4 animate-spin" /> : <ListChecks className="w-4 h-4" />}
                            {datasetRunning ? 'Running dataset…' : 'Run example dataset'}
                        </button>
                    </div>

                    {/* Live gauges for the last single result */}
                    <AnimatePresence>
                        {lastResult && (
                            <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                className="pt-2 border-t border-white/5 space-y-3"
                            >
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
                                    {METRICS.map((m) => (
                                        <Gauge key={m.key} label={m.label} value={lastResult[m.key] as number | null} help={m.help} />
                                    ))}
                                </div>
                                {lastResult.answer && (
                                    <p className="text-xs text-slate-400 leading-relaxed">
                                        <span className="text-slate-500">Answer:</span> {lastResult.answer.slice(0, 400)}
                                        {lastResult.answer.length > 400 ? '…' : ''}
                                    </p>
                                )}
                                <p className="text-[10px] text-slate-500">
                                    Judge: {lastResult.eval_provider || '—'} · {lastResult.eval_tokens ?? 0} tokens · {lastResult.eval_latency_ms ?? 0} ms
                                </p>
                            </motion.div>
                        )}
                    </AnimatePresence>

                    {/* Dataset aggregate */}
                    <AnimatePresence>
                        {datasetAggregate && (
                            <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                className="pt-2 border-t border-white/5 space-y-3"
                            >
                                <p className="text-xs font-semibold text-slate-300">Dataset averages ({datasetAggregate.count ?? 0} items)</p>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
                                    <Gauge label="Faithfulness" value={datasetAggregate.avg_faithfulness} />
                                    <Gauge label="Answer Relevancy" value={datasetAggregate.avg_answer_relevancy} />
                                    <Gauge label="Context Precision" value={datasetAggregate.avg_context_precision} />
                                    <Gauge label="Context Recall" value={datasetAggregate.avg_context_recall} />
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {/* Recent evaluations */}
                <div className="glass-panel rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-slate-200 mb-3">Recent evaluations</h3>
                    {recent.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-8 text-slate-500 text-sm">
                            <BarChart3 className="w-10 h-10 text-slate-600 mb-2" />
                            <p>No evaluations yet. Run one above to get started.</p>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                                <thead>
                                    <tr className="text-slate-500 text-left border-b border-white/5">
                                        <th className="py-2 pr-3 font-medium">Question</th>
                                        <th className="py-2 px-2 font-medium text-center">Faith.</th>
                                        <th className="py-2 px-2 font-medium text-center">Relev.</th>
                                        <th className="py-2 px-2 font-medium text-center">Prec.</th>
                                        <th className="py-2 px-2 font-medium text-center">Recall</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {recent.map((r, i) => (
                                        <tr key={r.id ?? i} className="border-b border-white/5 last:border-0">
                                            <td className="py-2 pr-3 text-slate-300 max-w-[280px] truncate" title={r.question}>{r.question}</td>
                                            {(['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall'] as const).map((k) => (
                                                <td key={k} className={`py-2 px-2 text-center font-mono ${bandText(r[k])}`}>{pct(r[k])}</td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// The bundled example dataset (mirrors backend/eval/ragas_example.json) so the
// "Run example dataset" button works with a single click.
const EXAMPLE_ITEMS = [
    { question: 'Where is the Eiffel Tower located?', ground_truth: 'The Eiffel Tower is located in Paris, France, and was completed in 1889.' },
    { question: 'How do plants convert sunlight into energy?', ground_truth: 'Through photosynthesis, green plants convert sunlight into chemical energy stored as glucose.' },
    { question: 'What is the role of employee 7741?', ground_truth: 'Employee ID 7741 is Priya Nair, a Data Scientist in the Analytics team.' },
    { question: 'How tall is the highest mountain on Earth?', ground_truth: 'Mount Everest is the highest mountain above sea level at 8849 meters, in the Himalayas.' },
    { question: 'What is the refund window for returns?', ground_truth: 'Refunds are allowed within 30 days of purchase if the item is unused and in its original packaging.' },
    { question: 'What was the Q3 revenue?', ground_truth: 'Quarterly revenue for Q3 reached 4.2 million dollars, up 12 percent year over year.' },
];
