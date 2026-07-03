import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, ChevronDown, ChevronUp, Wand2, Copy as CopyIcon, Layers,
  ListOrdered, Filter, Hash, FileStack, Clock, Coins,
} from 'lucide-react';

// ── Shapes emitted by services/inspection.py `RetrievalTrace.to_dict()` ───────
export interface TraceHit {
  source: string;
  preview: string;
  chars: number;
  location?: string;
  rank?: number;
  score?: number;
}
export interface QueryHits { query: string; hits: TraceHit[]; }
export interface Tokens { prompt: number; completion: number; total: number; estimated: boolean; }
export interface InspectionData {
  original_query: string | null;
  rewritten_query: string | null;
  multi_queries: string[];
  dense_by_query: QueryHits[];
  sparse_by_query: QueryHits[];
  fused: TraceHit[];
  reranked: TraceHit[] | null;
  rerank_enabled: boolean;
  exact_match: string | null;
  final_context_chars: number | null;
  final_context_preview: string | null;
  budget: Record<string, unknown> | null;
  timings_ms: Record<string, number>;
  tokens: Tokens | null;
  provider: string | null;
}
// The compact per-request telemetry carried on the stream's `done` event.
export interface RequestMetrics {
  provider: string;
  tokens: Tokens;
  retrieval_ms: number;
  generation_ms: number;
  total_ms: number;
}

