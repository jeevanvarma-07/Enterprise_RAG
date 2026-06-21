import { motion } from 'framer-motion';
import { Search, FileSearch, Database, GitMerge, MessageSquare, Brain, ArrowRight } from 'lucide-react';

const STEPS = [
  {
    num: 1, icon: Brain, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/30',
    title: 'Question Processing',
    subtitle: 'History Condensation',
    desc: 'If the user has prior chat history, the LLM rewrites the new question as a fully standalone, self-contained query. This ensures follow-up questions like "explain that more" work correctly.',
    detail: 'Technique: LangChain History-Aware Retriever · Model: Groq LLM',
  },
  {
    num: 2, icon: Search, color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/30',
    title: 'Query Expansion',
    subtitle: 'Multi-Query Generation',
    desc: 'The LLM generates 3 semantically different variations of the original question. This overcomes vocabulary mismatches where the user\'s exact words might not appear in the documents.',
    detail: 'Output: 4 queries total (1 original + 3 variants) · Model: Groq Llama',
  },
  {
    num: 3, icon: Database, color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/30',
    title: 'Vector Retrieval',
    subtitle: 'MMR Search on FAISS',
    desc: 'Each of the 4 queries searches the FAISS vector index using Maximum Marginal Relevance (MMR), which retrieves chunks that are both highly relevant AND diverse from each other.',
    detail: 'Config: k=5, fetch_k=20, lambda_mult=0.6 · Embeddings: all-MiniLM-L6-v2',
  },
  {
    num: 4, icon: GitMerge, color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/30',
    title: 'RRF Ranking',
    subtitle: 'Reciprocal Rank Fusion',
    desc: 'All retrieved document chunks from the 4 queries are merged using the RRF algorithm. Chunks that appear consistently at the top across multiple query results receive a higher final score.',
    detail: 'Formula: score(d) = Σ 1/(k + rank) · k=60 · Top 6 chunks selected',
  },
  {
    num: 5, icon: FileSearch, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30',
    title: 'Context Assembly',
    subtitle: 'Prompt Construction',
    desc: 'The top 6 ranked document chunks are assembled into a context window. The system prompt, conversation history, and user query are combined with this context to form the final prompt.',
    detail: 'Format: [System Prompt + Context] + [Chat History] + [User Query]',
  },
  {
    num: 6, icon: MessageSquare, color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/30',
    title: 'LLM Generation',
    subtitle: 'Groq API Inference',
    desc: 'The assembled prompt is sent to the Groq API. The LLM generates a structured Markdown-formatted answer grounded strictly in the retrieved document context — it cannot hallucinate beyond it.',
    detail: 'Models: Llama 3.1 8B / Llama 3.3 70B / Mixtral 8x7B · Temperature: 0.3',
  },
];

const PIPELINE_LABELS = ['Question', 'Condensation', 'Multi-Query', 'MMR Retrieval ×4', 'RRF Fusion', 'Top-6 Chunks', 'LLM', 'Answer'];

export default function PipelineTab() {
  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto p-6 gap-8">

      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-100">AI Pipeline Viewer</h2>
        <p className="text-xs text-slate-400 mt-1">How every question is processed through the 6-stage RAG pipeline</p>
      </div>

      {/* Flow diagram */}
      <div className="glass-panel rounded-2xl p-5">
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">End-to-End Flow</h3>
        <div className="flex flex-wrap items-center gap-2">
          {PIPELINE_LABELS.map((label, i) => (
            <div key={label} className="flex items-center gap-2">
              <div className={`px-3 py-1.5 rounded-lg text-xs font-semibold border whitespace-nowrap
                ${i === 0 || i === PIPELINE_LABELS.length - 1
                  ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
                  : 'bg-slate-800 border-slate-700 text-slate-300'}`}>
                {label}
              </div>
              {i < PIPELINE_LABELS.length - 1 && <ArrowRight className="w-3 h-3 text-slate-600 shrink-0" />}
            </div>
          ))}
        </div>
      </div>

      {/* Step cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {STEPS.map((step, i) => (
          <motion.div key={step.num}
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }}
            className={`glass-panel rounded-2xl p-5 border ${step.bg}`}>
            <div className="flex items-start gap-4">
              <div className={`w-10 h-10 rounded-xl ${step.bg} border flex items-center justify-center shrink-0`}>
                <step.icon className={`w-5 h-5 ${step.color}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] font-bold ${step.color} uppercase tracking-widest`}>Step {step.num}</span>
                  <span className="text-[10px] text-slate-500">·</span>
                  <span className="text-[10px] text-slate-400">{step.subtitle}</span>
                </div>
                <h3 className="text-sm font-bold text-slate-100 mb-2">{step.title}</h3>
                <p className="text-xs text-slate-400 leading-relaxed mb-3">{step.desc}</p>
                <div className={`px-3 py-1.5 rounded-lg ${step.bg} border text-[10px] font-mono text-slate-300`}>
                  {step.detail}
                </div>
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Why this is better */}
      <div className="glass-panel rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Why This Pipeline is Advanced</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            { label: 'vs Basic RAG', text: 'Basic RAG runs 1 query. This system runs 4 queries and fuses the results mathematically.' },
            { label: 'vs Keyword Search', text: 'Keyword search fails on synonyms. Vector + MMR understands semantic meaning.' },
            { label: 'vs No History', text: 'Most demos lose context between turns. This system condenses history into every query.' },
          ].map(c => (
            <div key={c.label} className="p-3 rounded-xl bg-slate-800/50 border border-white/5">
              <p className="text-[10px] font-bold text-blue-300 mb-1">{c.label}</p>
              <p className="text-xs text-slate-400 leading-relaxed">{c.text}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
