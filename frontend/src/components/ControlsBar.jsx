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
  ChevronRight,
  Loader2,
} from "lucide-react";
import { api } from "../lib/api";

function CommandButton({ icon: Icon, label, color = "neon", onClick, loading }) {
  const colors = {
    neon: "text-neon hover:bg-neon/10",
    amber: "text-amber hover:bg-amber/10",
    blue: "text-blue hover:bg-blue/10",
  };
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-mono transition-all ${colors[color]} disabled:opacity-40`}
    >
      {loading ? <Loader2 size={12} className="animate-spin" /> : <Icon size={12} />}
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        onClick={(e) => e.stopPropagation()}
        className="bg-terminal-surface border border-terminal-border rounded-lg p-4 w-80 max-w-[90vw]"
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-mono text-gray-200">
            <span className="text-neon">{">"}</span> {title}
          </h3>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300">
            <X size={14} />
          </button>
        </div>
        {children}
      </motion.div>
    </motion.div>
  );
}

export default function ControlsBar({
  threadId,
  threads,
  onRefresh,
  onShowDiff,
}) {
  const [modal, setModal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  // Form states
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
      <div className="flex items-center gap-1 px-3 py-2 border-t border-terminal-border bg-terminal-surface overflow-x-auto">
        <span className="text-[10px] font-mono text-gray-600 mr-1 flex-shrink-0">
          cmds:
        </span>
        <CommandButton
          icon={Save}
          label="checkpoint"
          onClick={() => setModal("checkpoint")}
        />
        <CommandButton
          icon={GitFork}
          label="fork"
          color="amber"
          onClick={() => setModal("fork")}
        />
        <CommandButton
          icon={GitMerge}
          label="merge"
          color="amber"
          onClick={() => setModal("merge")}
        />
        <CommandButton
          icon={GitCompare}
          label="diff"
          onClick={() => onShowDiff && onShowDiff()}
        />
        <div className="w-px h-4 bg-terminal-border mx-1" />
        <CommandButton
          icon={Upload}
          label="push"
          color="blue"
          onClick={() => runAction(() => api.pushToGithub(threadId))}
          loading={loading && !modal}
        />
        <CommandButton
          icon={Share2}
          label="gist"
          color="blue"
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
            className={`absolute bottom-16 left-1/2 -translate-x-1/2 px-3 py-2 rounded-lg text-xs font-mono z-40 ${
              result.ok
                ? "bg-neon/10 border border-neon/20 text-neon"
                : "bg-red/10 border border-red/20 text-red"
            }`}
          >
            {result.text.length > 100 ? result.text.slice(0, 100) + "..." : result.text}
            <button
              onClick={() => setResult(null)}
              className="ml-2 opacity-60 hover:opacity-100"
            >
              <X size={10} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Modals */}
      <AnimatePresence>
        {modal === "checkpoint" && (
          <Modal title="checkpoint" onClose={closeModal}>
            <div className="space-y-3">
              <input
                type="text"
                value={checkpointLabel}
                onChange={(e) => setCheckpointLabel(e.target.value)}
                placeholder="label for this checkpoint"
                className="w-full bg-terminal-bg border border-terminal-border-light rounded px-3 py-2 text-sm font-mono text-gray-300 placeholder-gray-600 outline-none focus:border-neon/30"
                autoFocus
                onKeyDown={(e) =>
                  e.key === "Enter" &&
                  runAction(() =>
                    api.checkpoint(threadId, checkpointLabel.trim())
                  ).then(closeModal)
                }
              />
              <div className="flex justify-end gap-2">
                <button onClick={closeModal} className="text-xs font-mono text-gray-500 hover:text-gray-300 px-2 py-1">
                  cancel
                </button>
                <button
                  onClick={() =>
                    runAction(() =>
                      api.checkpoint(threadId, checkpointLabel.trim())
                    ).then(closeModal)
                  }
                  disabled={!checkpointLabel.trim() || loading}
                  className="text-xs font-mono text-neon hover:bg-neon/10 px-2 py-1 rounded disabled:opacity-40 flex items-center gap-1"
                >
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  <ChevronRight size={10} /> save
                </button>
              </div>
            </div>
            {result && (
              <p className={`text-xs font-mono mt-2 ${result.ok ? "text-neon" : "text-red"}`}>
                {result.text}
              </p>
            )}
          </Modal>
        )}

        {modal === "fork" && (
          <Modal title="fork" onClose={closeModal}>
            <div className="space-y-3">
              <input
                type="text"
                value={forkName}
                onChange={(e) => setForkName(e.target.value)}
                placeholder="new-thread-name"
                className="w-full bg-terminal-bg border border-terminal-border-light rounded px-3 py-2 text-sm font-mono text-gray-300 placeholder-gray-600 outline-none focus:border-amber/30"
                autoFocus
              />
              <input
                type="text"
                value={forkSha}
                onChange={(e) => setForkSha(e.target.value)}
                placeholder="checkpoint SHA (leave blank for HEAD)"
                className="w-full bg-terminal-bg border border-terminal-border-light rounded px-3 py-2 text-sm font-mono text-gray-300 placeholder-gray-600 outline-none focus:border-amber/30"
              />
              <div className="text-[10px] text-gray-600 font-mono">
                forking from: <span className="text-amber">{threadId}</span>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={closeModal} className="text-xs font-mono text-gray-500 hover:text-gray-300 px-2 py-1">
                  cancel
                </button>
                <button
                  onClick={() =>
                    runAction(() =>
                      api.fork(threadId, forkSha.trim() || "HEAD", forkName.trim())
                    ).then(closeModal)
                  }
                  disabled={!forkName.trim() || loading}
                  className="text-xs font-mono text-amber hover:bg-amber/10 px-2 py-1 rounded disabled:opacity-40 flex items-center gap-1"
                >
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  <ChevronRight size={10} /> fork
                </button>
              </div>
            </div>
            {result && (
              <p className={`text-xs font-mono mt-2 ${result.ok ? "text-neon" : "text-red"}`}>
                {result.text}
              </p>
            )}
          </Modal>
        )}

        {modal === "merge" && (
          <Modal title="merge" onClose={closeModal}>
            <div className="space-y-3">
              <div>
                <label className="text-[10px] font-mono text-gray-600 block mb-1">source thread</label>
                <select
                  value={mergeSource}
                  onChange={(e) => setMergeSource(e.target.value)}
                  className="w-full bg-terminal-bg border border-terminal-border-light rounded px-3 py-2 text-sm font-mono text-gray-300 outline-none focus:border-amber/30"
                >
                  <option value="">select source...</option>
                  {threads.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="text-center text-gray-600 font-mono text-xs">
                merge into
              </div>
              <div>
                <label className="text-[10px] font-mono text-gray-600 block mb-1">target thread</label>
                <select
                  value={mergeTarget || threadId}
                  onChange={(e) => setMergeTarget(e.target.value)}
                  className="w-full bg-terminal-bg border border-terminal-border-light rounded px-3 py-2 text-sm font-mono text-gray-300 outline-none focus:border-amber/30"
                >
                  {threads.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={closeModal} className="text-xs font-mono text-gray-500 hover:text-gray-300 px-2 py-1">
                  cancel
                </button>
                <button
                  onClick={() =>
                    runAction(() =>
                      api.merge(mergeSource, mergeTarget || threadId)
                    ).then(closeModal)
                  }
                  disabled={!mergeSource || loading}
                  className="text-xs font-mono text-amber hover:bg-amber/10 px-2 py-1 rounded disabled:opacity-40 flex items-center gap-1"
                >
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  <ChevronRight size={10} /> merge
                </button>
              </div>
            </div>
            {result && (
              <p className={`text-xs font-mono mt-2 ${result.ok ? "text-neon" : "text-red"}`}>
                {result.text}
              </p>
            )}
          </Modal>
        )}
      </AnimatePresence>
    </>
  );
}