function fmtMs(ms?: number) {
  if (ms == null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

/**
 * Compact per-answer telemetry strip (provider · tokens · latency). Always shown
 * under an AI answer once the `done{metrics}` event arrives — the Inspector below
 * is the deep-dive; this is the at-a-glance summary.
 */
export function MetricsBar({ metrics }: { metrics: RequestMetrics }) {
  const t = metrics.tokens;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
      {t && (
        <span className="flex items-center gap-1" title={`prompt ${t.prompt} · completion ${t.completion}`}>
          <Coins className="w-3 h-3 text-amber-400/70" />
          {t.total.toLocaleString()} tokens{t.estimated ? ' (est.)' : ''}
        </span>
      )}
      <span className="flex items-center gap-1" title={`retrieval ${fmtMs(metrics.retrieval_ms)} · generation ${fmtMs(metrics.generation_ms)}`}>
        <Clock className="w-3 h-3 text-sky-400/70" />
        {fmtMs(metrics.total_ms)}
      </span>
      {metrics.provider && (
        <span className="text-slate-600 truncate max-w-[220px]" title={metrics.provider}>
          {metrics.provider}
        </span>
      )}
    </div>
  );
}

// One retrieved chunk row (rank · source · location · score · preview).
function HitRow({ hit }: { hit: TraceHit }) {
  return (
    <div className="px-2.5 py-1.5 border-t border-white/5 first:border-t-0">
      <div className="flex items-center gap-1.5 mb-0.5">
        {hit.rank != null && (
          <span className="text-[9px] font-mono bg-slate-700/60 text-slate-300 rounded px-1">#{hit.rank}</span>
        )}
        <span className="text-[10px] font-semibold text-slate-300 truncate">{hit.source}</span>
        {hit.location && (
          <span className="text-[9px] font-mono bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 rounded px-1">{hit.location}</span>
        )}
        {hit.score != null && (
          <span className="ml-auto text-[9px] font-mono text-emerald-400/80" title="RRF score">{hit.score.toFixed(4)}</span>
        )}
      </div>
      <p className="text-[10px] text-slate-500 leading-relaxed italic line-clamp-2">"{hit.preview}"</p>
    </div>
  );
}

// A titled, collapsible stage block.
function Stage({
  icon, title, count, children, defaultOpen = false,
}: {
  icon: React.ReactNode; title: string; count?: number;
  children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-white/5 overflow-hidden bg-slate-900/40">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 bg-slate-800/50 hover:bg-slate-800/80 transition-colors text-left"
      >
        <span className="text-slate-400">{icon}</span>
        <span className="text-[11px] font-medium text-slate-300">{title}</span>
        {count != null && (
          <span className="text-[9px] font-mono bg-slate-700/60 text-slate-400 rounded px-1">{count}</span>
        )}
        <span className="ml-auto text-slate-500">{open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="p-1">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function QueryGroup({ groups }: { groups: QueryHits[] }) {
  if (!groups || groups.length === 0) {
    return <p className="px-2.5 py-2 text-[10px] text-slate-600 italic">No results for this stage.</p>;
  }
  return (
    <div className="flex flex-col gap-1">
      {groups.map((g, i) => (
        <div key={i} className="rounded-md bg-slate-900/60 border border-white/5">
          <p className="px-2.5 py-1 text-[10px] text-blue-300/80 font-mono border-b border-white/5 truncate" title={g.query}>
            ↳ {g.query}
          </p>
          {g.hits.length
            ? g.hits.map((h, j) => <HitRow key={j} hit={h} />)
            : <p className="px-2.5 py-1.5 text-[10px] text-slate-600 italic">no hits</p>}
        </div>
      ))}
    </div>
  );
}

/**
 * The Retrieval Inspector: an opt-in, per-answer trace of the whole RAG pipeline.
 * Rendered only when the `retrieval_inspector` setting is on AND the stream carried
 * an `inspection` event. Collapsed by default so it never crowds the conversation.
 */
export default function RetrievalInspector({ data }: { data: InspectionData }) {
  const [open, setOpen] = useState(false);
  const rewrote = data.rewritten_query && data.rewritten_query !== data.original_query;
  const timings = data.timings_ms || {};

  return (
    <div className="mt-2 rounded-xl overflow-hidden border border-violet-500/15">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-violet-500/10 hover:bg-violet-500/15 transition-colors text-[11px] text-violet-300 font-medium"
      >
        <span className="flex items-center gap-1.5">
          <Search className="w-3 h-3" />
          Retrieval Inspector
        </span>
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden bg-slate-900/70"
          >
            <div className="p-2.5 flex flex-col gap-1.5">

              {/* Query rewrite */}
              <Stage icon={<Wand2 className="w-3.5 h-3.5" />} title="Query rewrite" defaultOpen>
                <div className="px-2.5 py-1.5 space-y-1">
                  <p className="text-[10px] text-slate-500">Original</p>
                  <p className="text-[11px] text-slate-300 font-mono">{data.original_query || '—'}</p>
                  {rewrote ? (
                    <>
                      <p className="text-[10px] text-slate-500 mt-1">Rewritten (history-aware)</p>
                      <p className="text-[11px] text-emerald-300/90 font-mono">{data.rewritten_query}</p>
                    </>
                  ) : (
                    <p className="text-[10px] text-slate-600 italic mt-0.5">No rewrite needed (standalone query).</p>
                  )}
                </div>
              </Stage>

              {/* Multi-queries */}
              <Stage icon={<CopyIcon className="w-3.5 h-3.5" />} title="Multi-query variations" count={data.multi_queries?.length}>
                {data.multi_queries?.length ? (
                  <ul className="px-2.5 py-1.5 space-y-1">
                    {data.multi_queries.map((q, i) => (
                      <li key={i} className="text-[11px] text-slate-300 font-mono flex gap-1.5">
                        <span className="text-slate-600">{i + 1}.</span>{q}
                      </li>
                    ))}
                  </ul>
                ) : <p className="px-2.5 py-2 text-[10px] text-slate-600 italic">None generated.</p>}
              </Stage>

              {/* Dense (FAISS) */}
              <Stage icon={<Layers className="w-3.5 h-3.5" />} title="Dense retrieval · FAISS + MMR" count={data.dense_by_query?.length}>
                <QueryGroup groups={data.dense_by_query} />
              </Stage>

              {/* Sparse (BM25) */}
              <Stage icon={<Filter className="w-3.5 h-3.5" />} title="Sparse retrieval · BM25" count={data.sparse_by_query?.length}>
                <QueryGroup groups={data.sparse_by_query} />
              </Stage>

              {/* Fused (RRF) */}
              <Stage icon={<ListOrdered className="w-3.5 h-3.5" />} title="Reciprocal Rank Fusion" count={data.fused?.length} defaultOpen>
                {data.fused?.length
                  ? <div className="rounded-md bg-slate-900/60 border border-white/5">{data.fused.map((h, i) => <HitRow key={i} hit={h} />)}</div>
                  : <p className="px-2.5 py-2 text-[10px] text-slate-600 italic">No fused results.</p>}
              </Stage>

              {/* Reranked */}
              {data.rerank_enabled && data.reranked && (
                <Stage icon={<Hash className="w-3.5 h-3.5" />} title="Cross-encoder rerank" count={data.reranked.length}>
                  <div className="rounded-md bg-slate-900/60 border border-white/5">{data.reranked.map((h, i) => <HitRow key={i} hit={h} />)}</div>
                </Stage>
              )}

              {/* Exact match */}
              {data.exact_match && (
                <Stage icon={<Hash className="w-3.5 h-3.5" />} title="Exact CSV/Excel lookup">
                  <p className="px-2.5 py-1.5 text-[10px] text-slate-400 font-mono whitespace-pre-wrap">{data.exact_match}</p>
                </Stage>
              )}

              {/* Final context */}
              <Stage icon={<FileStack className="w-3.5 h-3.5" />} title="Final context sent to LLM">
                <div className="px-2.5 py-1.5 space-y-1">
                  <p className="text-[10px] text-slate-500">
                    {(data.final_context_chars ?? 0).toLocaleString()} chars
                    {data.budget?.max_context_chars ? ` (budget ${Number(data.budget.max_context_chars).toLocaleString()})` : ''}
                  </p>
                  {data.final_context_preview && (
                    <p className="text-[10px] text-slate-400 font-mono leading-relaxed line-clamp-4 whitespace-pre-wrap">
                      {data.final_context_preview}…
                    </p>
                  )}
                </div>
              </Stage>

              {/* Tokens + timings */}
              <div className="grid grid-cols-2 gap-1.5">
                <div className="rounded-lg border border-white/5 bg-slate-900/40 px-2.5 py-2">
                  <p className="text-[10px] text-slate-500 flex items-center gap-1 mb-1"><Coins className="w-3 h-3 text-amber-400/70" /> Tokens</p>
                  {data.tokens ? (
                    <p className="text-[11px] text-slate-300 font-mono">
                      {data.tokens.total.toLocaleString()} total
                      <span className="text-slate-600"> · {data.tokens.prompt}p / {data.tokens.completion}c</span>
                      {data.tokens.estimated && <span className="text-amber-400/70"> · est.</span>}
                    </p>
                  ) : <p className="text-[10px] text-slate-600 italic">not reported</p>}
                </div>
                <div className="rounded-lg border border-white/5 bg-slate-900/40 px-2.5 py-2">
                  <p className="text-[10px] text-slate-500 flex items-center gap-1 mb-1"><Clock className="w-3 h-3 text-sky-400/70" /> Latency</p>
                  <p className="text-[11px] text-slate-300 font-mono">
                    {fmtMs(timings.total)}
                    <span className="text-slate-600"> · retr {fmtMs(timings.retrieval)} / gen {fmtMs(timings.generation)}</span>
                  </p>
                </div>
              </div>

            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
