import { motion } from 'framer-motion';
import { Monitor, Server, Database, ArrowRight, FileText, Image, FileSpreadsheet, Globe, Cpu } from 'lucide-react';
import { API_BASE_URL } from '../api';

const frontendComponents = [
  { name: 'LandingPage.tsx', desc: 'Hero, features, pipeline diagram' },
  { name: 'ChatInterface.tsx', desc: 'AI chat with source transparency' },
  { name: 'UploadSection.tsx', desc: 'Batch file upload with progress' },
  { name: 'VectorStoreTab.tsx', desc: 'Index management & batch delete' },
  { name: 'DataSourcesTab.tsx', desc: 'File browser & URL scraper' },
  { name: 'PipelineTab.tsx', desc: 'Visual RAG pipeline explanation' },
  { name: 'ArchitectureTab.tsx', desc: 'Full system architecture view' },
];

const backendModules = [
  { name: 'main.py', desc: '10+ REST API endpoints, CORS, async batch upload' },
  { name: 'document_processing.py', desc: 'Multi-format parsing + OCR fallback' },
  { name: 'indexing.py', desc: 'FAISS manager — add, delete, save, load' },
  { name: 'generation.py', desc: 'Multi-Query + MMR + RRF RAG pipeline' },
];

const docTypes = [
  { icon: FileText, label: 'PDF', desc: 'PyPDF2 text extraction', color: 'text-red-400', bg: 'bg-red-500/10' },
  { icon: FileText, label: 'PDF (Scanned)', desc: 'pdf2image + pytesseract OCR', color: 'text-orange-400', bg: 'bg-orange-500/10' },
  { icon: FileSpreadsheet, label: 'CSV / Excel', desc: 'pandas row-by-row conversion', color: 'text-green-400', bg: 'bg-green-500/10' },
  { icon: Image, label: 'Images', desc: 'pytesseract direct OCR', color: 'text-purple-400', bg: 'bg-purple-500/10' },
  { icon: FileText, label: 'TXT', desc: 'Direct UTF-8 read', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  { icon: Globe, label: 'URLs', desc: 'HTMLParser scraper', color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
];

const techStack = [
  { cat: 'Frontend', items: ['React 18', 'Vite', 'TypeScript', 'Tailwind CSS', 'Framer Motion', 'React-Markdown', 'Axios'] },
  { cat: 'Backend', items: ['FastAPI', 'Uvicorn', 'Pydantic', 'asyncio', 'Python 3.9+'] },
  { cat: 'AI / ML', items: ['FAISS (local)', 'HuggingFace all-MiniLM-L6-v2', 'Groq API', 'LangChain Core'] },
  { cat: 'Doc Parsing', items: ['PyPDF2', 'pdf2image', 'pytesseract', 'pandas', 'Pillow', 'HTMLParser'] },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="glass-panel rounded-2xl p-5 mb-4">
      <h3 className="text-sm font-bold text-slate-200 mb-4">{title}</h3>
      {children}
    </div>
  );
}

export default function ArchitectureTab() {
  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto p-6 gap-0">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-slate-100">System Architecture</h2>
        <p className="text-xs text-slate-400 mt-1">Full breakdown of the frontend, backend, and AI components</p>
      </div>

      {/* System Overview */}
      <Section title="System Overview">
        <div className="flex flex-wrap items-center justify-center gap-3">
          {[
            { icon: Monitor, label: 'React Frontend', sub: window.location.host, color: 'text-blue-400', bg: 'bg-blue-500/10' },
            { icon: Server, label: 'FastAPI Backend', sub: API_BASE_URL.replace(/^https?:\/\//, ''), color: 'text-green-400', bg: 'bg-green-500/10' },
            { icon: Cpu, label: 'HuggingFace Embeddings', sub: 'Local CPU', color: 'text-purple-400', bg: 'bg-purple-500/10' },
            { icon: Database, label: 'FAISS Vector DB', sub: 'Local Disk', color: 'text-amber-400', bg: 'bg-amber-500/10' },
            { icon: Globe, label: 'Groq LLM API', sub: 'Cloud Inference', color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
          ].map((node, i, arr) => (
            <div key={node.label} className="flex items-center gap-3">
              <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.1 }}
                className={`flex flex-col items-center gap-2 p-4 rounded-xl border ${node.bg} border-current/20 w-36 text-center`}>
                <node.icon className={`w-6 h-6 ${node.color}`} />
                <p className={`text-xs font-semibold ${node.color}`}>{node.label}</p>
                <p className="text-[10px] text-slate-500">{node.sub}</p>
              </motion.div>
              {i < arr.length - 1 && <ArrowRight className="w-4 h-4 text-slate-600" />}
            </div>
          ))}
        </div>
      </Section>

      {/* Frontend Components */}
      <Section title="Frontend Components">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
          {frontendComponents.map(c => (
            <div key={c.name} className="p-3 rounded-lg bg-slate-800/50 border border-white/5">
              <p className="text-[10px] font-mono text-blue-300 mb-1">{c.name}</p>
              <p className="text-[10px] text-slate-500">{c.desc}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Backend Modules */}
      <Section title="Backend Modules">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {backendModules.map(m => (
            <div key={m.name} className="p-3 rounded-lg bg-slate-800/50 border border-white/5">
              <p className="text-xs font-mono text-green-300 mb-1">{m.name}</p>
              <p className="text-xs text-slate-400">{m.desc}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Document Processing Pipeline */}
      <Section title="Document Processing Pipeline">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {docTypes.map(d => (
            <div key={d.label} className={`p-3 rounded-lg ${d.bg} border border-current/20 flex items-start gap-2`}>
              <d.icon className={`w-4 h-4 ${d.color} shrink-0 mt-0.5`} />
              <div>
                <p className={`text-xs font-semibold ${d.color}`}>{d.label}</p>
                <p className="text-[10px] text-slate-400 mt-0.5">{d.desc}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 px-4 py-3 rounded-lg bg-slate-800/60 border border-white/5">
          <p className="text-[10px] text-slate-400 font-mono">
            All formats → <span className="text-blue-300">chunk_text(size=1000, overlap=150)</span> → <span className="text-green-300">FAISS.add_documents(embeddings)</span>
          </p>
        </div>
      </Section>

      {/* Tech Stack */}
      <Section title="Complete Technology Stack">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {techStack.map(t => (
            <div key={t.cat}>
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-2 font-semibold">{t.cat}</p>
              <div className="space-y-1">
                {t.items.map(item => (
                  <div key={item} className="px-2.5 py-1.5 rounded-md bg-slate-800/60 border border-white/5 text-xs text-slate-300">{item}</div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
