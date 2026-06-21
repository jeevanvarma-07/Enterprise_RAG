import { useState, useEffect, useCallback } from 'react';
import { MessageSquare, Plus, Trash2, Pencil, Check, X, History } from 'lucide-react';
import api from '../api';

interface SessionMeta {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
}

/**
 * Sidebar panel listing saved chat sessions (SQLite-backed). Lets the user
 * start a new chat, switch between past conversations, rename, and delete them.
 * `refreshKey` is bumped by the parent after a message is saved so counts/titles
 * and ordering stay current.
 */
export default function SessionsPanel({
  currentSessionId,
  onSelect,
  onNew,
  refreshKey,
}: {
  currentSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  refreshKey: number;
}) {
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  const fetchSessions = useCallback(async () => {
    try {
      const res = await api.get('/api/sessions');
      setSessions(res.data.sessions || []);
    } catch {
      setSessions([]);
    }
  }, []);

  useEffect(() => { fetchSessions(); }, [fetchSessions, refreshKey]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try { await api.delete(`/api/sessions/${id}`); } catch { /* ignore */ }
    if (id === currentSessionId) onNew();
    fetchSessions();
  };

  const startRename = (s: SessionMeta, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(s.id);
    setEditTitle(s.title);
  };

  const saveRename = async (id: string, e: React.MouseEvent | React.FormEvent) => {
    e.stopPropagation();
    const t = editTitle.trim();
    if (t) { try { await api.patch(`/api/sessions/${id}`, { title: t }); } catch { /* ignore */ } }
    setEditingId(null);
    fetchSessions();
  };

  const cancelRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(null);
  };

  return (
    <div className="glass-panel rounded-2xl p-4 flex flex-col min-h-0 max-h-56 shrink-0">
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div className="flex items-center gap-2">
          <History className="w-3.5 h-3.5 text-indigo-400" />
          <h3 className="font-semibold text-slate-200 text-sm">Chat History</h3>
        </div>
        <button
          onClick={onNew}
          title="New chat"
          className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-lg bg-blue-600/80 hover:bg-blue-500 text-white transition-colors"
        >
          <Plus className="w-3 h-3" /> New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-1 min-h-0 -mr-1 pr-1">
        {sessions.length === 0 ? (
          <p className="text-xs text-slate-500 italic text-center py-4">No saved chats yet.</p>
        ) : (
          sessions.map((s) => {
            const active = s.id === currentSessionId;
            return (
              <div
                key={s.id}
                onClick={() => onSelect(s.id)}
                className={`group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer border transition-colors ${
                  active
                    ? 'bg-blue-500/15 border-blue-500/30'
                    : 'bg-slate-800/40 border-white/5 hover:bg-slate-800/80'
                }`}
              >
                <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${active ? 'text-blue-300' : 'text-slate-500'}`} />

                {editingId === s.id ? (
                  <form onSubmit={(e) => { e.preventDefault(); saveRename(s.id, e); }} className="flex-1 flex items-center gap-1">
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      className="flex-1 min-w-0 bg-slate-900/80 border border-slate-600 rounded px-1.5 py-0.5 text-xs text-slate-200 outline-none focus:border-blue-500"
                    />
                    <button type="submit" onClick={(e) => saveRename(s.id, e)} className="text-green-400 hover:text-green-300 shrink-0"><Check className="w-3.5 h-3.5" /></button>
                    <button type="button" onClick={cancelRename} className="text-slate-500 hover:text-slate-300 shrink-0"><X className="w-3.5 h-3.5" /></button>
                  </form>
                ) : (
                  <>
                    <span className="text-xs text-slate-300 truncate flex-1" title={s.title}>{s.title}</span>
                    <span className="text-[10px] text-slate-600 font-mono shrink-0">{s.message_count}</span>
                    <button onClick={(e) => startRename(s, e)} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-blue-400 transition-opacity shrink-0"><Pencil className="w-3 h-3" /></button>
                    <button onClick={(e) => handleDelete(s.id, e)} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity shrink-0"><Trash2 className="w-3 h-3" /></button>
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
