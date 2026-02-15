import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, GitCompare, Loader2 } from "lucide-react";
import { api } from "../lib/api";

export default function DiffViewer({ threadId, onClose }) {
  const [shaA, setShaA] = useState("");
  const [shaB, setShaB] = useState("");
  const [diffResult, setDiffResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleDiff() {
    if (!shaA.trim() || !shaB.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDiff(threadId, shaA.trim(), shaB.trim());
      setDiffResult(data.result);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }

  function renderDiffLines(text) {
    return text.split("\n").map((line, i) => {
      let cls = "text-gray-400";
      if (line.startsWith("+")) cls = "text-neon bg-neon/5";
      else if (line.startsWith("-")) cls = "text-red bg-red/5";
      else if (line.startsWith("@")) cls = "text-blue";
      return (
        <div key={i} className={`px-3 py-0.5 font-mono text-xs ${cls}`}>
          {line || " "}
        </div>
      );
    });
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="bg-terminal-surface border border-terminal-border rounded-lg w-[600px] max-w-[90vw] max-h-[80vh] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-terminal-border">
          <div className="flex items-center gap-2">
            <GitCompare size={14} className="text-neon" />
            <span className="text-sm font-mono text-gray-200">
              diff <span className="text-amber">{threadId}</span>
            </span>
          </div>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300">
            <X size={14} />
          </button>
        </div>

        {/* SHA inputs */}
        <div className="px-4 py-3 flex items-center gap-2 border-b border-terminal-border">
          <input
            type="text"
            value={shaA}
            onChange={(e) => setShaA(e.target.value)}
            placeholder="SHA A"
            className="flex-1 bg-terminal-bg border border-terminal-border-light rounded px-2 py-1.5 text-xs font-mono text-gray-300 placeholder-gray-600 outline-none focus:border-neon/30"
          />
          <span className="text-gray-600 font-mono text-xs">..</span>
          <input
            type="text"
            value={shaB}
            onChange={(e) => setShaB(e.target.value)}
            placeholder="SHA B"
            className="flex-1 bg-terminal-bg border border-terminal-border-light rounded px-2 py-1.5 text-xs font-mono text-gray-300 placeholder-gray-600 outline-none focus:border-neon/30"
          />
          <button
            onClick={handleDiff}
            disabled={loading || !shaA.trim() || !shaB.trim()}
            className="px-3 py-1.5 rounded text-xs font-mono text-neon hover:bg-neon/10 disabled:opacity-40 flex items-center gap-1"
          >
            {loading ? <Loader2 size={10} className="animate-spin" /> : <GitCompare size={10} />}
            diff
          </button>
        </div>

        {/* Diff output */}
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="px-4 py-3 text-xs font-mono text-red">
              Error: {error}
            </div>
          )}
          {diffResult && (
            <div className="py-1">{renderDiffLines(diffResult)}</div>
          )}
          {!diffResult && !error && (
            <div className="flex items-center justify-center h-32 text-xs text-gray-600 font-mono">
              enter two SHAs to compare
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
