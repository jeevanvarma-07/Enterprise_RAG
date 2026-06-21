import React from 'react';
import { Database, UploadCloud, MessageSquare, Activity, GitBranch, Cpu } from 'lucide-react';
import { motion } from 'framer-motion';

export default function Sidebar({ activeTab, setActiveTab }: { activeTab: string, setActiveTab: (tab: string) => void }) {
    return (
        <motion.aside
            initial={{ x: -20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            className="w-20 lg:w-64 glass-panel border-r border-white/5 flex flex-col justify-between py-6 px-4 z-20 shrink-0"
        >
            <div>
                <div className="flex items-center gap-3 mb-10 px-2 mt-4 lg:mt-0">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20 shrink-0">
                        <Activity className="text-white w-6 h-6" />
                    </div>
                    <h2 className="text-xl font-bold hidden lg:block text-gradient">Enterprise</h2>
                </div>

                <nav className="space-y-1">
                    <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 mb-2 hidden lg:block font-semibold">Workspace</p>
                    <NavItem icon={<MessageSquare />} label="Chat Sessions" active={activeTab === 'chat'} onClick={() => setActiveTab('chat')} />
                    <NavItem icon={<Database />} label="Vector Store" active={activeTab === 'vector'} onClick={() => setActiveTab('vector')} />
                    <NavItem icon={<UploadCloud />} label="Data Sources" active={activeTab === 'data'} onClick={() => setActiveTab('data')} />

                    <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 mt-4 mb-2 hidden lg:block font-semibold pt-2 border-t border-white/5">System</p>
                    <NavItem icon={<GitBranch />} label="AI Pipeline" active={activeTab === 'pipeline'} onClick={() => setActiveTab('pipeline')} />
                    <NavItem icon={<Cpu />} label="Architecture" active={activeTab === 'arch'} onClick={() => setActiveTab('arch')} />
                </nav>
            </div>

            <div className="mt-auto pt-4 border-t border-white/5 px-2 hidden lg:block">
                <p className="text-xs text-slate-500 text-center">v1.0.0 Enterprise RAG</p>
            </div>
        </motion.aside>
    );
}

function NavItem({ icon, label, active = false, onClick }: { icon: React.ReactNode, label: string, active?: boolean, onClick?: () => void }) {
    return (
        <button onClick={onClick} className={`w-full flex items-center lg:justify-start justify-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 group
      ${active ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'}`}>
            <span className="shrink-0 w-4 h-4">{icon}</span>
            <span className="font-medium hidden lg:block text-sm">{label}</span>
        </button>
    );
}
