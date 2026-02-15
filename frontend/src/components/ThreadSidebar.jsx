import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  GitBranch,
  Plus,
  RefreshCw,
  Loader2,
} from "lucide-react";

function formatName(name) {
  return name
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

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
    <div className="flex flex-col h-full bg-surface-secondary border-r border-border">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <span className="text-xs font-semibold text-text-secondary tracking-wide">
          Threads
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={onRefresh}
            className="p-1.5 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-tertiary transition-colors"
            title="Refresh"
          >
            {loading ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCw size={13} />
            )}
          </button>
          <button
            onClick={() => setShowNew(!showNew)}
            className="p-1.5 rounded-md text-text-muted hover:text-accent hover:bg-accent-light transition-colors"
            title="New thread"
          >
            <Plus size={13} />
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
            className="px-4 py-2 border-b border-border overflow-hidden"
          >
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New thread name..."
              className="w-full bg-white border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10"
              autoFocus
            />
          </motion.form>
        )}
      </AnimatePresence>

      {/* Thread list */}
      <div className="flex-1 overflow-y-auto py-1">
        {threads.length === 0 && !loading && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-text-muted">No threads yet</p>
            <p className="text-xs text-text-muted mt-1">
              Start chatting to create one
            </p>
          </div>
        )}

        {threads.map((thread) => {
          const isActive = thread.name === currentThread;
          return (
            <button
              key={thread.name}
              onClick={() => onSelectThread(thread.name)}
              className={`w-full text-left px-4 py-2.5 flex items-center gap-3 transition-all group ${
                isActive
                  ? "bg-accent-light border-l-2 border-accent"
                  : "border-l-2 border-transparent hover:bg-surface-tertiary"
              }`}
            >
              <GitBranch
                size={14}
                className={isActive ? "text-accent" : "text-text-muted group-hover:text-text-secondary"}
              />
              <div className="flex-1 min-w-0">
                <div
                  className={`text-sm truncate ${
                    isActive
                      ? "text-accent font-medium"
                      : "text-text-primary group-hover:text-text-primary"
                  }`}
                >
                  {formatName(thread.name)}
                </div>
                {thread.commits > 0 && (
                  <div className="text-xs text-text-muted">
                    {thread.commits} checkpoint{thread.commits !== 1 ? "s" : ""}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-border">
        <div className="text-xs text-text-muted">
          {threads.length} thread{threads.length !== 1 ? "s" : ""}
        </div>
      </div>
    </div>
  );
}
