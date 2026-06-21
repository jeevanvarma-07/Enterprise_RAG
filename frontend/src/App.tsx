import { useState, useEffect, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import SessionsPanel from './components/SessionsPanel';
import SettingsModal from './components/SettingsModal';
import UploadSection from './components/UploadSection';
import VectorStoreTab from './components/VectorStoreTab';
import DataSourcesTab from './components/DataSourcesTab';
import PipelineTab from './components/PipelineTab';
import ArchitectureTab from './components/ArchitectureTab';
import LandingPage from './components/LandingPage';
import ConnectionStatus from './components/ConnectionStatus';
import { FileText, Database, RefreshCw, Settings as SettingsIcon, AlertTriangle, KeyRound } from 'lucide-react';
import { useHealth } from './useHealth';
import api from './api';

interface DocEntry {
  filename: string;
  chunks: number;
  timestamp: string;
}

interface ModelOption {
  id: string;
  label: string;
  provider: string;
  provider_label?: string;
  available?: boolean;
}

function DocumentContextPanel({ refreshTrigger }: { refreshTrigger: number }) {
  const [docs, setDocs] = useState<DocEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/index/documents');
      setDocs(res.data.documents || []);
    } catch {
      setDocs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs, refreshTrigger]);

  const totalChunks = docs.reduce((s, d) => s + d.chunks, 0);

  return (
    <div className="flex-1 glass-panel rounded-2xl p-5 overflow-hidden flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-blue-400" />
          <h3 className="font-semibold text-slate-200 text-sm">Knowledge Base</h3>
        </div>
        <button onClick={fetchDocs} className="text-slate-500 hover:text-slate-300 transition-colors">
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {docs.length > 0 && (
        <div className="mb-3 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded-xl shrink-0">
          <p className="text-xs text-blue-300 font-medium">
            {docs.length} file{docs.length !== 1 ? 's' : ''} · {totalChunks.toLocaleString()} chunks indexed
          </p>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
        {loading ? (
          <p className="text-xs text-slate-500 italic text-center py-4">Loading...</p>
        ) : docs.length === 0 ? (
          <div className="text-center py-6">
            <Database className="w-8 h-8 text-slate-700 mx-auto mb-2" />
            <p className="text-xs text-slate-500 italic">No documents indexed yet.<br />Upload files above to begin.</p>
          </div>
        ) : (
          docs.map((doc) => (
            <div
              key={doc.filename}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-white/5 hover:bg-slate-800/80 transition-colors"
            >
              <FileText className="w-3.5 h-3.5 text-blue-400/80 shrink-0" />
              <span className="text-xs text-slate-300 truncate flex-1 font-medium" title={doc.filename}>
                {doc.filename}
              </span>
              <span className="text-[10px] text-blue-300 font-mono bg-blue-500/10 border border-blue-500/20 rounded-full px-1.5 py-0.5 shrink-0">
                {doc.chunks}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function App() {
  const [showLanding, setShowLanding] = useState(true);
  const [model, setModel] = useState("llama-3.1-8b-instant");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [activeTab, setActiveTab] = useState("chat");
  const [uploadRefresh, setUploadRefresh] = useState(0);

  // Chat-history state lifted here so the sessions sidebar and the chat view
  // stay in sync. `currentSessionId` is the open conversation (null = a fresh,
  // unsaved chat); `sessionRefresh` is bumped to make the sidebar re-fetch
  // after a message is saved (updates titles/counts/ordering).
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [sessionRefresh, setSessionRefresh] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Backend connection + readiness, polled for the header indicator and the
  // first-run banners below the header.
  const { status: health, data: healthData, refresh: refreshHealth } = useHealth();

  // Load the available models from the backend registry (single source of truth)
  useEffect(() => {
    api.get('/api/models')
      .then(res => {
        const list: ModelOption[] = res.data.models || [];
        setModels(list);
        // Prefer a usable (configured) model: keep the current one only if it's
        // still offered AND available; otherwise fall back to the backend default
        // or the first available model.
        const current = list.find(m => m.id === model);
        if (!current || current.available === false) {
          const firstAvailable = list.find(m => m.available !== false);
          setModel(res.data.default || firstAvailable?.id || (list[0]?.id ?? model));
        }
      })
      .catch(() => { /* backend offline — keep the default option below */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The provider that owns the selected model (sent with chat so the backend
  // knows which client + key to use; falls back to backend resolution if absent).
  const selectedProvider = models.find(m => m.id === model)?.provider;

  // Show landing on first load, workspace after enter
  if (showLanding) {
    return <LandingPage onEnter={() => setShowLanding(false)} />;
  }

  const isFullWidth = activeTab !== 'chat';

  return (
    <div className="flex h-screen bg-slate-950 overflow-hidden text-slate-200">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/20 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-purple-600/20 rounded-full blur-[120px] pointer-events-none" />

      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 flex flex-col h-full relative z-10 p-4 gap-4 overflow-hidden">
        {/* Header */}
        <header className="glass-panel rounded-2xl p-4 flex justify-between items-center shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowLanding(true)}
              title="Back to landing page"
              className="text-xs text-slate-500 hover:text-blue-400 transition-colors font-medium"
            >
              ← Home
            </button>
            <div className="w-px h-4 bg-slate-700" />
            <div>
              <h1 className="text-xl font-bold tracking-tight text-gradient">Enterprise RAG</h1>
              <p className="text-xs text-slate-400">Knowledge Retrieval System</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ConnectionStatus status={health} data={healthData} onRefresh={refreshHealth} />
            <div className="w-px h-4 bg-slate-700" />
            <span className="text-sm text-slate-400">Model:</span>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="bg-slate-800/80 border border-slate-700 rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-blue-500/50 transition-all text-slate-200"
            >
              {models.length > 0 ? (
                // Group models by provider; disable any whose provider has no key.
                Object.entries(
                  models.reduce<Record<string, ModelOption[]>>((groups, m) => {
                    const key = m.provider_label || m.provider;
                    (groups[key] = groups[key] || []).push(m);
                    return groups;
                  }, {})
                ).map(([providerLabel, group]) => (
                  <optgroup key={providerLabel} label={providerLabel}>
                    {group.map((m) => (
                      <option key={`${m.provider}:${m.id}`} value={m.id} disabled={m.available === false}>
                        {m.label}{m.available === false ? ' — needs key' : ''}
                      </option>
                    ))}
                  </optgroup>
                ))
              ) : (
                <option value={model}>{model}</option>
              )}
            </select>
            <button
              onClick={() => setSettingsOpen(true)}
              title="Settings"
              className="p-2 rounded-lg bg-slate-800/80 border border-slate-700 text-slate-400 hover:text-blue-400 hover:border-blue-500/40 transition-colors"
            >
              <SettingsIcon className="w-4 h-4" />
            </button>
          </div>
        </header>

        {/* Offline banner — backend unreachable */}
        {health === 'offline' && (
          <div className="shrink-0 flex items-center gap-2.5 px-4 py-2.5 rounded-2xl bg-red-500/10 border border-red-500/30 text-sm text-red-200">
            <AlertTriangle className="w-4 h-4 shrink-0 text-red-400" />
            <span className="flex-1">
              Can't reach the backend. Start it with{' '}
              <code className="text-red-100 bg-red-500/20 px-1.5 py-0.5 rounded text-xs">uvicorn main:app --port 8000</code>.
            </span>
            <button onClick={refreshHealth} className="text-xs font-semibold px-3 py-1 rounded-lg bg-red-500/20 hover:bg-red-500/30 transition-colors">
              Retry
            </button>
          </div>
        )}

        {/* First-run nudge — no LLM provider key configured yet */}
        {health === 'online' && healthData?.providers_configured === 0 && (
          <div className="shrink-0 flex items-center gap-2.5 px-4 py-2.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-sm text-amber-200">
            <KeyRound className="w-4 h-4 shrink-0 text-amber-400" />
            <span className="flex-1">
              No LLM provider key configured yet — add one to start chatting with your documents.
            </span>
            <button onClick={() => setSettingsOpen(true)} className="text-xs font-semibold px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 transition-colors">
              Open Settings
            </button>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 flex flex-col lg:flex-row gap-4 overflow-hidden">

          {/* LEFT panel — only on Chat tab */}
          {activeTab === 'chat' && (
            <div className="w-full lg:w-1/3 flex flex-col gap-4 overflow-hidden">
              <UploadSection onUploadSuccess={() => setUploadRefresh(v => v + 1)} />
              <SessionsPanel
                currentSessionId={currentSessionId}
                onSelect={setCurrentSessionId}
                onNew={() => setCurrentSessionId(null)}
                refreshKey={sessionRefresh}
              />
              <DocumentContextPanel refreshTrigger={uploadRefresh} />
            </div>
          )}

          {/* RIGHT / Full-width panel */}
          <div className={`w-full ${isFullWidth ? '' : 'lg:w-2/3'} glass-panel rounded-2xl overflow-hidden flex flex-col`}>
            {activeTab === 'chat'       && (
              <ChatInterface
                selectedModel={model}
                selectedProvider={selectedProvider}
                currentSessionId={currentSessionId}
                onSessionChange={setCurrentSessionId}
                onSessionSaved={() => setSessionRefresh(v => v + 1)}
              />
            )}
            {activeTab === 'data'       && <DataSourcesTab />}
            {activeTab === 'vector'     && <VectorStoreTab />}
            {activeTab === 'pipeline'   && <PipelineTab />}
            {activeTab === 'arch'       && <ArchitectureTab />}
          </div>
        </div>
      </main>

      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

export default App;
