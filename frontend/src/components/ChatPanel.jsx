import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Save, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { createChatSocket } from "../lib/websocket";

function ShaBadge({ sha }) {
  const [copied, setCopied] = useState(false);
  if (!sha) return null;
  const short = sha.slice(0, 7);
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(sha);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
      className="inline-block font-mono text-[11px] px-1.5 py-0.5 rounded-md border border-border text-text-muted hover:text-accent hover:border-accent/30 transition-colors cursor-pointer"
      title={`Copy ${sha}`}
    >
      {copied ? "copied!" : short}
    </button>
  );
}

export default function ChatPanel({
  threadId,
  messages,
  setMessages,
  onCheckpointCreated,
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [showCheckpoint, setShowCheckpoint] = useState(false);
  const [checkpointLabel, setCheckpointLabel] = useState("");
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const wsRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  useEffect(() => { inputRef.current?.focus(); }, [threadId]);

  useEffect(() => {
    return () => { if (wsRef.current) wsRef.current.close(); };
  }, [threadId]);

  async function handleSend(e) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setLoading(true);

    try {
      let streamContent = "";
      setStreaming(true);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "", streaming: true },
      ]);

      const sock = createChatSocket(threadId, {
        onToken: (token) => {
          streamContent += token;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.streaming) {
              updated[updated.length - 1] = { ...last, content: streamContent };
            }
            return updated;
          });
        },
        onDone: () => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.streaming) {
              updated[updated.length - 1] = { role: "assistant", content: last.content };
            }
            return updated;
          });
          setStreaming(false);
          setLoading(false);
          sock.close();
        },
        onError: async () => {
          sock.close();
          try {
            const data = await api.chat(msg, threadId);
            setMessages((prev) => {
              const updated = prev.filter((m) => !m.streaming);
              return [...updated, {
                role: "assistant",
                content: data.response,
                checkpoint_id: data.checkpoint_id,
              }];
            });
          } catch (err) {
            setMessages((prev) => {
              const updated = prev.filter((m) => !m.streaming);
              return [...updated, { role: "error", content: `Error: ${err.message}` }];
            });
          }
          setStreaming(false);
          setLoading(false);
        },
      });

      wsRef.current = sock;
      setTimeout(() => {
        if (sock.readyState === WebSocket.OPEN) {
          sock.send(msg);
        } else {
          const checkAndSend = setInterval(() => {
            if (sock.readyState === WebSocket.OPEN) {
              sock.send(msg);
              clearInterval(checkAndSend);
            }
          }, 100);
          setTimeout(() => clearInterval(checkAndSend), 5000);
        }
      }, 300);
    } catch {
      try {
        const data = await api.chat(msg, threadId);
        setMessages((prev) => [
          ...prev.filter((m) => !m.streaming),
          { role: "assistant", content: data.response, checkpoint_id: data.checkpoint_id },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev.filter((m) => !m.streaming),
          { role: "error", content: `Error: ${err.message}` },
        ]);
      }
      setStreaming(false);
      setLoading(false);
    }
  }

  async function handleCheckpoint() {
    if (!checkpointLabel.trim()) return;
    try {
      await api.checkpoint(threadId, checkpointLabel.trim());
      setShowCheckpoint(false);
      setCheckpointLabel("");
      if (onCheckpointCreated) onCheckpointCreated();
    } catch (err) {
      alert(`Checkpoint failed: ${err.message}`);
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-sm">
              <h2 className="text-lg font-semibold text-text-primary mb-2">
                Start a conversation
              </h2>
              <p className="text-sm text-text-secondary">
                Every message creates a checkpoint. Branch, fork, merge, and
                time-travel through your conversation history.
              </p>
              <p className="text-xs text-text-muted mt-3 font-mono">
                Thread: {threadId}
              </p>
            </div>
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-accent text-white"
                    : msg.role === "error"
                      ? "bg-error-light text-error border border-error/10"
                      : "bg-surface-secondary text-text-primary border border-border"
                }`}
              >
                <div className="whitespace-pre-wrap break-words">
                  {msg.content}
                  {msg.streaming && (
                    <span className="inline-block w-1.5 h-4 bg-accent ml-0.5 blink rounded-sm" />
                  )}
                </div>
                {msg.checkpoint_id && (
                  <div className="mt-2">
                    <ShaBadge sha={msg.checkpoint_id} />
                  </div>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* Checkpoint bar */}
      <AnimatePresence>
        {showCheckpoint && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-border bg-surface-secondary px-6 py-2.5 flex items-center gap-3 overflow-hidden"
          >
            <input
              type="text"
              placeholder="Checkpoint label..."
              value={checkpointLabel}
              onChange={(e) => setCheckpointLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCheckpoint()}
              className="flex-1 bg-transparent outline-none text-sm text-text-primary placeholder-text-muted"
              autoFocus
            />
            <button
              onClick={handleCheckpoint}
              className="text-xs font-medium text-accent hover:text-accent-hover transition-colors"
            >
              Save
            </button>
            <button
              onClick={() => setShowCheckpoint(false)}
              className="text-xs text-text-muted hover:text-text-secondary"
            >
              Cancel
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input bar */}
      <form
        onSubmit={handleSend}
        className="border-t border-border bg-white px-6 py-3 flex items-center gap-3"
      >
        <button
          type="button"
          onClick={() => setShowCheckpoint(!showCheckpoint)}
          className="p-2 rounded-lg text-text-muted hover:text-warning hover:bg-warning-light transition-colors"
          title="Save checkpoint"
        >
          <Save size={16} />
        </button>
        <div className="flex-1 flex items-center border border-border rounded-xl px-4 py-2.5 focus-within:border-accent/40 focus-within:ring-1 focus-within:ring-accent/10 transition-all">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            className="flex-1 bg-transparent outline-none text-sm text-text-primary placeholder-text-muted"
            disabled={loading}
          />
        </div>
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="p-2.5 rounded-xl bg-accent text-white hover:bg-accent-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Send size={16} />
          )}
        </button>
      </form>
    </div>
  );
}
