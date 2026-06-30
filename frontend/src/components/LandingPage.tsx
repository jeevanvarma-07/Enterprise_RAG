import { motion } from 'framer-motion';
import { FileText, Search, Zap, Database, Globe, ArrowRight, ChevronRight, Brain } from 'lucide-react';

interface Props { onEnter: () => void; }

const features = [
  { icon: FileText, title: 'Multi-Format Ingestion', desc: 'PDF, Excel, CSV, Images, TXT, and live Web URLs all supported out of the box.', color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
  { icon: Search, title: 'OCR for Scanned Docs', desc: 'Auto-detects image-based PDFs and handwritten forms, runs OCR transparently.', color: 'text-purple-400', bg: 'bg-purple-500/10 border-purple-500/20' },
  { icon: Brain, title: 'Multi-Query Retrieval', desc: 'Generates 3 semantic query variations to overcome terminology gaps.', color: 'text-indigo-400', bg: 'bg-indigo-500/10 border-indigo-500/20' },
  { icon: Database, title: 'FAISS Vector Search', desc: 'MMR-powered local vector search with diversity-aware ranking.', color: 'text-cyan-400', bg: 'bg-cyan-500/10 border-cyan-500/20' },
  { icon: Zap, title: 'Reciprocal Rank Fusion', desc: 'Mathematically merges results from all query variants for maximum accuracy.', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' },
  { icon: Globe, title: 'Groq LLM Generation', desc: 'Structured Markdown answers via Llama 3.1/3.3 and Mixtral on Groq API.', color: 'text-green-400', bg: 'bg-green-500/10 border-green-500/20' },
];

const pipeline = [
  'Upload Docs', 'Parse & OCR', 'Chunk Text', 'Embed Vectors', 'FAISS Index', 'MMR + RRF', 'LLM Answer',
];

export default function LandingPage({ onEnter }: Props) {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 overflow-y-auto">
      {/* Ambient blobs */}
      <div className="fixed top-[-20%] left-[-10%] w-[50%] h-[50%] bg-blue-600/15 rounded-full blur-[140px] pointer-events-none" />
      <div className="fixed bottom-[-20%] right-[-10%] w-[50%] h-[50%] bg-purple-600/15 rounded-full blur-[140px] pointer-events-none" />

      <div className="relative z-10 max-w-5xl mx-auto px-6 py-16">

        {/* ── Hero ── */}
        <motion.div initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7 }} className="text-center mb-20">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-blue-500/30 bg-blue-500/10 text-blue-300 text-xs font-medium mb-6">
            <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
            Local-First · Privacy-Safe · AI-Powered
          </div>

          <h1 className="text-5xl md:text-6xl font-extrabold tracking-tight mb-5">
            <span className="bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
              Enterprise RAG
            </span>
            <br />
            <span className="text-slate-100">System</span>
          </h1>

          <p className="text-xl text-slate-400 max-w-2xl mx-auto mb-3 leading-relaxed">
            Intelligent Document Retrieval &amp; AI Knowledge Assistant
          </p>
          <p className="text-sm text-slate-500 max-w-xl mx-auto mb-10">
            Upload any document → Ask any question → AI retrieves and synthesizes the exact information you need.
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <motion.button
              whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}
              onClick={onEnter}
              className="px-8 py-3.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-semibold rounded-xl shadow-lg shadow-blue-500/20 flex items-center gap-2 justify-center transition-all"
            >
              Enter Workspace <ArrowRight className="w-4 h-4" />
            </motion.button>
            <motion.a
              whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.97 }}
              href="#pipeline"
              className="px-8 py-3.5 bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700 text-slate-200 font-semibold rounded-xl flex items-center gap-2 justify-center transition-all"
            >
              View Architecture <ChevronRight className="w-4 h-4" />
            </motion.a>
          </div>
        </motion.div>

        {/* ── Features Grid ── */}
        <motion.section initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3, duration: 0.6 }} className="mb-20">
          <h2 className="text-2xl font-bold text-center text-slate-100 mb-10">Core Capabilities</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {features.map((f, i) => (
              <motion.div key={f.title} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 + i * 0.07 }}
                className={`p-5 rounded-2xl border ${f.bg} backdrop-blur-sm hover:scale-[1.02] transition-transform`}>
                <f.icon className={`w-6 h-6 ${f.color} mb-3`} />
                <h3 className="font-semibold text-slate-100 mb-1.5 text-sm">{f.title}</h3>
                <p className="text-xs text-slate-400 leading-relaxed">{f.desc}</p>
              </motion.div>
            ))}
          </div>
        </motion.section>

        {/* ── Pipeline Diagram ── */}
        <motion.section id="pipeline" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5, duration: 0.6 }} className="mb-20">
          <h2 className="text-2xl font-bold text-center text-slate-100 mb-3">RAG Pipeline Architecture</h2>
          <p className="text-sm text-slate-500 text-center mb-8">Every query flows through a 7-stage intelligent retrieval pipeline</p>

          <div className="flex flex-wrap justify-center items-center gap-2">
            {pipeline.map((step, i) => (
              <div key={step} className="flex items-center gap-2">
                <div className="flex flex-col items-center">
                  <div className="w-7 h-7 rounded-full bg-blue-500/20 border border-blue-500/40 flex items-center justify-center text-[10px] font-bold text-blue-300 mb-1.5">{i + 1}</div>
                  <div className="px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700 text-xs font-semibold text-slate-200 whitespace-nowrap">{step}</div>
                </div>
                {i < pipeline.length - 1 && <ArrowRight className="w-4 h-4 text-slate-600 shrink-0 mt-2" />}
              </div>
            ))}
          </div>
        </motion.section>

        {/* ── Tech Stack ── */}
        <motion.section initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6, duration: 0.6 }} className="mb-16">
          <h2 className="text-2xl font-bold text-center text-slate-100 mb-8">Technology Stack</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'React + Vite + TS', cat: 'Frontend' },
              { label: 'FastAPI + Uvicorn', cat: 'Backend' },
              { label: 'FAISS (Local)', cat: 'Vector DB' },
              { label: 'all-MiniLM-L6-v2', cat: 'Embeddings' },
              { label: 'Groq API', cat: 'LLM Inference' },
              { label: 'PyPDF2 + pytesseract', cat: 'Doc Parsing' },
              { label: 'pandas', cat: 'Tabular Data' },
              { label: 'Framer Motion', cat: 'UI Animations' },
            ].map(t => (
              <div key={t.label} className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 text-center">
                <p className="text-[10px] text-slate-500 mb-1 uppercase tracking-wide">{t.cat}</p>
                <p className="text-xs font-semibold text-slate-300">{t.label}</p>
              </div>
            ))}
          </div>
        </motion.section>

        {/* ── Footer ── */}
        <motion.footer initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.8 }}
          className="border-t border-slate-800 pt-8 text-center">
          <p className="text-xs text-slate-500 mb-4">Enterprise RAG System · Local-first document intelligence · FastAPI + React + FAISS</p>
          <motion.button whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
            onClick={onEnter}
            className="px-6 py-2.5 bg-blue-600/30 hover:bg-blue-500/40 border border-blue-500/30 text-blue-300 text-sm font-medium rounded-xl transition-all flex items-center gap-2 mx-auto">
            Launch Workspace <ArrowRight className="w-3.5 h-3.5" />
          </motion.button>
        </motion.footer>

      </div>
    </div>
  );
}
