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
      let cls = "text-text-secondary";
      if (line.startsWith("+")) cls = "text-success bg-success-light";
      else if (line.startsWith("-")) cls = "text-error bg-error-light";
      else if (line.startsWith("@")) cls = "text-accent bg-accent-light";
      return (
        <div key={i} className={`px-4 py-0.5 font-mono text-xs ${cls}`}>
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.96, opacity: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="bg-white border border-border rounded-2xl w-[600px] max-w-[90vw] max-h-[80vh] flex flex-col shadow-xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <GitCompare size={15} className="text-accent" />
            <span className="text-sm font-semibold text-text-primary">
              Diff — <span className="font-mono text-text-secondary">{threadId}</span>
            </span>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-secondary">
            <X size={16} />
          </button>
        </div>

        {/* SHA inputs */}
        <div className="px-5 py-3 flex items-center gap-2 border-b border-border">
          <input
            type="text"
            value={shaA}
            onChange={(e) => setShaA(e.target.value)}
            placeholder="SHA A"
            className="flex-1 border border-border rounded-xl px-3 py-2 text-xs font-mono text-text-primary placeholder-text-muted outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10"
          />
          <span className="text-text-muted text-xs">..</span>
          <input
            type="text"
            value={shaB}
            onChange={(e) => setShaB(e.target.value)}
            placeholder="SHA B"
            className="flex-1 border border-border rounded-xl px-3 py-2 text-xs font-mono text-text-primary placeholder-text-muted outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10"
          />
          <button
            onClick={handleDiff}
            disabled={loading || !shaA.trim() || !shaB.trim()}
            className="px-3 py-2 rounded-xl text-xs font-medium text-white bg-accent hover:bg-accent-hover disabled:opacity-40 flex items-center gap-1"
          >
            {loading ? <Loader2 size={11} className="animate-spin" /> : <GitCompare size={11} />}
            Compare
          </button>
        </div>

        {/* Diff output */}
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="px-5 py-3 text-xs text-error">
              Error: {error}
            </div>
          )}
          {diffResult && (
            <div className="py-1">{renderDiffLines(diffResult)}</div>
          )}
          {!diffResult && !error && (
            <div className="flex items-center justify-center h-32 text-sm text-text-muted">
              Enter two SHAs to compare
            </div>
          )}
        </div>
      </motion.div>
    </motion.div>
  );
}
