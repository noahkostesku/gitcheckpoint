import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  GitBranch,
  Plus,
  ChevronRight,
  Hash,
  RefreshCw,
  Loader2,
} from "lucide-react";

export default function ThreadSidebar({
  threads,
  currentThread,
  onSelectThread,
  onNewThread,
  onRefresh,
  loading,
}) {
  const [newName, setNewName] = useState("");
  const [showNew, setShowNew] = useState(false);

  function handleCreate(e) {
    e.preventDefault();
    const name = newName.trim().replace(/\s+/g, "-").toLowerCase();
    if (!name) return;
    onNewThread(name);
    setNewName("");
    setShowNew(false);
  }

  return (
    <div className="flex flex-col h-full bg-terminal-surface border-r border-terminal-border">
      {/* Header */}
      <div className="px-3 py-3 border-b border-terminal-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch size={14} className="text-neon" />
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Threads
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            className="p-1 rounded text-gray-600 hover:text-gray-300 transition-colors"
            title="Refresh"
          >
            {loading ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <RefreshCw size={12} />
            )}
          </button>
          <button
            onClick={() => setShowNew(!showNew)}
            className="p-1 rounded text-gray-600 hover:text-neon transition-colors"
            title="New thread"
          >
            <Plus size={12} />
          </button>
        </div>
      </div>

      {/* New thread form */}
      <AnimatePresence>
        {showNew && (
          <motion.form
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            onSubmit={handleCreate}
            className="px-3 py-2 border-b border-terminal-border overflow-hidden"
          >
            <div className="flex items-center gap-1.5 bg-terminal-bg border border-terminal-border-light rounded px-2 py-1.5">
              <span className="font-mono text-neon text-[10px]">+</span>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="thread-name"
                className="flex-1 bg-transparent border-none outline-none text-xs font-mono text-gray-300 placeholder-gray-600"
                autoFocus
              />
            </div>
          </motion.form>
        )}
      </AnimatePresence>

      {/* Thread list */}
      <div className="flex-1 overflow-y-auto py-1">
        {threads.length === 0 && !loading && (
          <div className="px-3 py-8 text-center">
            <p className="text-xs text-gray-600 font-mono">no threads yet</p>
            <p className="text-[10px] text-gray-700 mt-1">
              start chatting to create one
            </p>
          </div>
        )}

        {threads.map((thread) => {
          const isActive = thread.name === currentThread;
          return (
            <button
              key={thread.name}
              onClick={() => onSelectThread(thread.name)}
              className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-all group ${
                isActive
                  ? "bg-neon/5 border-l-2 border-neon"
                  : "border-l-2 border-transparent hover:bg-terminal-border/30"
              }`}
            >
              <Hash
                size={12}
                className={isActive ? "text-neon" : "text-gray-600 group-hover:text-gray-400"}
              />
              <div className="flex-1 min-w-0">
                <div
                  className={`text-xs font-mono truncate ${
                    isActive
                      ? "text-neon neon-text-glow"
                      : "text-gray-400 group-hover:text-gray-200"
                  }`}
                >
                  {thread.name}
                </div>
                {thread.commits > 0 && (
                  <div className="text-[10px] text-gray-600 font-mono">
                    {thread.commits} commit{thread.commits !== 1 ? "s" : ""}
                  </div>
                )}
              </div>
              {isActive && (
                <ChevronRight size={10} className="text-neon flex-shrink-0" />
              )}
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-terminal-border">
        <div className="text-[10px] font-mono text-gray-700">
          {threads.length} thread{threads.length !== 1 ? "s" : ""}
        </div>
      </div>
    </div>
  );
}
