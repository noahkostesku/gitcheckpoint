import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Save,
  GitFork,
  GitMerge,
  GitCompare,
  Upload,
  Share2,
  X,
  Loader2,
} from "lucide-react";
import { api } from "../lib/api";

function CommandButton({ icon: Icon, label, variant = "default", onClick, loading }) {
  const styles = {
    default: "text-text-secondary hover:text-accent hover:bg-accent-light",
    warning: "text-text-secondary hover:text-warning hover:bg-warning-light",
    blue: "text-text-secondary hover:text-accent hover:bg-accent-light",
  };
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${styles[variant]} disabled:opacity-40`}
    >
      {loading ? <Loader2 size={13} className="animate-spin" /> : <Icon size={13} />}
      {label}
    </button>
  );
}

function Modal({ title, onClose, children }) {
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
        className="bg-white border border-border rounded-2xl p-5 w-80 max-w-[90vw] shadow-xl"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-text-primary capitalize">{title}</h3>
          <button onClick={onClose} className="text-text-muted hover:text-text-secondary">
            <X size={16} />
          </button>
        </div>
        {children}
      </motion.div>
    </motion.div>
  );
}

export default function ControlsBar({ threadId, threads, onRefresh, onShowDiff }) {
  const [modal, setModal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const [checkpointLabel, setCheckpointLabel] = useState("");
  const [forkName, setForkName] = useState("");
  const [forkSha, setForkSha] = useState("");
  const [mergeSource, setMergeSource] = useState("");
  const [mergeTarget, setMergeTarget] = useState("");

  async function runAction(fn) {
    setLoading(true);
    setResult(null);
    try {
      const res = await fn();
      setResult({ ok: true, text: res.result || "Done" });
      onRefresh();
    } catch (err) {
      setResult({ ok: false, text: err.message });
    }
    setLoading(false);
  }

  function closeModal() {
    setModal(null);
    setResult(null);
  }

  return (
    <>
      <div className="flex items-center gap-1 px-4 py-2 border-t border-border bg-white overflow-x-auto">
        <CommandButton icon={Save} label="Checkpoint" onClick={() => setModal("checkpoint")} />
        <CommandButton icon={GitFork} label="Fork" variant="warning" onClick={() => setModal("fork")} />
        <CommandButton icon={GitMerge} label="Merge" variant="warning" onClick={() => setModal("merge")} />
        <CommandButton icon={GitCompare} label="Diff" onClick={() => onShowDiff && onShowDiff()} />
        <div className="w-px h-4 bg-border mx-1" />
        <CommandButton
          icon={Upload}
          label="Push"
          variant="blue"
          onClick={() => runAction(() => api.pushToGithub(threadId))}
          loading={loading && !modal}
        />
        <CommandButton
          icon={Share2}
          label="Gist"
          variant="blue"
          onClick={() => runAction(() => api.shareGist(threadId))}
          loading={loading && !modal}
        />
      </div>

      {/* Result toast */}
      <AnimatePresence>
        {result && !modal && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className={`absolute bottom-16 left-1/2 -translate-x-1/2 px-4 py-2.5 rounded-xl text-xs font-medium z-40 shadow-lg ${
              result.ok
                ? "bg-success-light text-success border border-success/10"
                : "bg-error-light text-error border border-error/10"
            }`}
          >
            {result.text.length > 100 ? result.text.slice(0, 100) + "..." : result.text}
            <button onClick={() => setResult(null)} className="ml-2 opacity-60 hover:opacity-100">
              <X size={10} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Modals */}
      <AnimatePresence>
        {modal === "checkpoint" && (
          <Modal title="Create Checkpoint" onClose={closeModal}>
            <div className="space-y-3">
              <input
                type="text"
                value={checkpointLabel}
                onChange={(e) => setCheckpointLabel(e.target.value)}
                placeholder="Label for this checkpoint"
                className="w-full border border-border rounded-xl px-3 py-2.5 text-sm text-text-primary placeholder-text-muted outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10"
                autoFocus
                onKeyDown={(e) =>
                  e.key === "Enter" &&
                  runAction(() => api.checkpoint(threadId, checkpointLabel.trim())).then(closeModal)
                }
              />
              <div className="flex justify-end gap-2">
                <button onClick={closeModal} className="text-xs font-medium text-text-muted hover:text-text-secondary px-3 py-1.5">
                  Cancel
                </button>
                <button
                  onClick={() =>
                    runAction(() => api.checkpoint(threadId, checkpointLabel.trim())).then(closeModal)
                  }
                  disabled={!checkpointLabel.trim() || loading}
                  className="text-xs font-medium text-white bg-accent hover:bg-accent-hover px-3 py-1.5 rounded-lg disabled:opacity-40 flex items-center gap-1"
                >
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  Save
                </button>
              </div>
            </div>
            {result && (
              <p className={`text-xs mt-2 ${result.ok ? "text-success" : "text-error"}`}>{result.text}</p>
            )}
          </Modal>
        )}

        {modal === "fork" && (
          <Modal title="Fork Thread" onClose={closeModal}>
            <div className="space-y-3">
              <input
                type="text"
                value={forkName}
                onChange={(e) => setForkName(e.target.value)}
                placeholder="New thread name"
                className="w-full border border-border rounded-xl px-3 py-2.5 text-sm text-text-primary placeholder-text-muted outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10"
                autoFocus
              />
              <input
                type="text"
                value={forkSha}
                onChange={(e) => setForkSha(e.target.value)}
                placeholder="Checkpoint SHA (blank for HEAD)"
                className="w-full border border-border rounded-xl px-3 py-2.5 text-sm font-mono text-text-primary placeholder-text-muted outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10"
              />
              <p className="text-xs text-text-muted">
                Forking from <span className="font-medium text-text-secondary">{threadId}</span>
              </p>
              <div className="flex justify-end gap-2">
                <button onClick={closeModal} className="text-xs font-medium text-text-muted hover:text-text-secondary px-3 py-1.5">
                  Cancel
                </button>
                <button
                  onClick={() =>
                    runAction(() => api.fork(threadId, forkSha.trim() || "HEAD", forkName.trim())).then(closeModal)
                  }
                  disabled={!forkName.trim() || loading}
                  className="text-xs font-medium text-white bg-warning hover:bg-warning/90 px-3 py-1.5 rounded-lg disabled:opacity-40 flex items-center gap-1"
                >
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  Fork
                </button>
              </div>
            </div>
            {result && (
              <p className={`text-xs mt-2 ${result.ok ? "text-success" : "text-error"}`}>{result.text}</p>
            )}
          </Modal>
        )}

        {modal === "merge" && (
          <Modal title="Merge Threads" onClose={closeModal}>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-text-secondary block mb-1.5">Source thread</label>
                <select
                  value={mergeSource}
                  onChange={(e) => setMergeSource(e.target.value)}
                  className="w-full border border-border rounded-xl px-3 py-2.5 text-sm text-text-primary outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10 bg-white"
                >
                  <option value="">Select source...</option>
                  {threads.map((t) => (
                    <option key={t.name} value={t.name}>{t.name}</option>
                  ))}
                </select>
              </div>
              <div className="text-center text-text-muted text-xs">merge into</div>
              <div>
                <label className="text-xs font-medium text-text-secondary block mb-1.5">Target thread</label>
                <select
                  value={mergeTarget || threadId}
                  onChange={(e) => setMergeTarget(e.target.value)}
                  className="w-full border border-border rounded-xl px-3 py-2.5 text-sm text-text-primary outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/10 bg-white"
                >
                  {threads.map((t) => (
                    <option key={t.name} value={t.name}>{t.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={closeModal} className="text-xs font-medium text-text-muted hover:text-text-secondary px-3 py-1.5">
                  Cancel
                </button>
                <button
                  onClick={() =>
                    runAction(() => api.merge(mergeSource, mergeTarget || threadId)).then(closeModal)
                  }
                  disabled={!mergeSource || loading}
                  className="text-xs font-medium text-white bg-warning hover:bg-warning/90 px-3 py-1.5 rounded-lg disabled:opacity-40 flex items-center gap-1"
                >
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  Merge
                </button>
              </div>
            </div>
            {result && (
              <p className={`text-xs mt-2 ${result.ok ? "text-success" : "text-error"}`}>{result.text}</p>
            )}
          </Modal>
        )}
      </AnimatePresence>
    </>
  );
}
