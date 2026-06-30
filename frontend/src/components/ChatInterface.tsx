import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Send, Bot, User, Sparkles, Copy, Trash2, ChevronDown, ChevronUp, FileText, Check, X, Download, AlertTriangle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import api, { API_BASE_URL } from '../api';

interface Source { file: string; chunk: number; preview: string; location?: string; text?: string; }
interface Message {
  role: 'user' | 'ai';
  content: string;
  timestamp: string;
  sources?: Source[];
  notice?: string;   // e.g. "Provider X unavailable; answered with Y" (provider fallback)
}

const EXAMPLE_QUERIES = [
  'Summarize the key points in the uploaded document',
  'What financial data appears in the spreadsheet?',
  'List all records where the status is active',
  'Explain the main policy described in the document',
  'Which items have the highest value in the dataset?',
];

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

// Full-screen modal showing the exact chunk a citation came from.
function SourceModal({ source, onClose }: { source: Source; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
    >
      <motion.div
        initial={{ scale: 0.96, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.96, y: 10 }}
        onClick={(e) => e.stopPropagation()}
        className="glass-panel w-full max-w-2xl max-h-[80vh] flex flex-col rounded-2xl border border-white/10 shadow-2xl overflow-hidden"
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/10 bg-slate-900/60 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <FileText className="w-4 h-4 text-blue-400 shrink-0" />
            <span className="text-sm font-semibold text-slate-200 truncate">{source.file}</span>
            <span className="text-[10px] font-mono bg-blue-500/10 border border-blue-500/20 text-blue-300 rounded px-1.5 py-0.5 shrink-0">chunk {source.chunk}</span>
            {source.location && (
              <span className="text-[10px] font-mono bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 rounded px-1.5 py-0.5 shrink-0">{source.location}</span>
            )}
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-700/60 text-slate-400 hover:text-slate-200 transition-colors shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="overflow-y-auto p-5">
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap font-mono">
            {source.text || source.preview}
          </p>
        </div>
        <div className="px-5 py-2.5 border-t border-white/10 bg-slate-900/40 shrink-0">
          <p className="text-[10px] text-slate-500">Exact retrieved context used to ground this answer.</p>
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  );
}

function SourcePanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<Source | null>(null);
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mt-2 rounded-xl overflow-hidden border border-white/5">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-slate-800/70 hover:bg-slate-700/60 transition-colors text-[11px] text-slate-400 font-medium"
      >
        <span className="flex items-center gap-1.5">
          <FileText className="w-3 h-3 text-blue-400" />
          {sources.length} Source Document{sources.length > 1 ? 's' : ''} Retrieved
        </span>
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden bg-slate-900/60 divide-y divide-white/5">
            {sources.map((s, i) => (
              <button
                key={i}
                onClick={() => setActive(s)}
                title="View full source context"
                className="w-full text-left px-3 py-2.5 hover:bg-slate-800/60 transition-colors group/src"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-mono bg-blue-500/10 border border-blue-500/20 text-blue-300 rounded px-1.5 py-0.5">chunk {s.chunk}</span>
                  {s.location && (
                    <span className="text-[10px] font-mono bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 rounded px-1.5 py-0.5">{s.location}</span>
                  )}
                  <span className="text-xs font-semibold text-slate-300 truncate">{s.file}</span>
                  <span className="ml-auto text-[10px] text-slate-600 group-hover/src:text-blue-400 transition-colors shrink-0">View →</span>
                </div>
                <p className="text-[10px] text-slate-500 leading-relaxed italic line-clamp-2">"{s.preview}..."</p>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {active && <SourceModal source={active} onClose={() => setActive(null)} />}
      </AnimatePresence>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handle = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={handle}
      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-slate-700 text-slate-500 hover:text-slate-300">
      {copied ? <Check className="w-3 h-3 text-green-400" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

const INITIAL_MSG: Message = {
  role: 'ai',
  content: '## Hello! 👋\n\nI am your **Enterprise RAG** assistant. Upload your documents and I\'ll answer any questions with **structured, detailed responses**.',
  timestamp: new Date().toISOString(),
};

export default function ChatInterface({
  selectedModel,
  selectedProvider,
  currentSessionId,
  onSessionChange,
  onSessionSaved,
}: {
  selectedModel: string;
  selectedProvider?: string;
  currentSessionId: string | null;
  onSessionChange: (id: string | null) => void;
  onSessionSaved: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([INITIAL_MSG]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Mirror the open session id for use inside the async stream handler (closures
  // would otherwise capture a stale value). `justCreatedRef` suppresses the
  // load-on-change effect when WE create the session locally after the first
  // message — its messages are already on screen and must not be wiped.
  const sessionIdRef = useRef<string | null>(currentSessionId);
  const justCreatedRef = useRef(false);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, loading]);

  // Load history when the open session changes (or reset to a fresh chat).
  useEffect(() => {
    sessionIdRef.current = currentSessionId;
    if (justCreatedRef.current) {
      justCreatedRef.current = false;
      return; // session was just created locally; keep current messages
    }
    if (!currentSessionId) {
      setMessages([{ ...INITIAL_MSG, timestamp: new Date().toISOString() }]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get(`/api/sessions/${currentSessionId}/messages`);
        if (cancelled) return;
        const loaded: Message[] = (res.data.messages || []).map((m: {
          role: 'user' | 'ai'; content: string; sources?: Source[]; created_at?: number;
        }) => ({
          role: m.role,
          content: m.content,
          timestamp: new Date((m.created_at || 0) * 1000).toISOString(),
          sources: m.sources || [],
        }));
        setMessages(loaded.length ? loaded : [{ ...INITIAL_MSG, timestamp: new Date().toISOString() }]);
      } catch {
        if (!cancelled) setMessages([{ ...INITIAL_MSG, timestamp: new Date().toISOString() }]);
      }
    })();
    return () => { cancelled = true; };
  }, [currentSessionId]);

  // Patch the last message in place (used to grow the streaming AI reply).
  const patchLastMessage = (patch: Partial<Message>) => {
    setMessages(prev => {
      const copy = [...prev];
      copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
      return copy;
    });
  };

  const handleSend = async (text?: string) => {
    const userMsg = (text ?? input).trim();
    if (!userMsg) return;
    setInput('');

    const historyToSend = messages
      .filter(m => m.role === 'user' || m.role === 'ai')
      .map(m => ({ role: m.role, content: m.content }));

    const userMessage: Message = { role: 'user', content: userMsg, timestamp: new Date().toISOString() };
    // Append the user message + an empty AI placeholder we'll stream into.
    const aiPlaceholder: Message = { role: 'ai', content: '', timestamp: new Date().toISOString(), sources: [] };
    setMessages(prev => [...prev, userMessage, aiPlaceholder]);
    setLoading(true);

    try {
      const resp = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMsg,
          model_name: selectedModel,
          provider: selectedProvider,
          chat_history: historyToSend,
        }),
      });
      if (!resp.ok) {
        // The endpoint normally streams errors as `error` events (HTTP 200),
        // so a non-OK status means it failed before streaming — surface its
        // detail if there is one rather than a generic message.
        let detail = '';
        try {
          const body = await resp.json();
          detail = body?.detail || '';
        } catch { /* not JSON — fall back to the status text */ }
        throw new Error(detail || `Server error (${resp.status} ${resp.statusText || 'request failed'}).`);
      }
      if (!resp.body) throw new Error('The server returned an empty response stream.');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let answer = '';
      let answerSources: Source[] = [];

      // Read the SSE stream: events are separated by a blank line, each line
      // prefixed with "data: ". We grow the AI message as tokens arrive.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          let evt: { type: string; content?: string; sources?: Source[]; detail?: string };
          try { evt = JSON.parse(payload); } catch { continue; }

          if (evt.type === 'sources') {
            answerSources = evt.sources || [];
            patchLastMessage({ sources: answerSources });
          } else if (evt.type === 'notice') {
            // A provider fallback happened — show a subtle heads-up above the answer.
            patchLastMessage({ notice: evt.content || '' });
          } else if (evt.type === 'token') {
            answer += evt.content || '';
            patchLastMessage({ content: answer });
          } else if (evt.type === 'error') {
            answer = `**Error:** ${evt.detail || 'Something went wrong.'}`;
            patchLastMessage({ content: answer });
          }
        }
      }
      if (!answer) {
        patchLastMessage({ content: '**Error:** Empty response from the server.' });
      } else {
        // Persist the exchange to chat history (best-effort). Create a session
        // on the first message, titled from the user's question.
        try {
          let sid = sessionIdRef.current;
          if (!sid) {
            const title = userMsg.length > 60 ? userMsg.slice(0, 57) + '…' : userMsg;
            const res = await api.post('/api/sessions', { title });
            sid = res.data?.id || null;
            if (sid) {
              sessionIdRef.current = sid;
              justCreatedRef.current = true;
              onSessionChange(sid);
            }
          }
          if (sid) {
            await api.post(`/api/sessions/${sid}/messages`, { role: 'user', content: userMsg });
            await api.post(`/api/sessions/${sid}/messages`, { role: 'ai', content: answer, sources: answerSources });
            onSessionSaved();
          }
        } catch { /* history is best-effort; never block the chat */ }
      }
    } catch (err) {
      // Distinguish a server-reported problem (has a message) from a raw
      // network failure (fetch throws a TypeError with no useful detail).
      const msg = err instanceof Error ? err.message : '';
      const isNetwork = !msg || /failed to fetch|networkerror|load failed/i.test(msg);
      patchLastMessage({
        content: isNetwork
          ? "**Error:** Couldn't reach the backend. Make sure it's running, then try again."
          : `**Error:** ${msg}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setMessages([{ ...INITIAL_MSG, timestamp: new Date().toISOString() }]);
    sessionIdRef.current = null;
    if (currentSessionId) onSessionChange(null); // signal App to start a fresh chat
  };

  // Export the visible conversation as a Markdown file (skips the greeting).
  const handleExport = () => {
    const convo = messages.filter((m, i) => !(i === 0 && m.role === 'ai'));
    if (convo.length === 0) return;
    const lines: string[] = [`# Conversation — ${new Date().toLocaleString()}`, ''];
    for (const m of convo) {
      lines.push(m.role === 'user' ? '### 🧑 You' : '### 🤖 Assistant', '', m.content, '');
      if (m.role === 'ai' && m.sources && m.sources.length) {
        lines.push('**Sources:**');
        for (const s of m.sources) {
          const loc = s.location ? `, ${s.location}` : '';
          lines.push(`- \`${s.file}\` (chunk ${s.chunk}${loc})`);
        }
        lines.push('');
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `rag-chat-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const showExamples = messages.length === 1;
  const canExport = messages.some((m, i) => !(i === 0 && m.role === 'ai'));

  return (
    <div className="flex flex-col flex-1 h-full bg-slate-900/40 relative rounded-2xl overflow-hidden shadow-2xl">
      {/* Header */}
      <div className="px-5 py-4 border-b border-white/10 bg-slate-900/60 backdrop-blur-md flex items-center justify-between z-10 shadow-sm shrink-0">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500/20 rounded-lg border border-indigo-500/20">
            <Sparkles className="w-4 h-4 text-indigo-400" />
          </div>
          <h2 className="font-semibold text-slate-200 text-sm">Retrieval Augmented Generation</h2>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-[11px] px-3 py-1 flex items-center gap-2 rounded-full bg-slate-800 border border-slate-700 font-medium text-slate-300">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            {selectedModel}
          </div>
          <button onClick={handleExport} disabled={!canExport} title="Export chat as Markdown"
            className="p-2 rounded-lg hover:bg-slate-700/60 text-slate-500 hover:text-blue-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
            <Download className="w-3.5 h-3.5" />
          </button>
          <button onClick={handleClear} title="Clear chat"
            className="p-2 rounded-lg hover:bg-slate-700/60 text-slate-500 hover:text-red-400 transition-colors">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5 scroll-smooth">

        {/* Example queries */}
        <AnimatePresence>
          {showExamples && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mb-2">
              <p className="text-xs text-slate-500 text-center mb-3 font-medium">Try an example question:</p>
              <div className="flex flex-wrap gap-2 justify-center">
                {EXAMPLE_QUERIES.map(q => (
                  <button key={q} onClick={() => handleSend(q)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 hover:border-blue-500/40 hover:bg-blue-500/10 hover:text-blue-300 text-slate-400 transition-all">
                    {q}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {messages.map((msg, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === 'user' ? 'ml-auto flex-row-reverse max-w-[80%]' : 'max-w-[96%]'}`}>
              <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border shadow-md
                ${msg.role === 'user' ? 'bg-slate-700 border-slate-600 text-slate-200' : 'bg-gradient-to-br from-blue-500/20 to-indigo-600/20 border-blue-500/30 text-blue-400'}`}>
                {msg.role === 'user' ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>

              <div className="flex flex-col gap-1 flex-1 min-w-0 group">
                {/* Timestamp */}
                <span className={`text-[10px] text-slate-600 ${msg.role === 'user' ? 'text-right' : 'text-left'}`}>
                  {formatTime(msg.timestamp)}
                </span>

                <div className={`p-4 rounded-2xl text-sm leading-relaxed shadow-sm relative
                  ${msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-tr-sm'
                    : 'glass-panel rounded-tl-sm text-slate-200 border-white/5'}`}>
                  {msg.role === 'ai' && msg.content && (
                    <div className="absolute top-2 right-2">
                      <CopyButton text={msg.content} />
                    </div>
                  )}
                  {msg.role === 'ai' && msg.notice && (
                    <div className="mb-2 flex items-start gap-1.5 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 rounded-lg px-2.5 py-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
                      <span>{msg.notice}</span>
                    </div>
                  )}
                  {msg.role === 'ai' ? (
                    msg.content ? (
                      <div className="prose prose-invert prose-sm max-w-none
                        prose-headings:text-slate-100 prose-headings:font-bold
                        prose-strong:text-slate-100 prose-code:text-blue-300
                        prose-code:bg-slate-800 prose-code:px-1 prose-code:rounded
                        prose-ul:text-slate-200 prose-ol:text-slate-200
                        prose-li:marker:text-blue-400 prose-p:text-slate-200">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{msg.content}</ReactMarkdown>
                      </div>
                    ) : (
                      // Empty AI bubble = streaming hasn't produced a token yet.
                      <div className="flex items-center gap-1.5 py-0.5">
                        <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                        <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                        <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    )
                  ) : msg.content}
                </div>

                {/* Source documents panel */}
                {msg.role === 'ai' && msg.sources && msg.sources.length > 0 && (
                  <SourcePanel sources={msg.sources} />
                )}
              </div>
            </motion.div>
          ))}

          {/* Standalone loading dots only if there's no AI placeholder bubble
              already streaming (it shows its own inline dots). */}
          {loading && messages[messages.length - 1]?.role !== 'ai' && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 max-w-[80%]">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500/20 to-indigo-600/20 border border-blue-500/30 flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4 text-blue-400" />
              </div>
              <div className="glass-panel p-4 py-5 rounded-2xl rounded-tl-sm flex items-center gap-1.5 border-white/5">
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Input */}
      <div className="p-4 bg-slate-900/90 backdrop-blur-md border-t border-white/5 z-10 shrink-0">
        <form onSubmit={(e) => { e.preventDefault(); handleSend(); }}
          className="bg-slate-800/80 border border-slate-700/80 p-1.5 rounded-2xl flex items-center shadow-lg focus-within:border-blue-500/50 focus-within:ring-2 focus-within:ring-blue-500/20 transition-all">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="Ask questions about your uploaded documents..."
            className="flex-1 bg-transparent border-none outline-none px-4 text-slate-200 text-sm placeholder:text-slate-500 h-10" />
          <button type="submit" disabled={!input.trim() || loading}
            className="bg-blue-600 hover:bg-blue-500 text-white p-2.5 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed group shadow-md shadow-blue-500/20 active:scale-[0.97]">
            <Send className="w-4 h-4 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
          </button>
        </form>
        <p className="text-[10px] text-slate-500 font-medium text-center mt-2">
          Responses are grounded strictly in your uploaded documents.
        </p>
      </div>
    </div>
  );
}
