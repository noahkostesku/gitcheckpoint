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
      className="inline-block font-mono text-[10px] px-1.5 py-0.5 rounded bg-terminal-border text-gray-500 hover:text-neon hover:bg-terminal-border-light transition-colors cursor-pointer"
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

  useEffect(() => {
    inputRef.current?.focus();
  }, [threadId]);

  // Clean up websocket on unmount or thread change
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [threadId]);

  async function handleSend(e) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || loading) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setLoading(true);

    // Try WebSocket streaming first, fall back to REST
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
              updated[updated.length - 1] = {
                ...last,
                content: streamContent,
              };
            }
            return updated;
          });
        },
        onDone: () => {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.streaming) {
              updated[updated.length - 1] = {
                role: "assistant",
                content: last.content,
              };
            }
            return updated;
          });
          setStreaming(false);
          setLoading(false);
          sock.close();
        },
        onError: async () => {
          // Fallback to REST
          sock.close();
          try {
            const data = await api.chat(msg, threadId);
            setMessages((prev) => {
              const updated = prev.filter((m) => !m.streaming);
              return [
                ...updated,
                {
                  role: "assistant",
                  content: data.response,
                  checkpoint_id: data.checkpoint_id,
                },
              ];
            });
          } catch (err) {
            setMessages((prev) => {
              const updated = prev.filter((m) => !m.streaming);
              return [
                ...updated,
                { role: "error", content: `Error: ${err.message}` },
              ];
            });
          }
          setStreaming(false);
          setLoading(false);
        },
      });

      wsRef.current = sock;

      // Wait for connection then send
      setTimeout(() => {
        if (sock.readyState === WebSocket.OPEN) {
          sock.send(msg);
        } else {
          // Connection not ready, add listener
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
      // Direct REST fallback
      try {
        const data = await api.chat(msg, threadId);
        setMessages((prev) => [
          ...prev.filter((m) => !m.streaming),
          {
            role: "assistant",
            content: data.response,
            checkpoint_id: data.checkpoint_id,
          },
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
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-gray-600">
              <pre className="font-mono text-xs text-gray-700 mb-4">
{`    ______ _  __   ________              __            _       __
   / ____/(_)/ /_ / ____/ /_  ___  _____/ /__ ____   (_)___  / /_
  / / __ / // __// /   / __ \\/ _ \\/ ___/ //_// __ \\ / // __ \\/ __/
 / /_/ // // /_ / /___/ / / /  __/ /__/ ,<  / /_/ // // / / / /_
 \\____//_/ \\__/ \\____/_/ /_/\\___/\\___/_/|_|/ .___//_//_/ /_/\\__/
                                          /_/`}
              </pre>
              <p className="text-sm">
                Start a conversation on{" "}
                <span className="font-mono text-amber">{threadId}</span>
              </p>
              <p className="text-xs text-gray-700 mt-1">
                Every message is a commit. Every branch is an idea.
              </p>
            </div>
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                  msg.role === "user"
                    ? "bg-neon/10 border border-neon/20 text-gray-200"
                    : msg.role === "error"
                      ? "bg-red/10 border border-red/20 text-red"
                      : "bg-terminal-surface border border-terminal-border text-gray-300"
                }`}
              >
                <div className="whitespace-pre-wrap break-words">
                  {msg.content}
                  {msg.streaming && (
                    <span className="inline-block w-2 h-4 bg-neon ml-0.5 blink" />
                  )}
                </div>
                {msg.checkpoint_id && (
                  <div className="mt-1.5 flex items-center gap-1.5">
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
            className="border-t border-terminal-border bg-terminal-surface px-4 py-2 flex items-center gap-2 overflow-hidden"
          >
            <span className="font-mono text-xs text-neon">{">"}</span>
            <input
              type="text"
              placeholder="checkpoint label..."
              value={checkpointLabel}
              onChange={(e) => setCheckpointLabel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCheckpoint()}
              className="flex-1 bg-transparent border-none outline-none text-sm font-mono text-gray-300 placeholder-gray-600"
              autoFocus
            />
            <button
              onClick={handleCheckpoint}
              className="text-xs font-mono text-neon hover:neon-text-glow transition-all"
            >
              save
            </button>
            <button
              onClick={() => setShowCheckpoint(false)}
              className="text-xs font-mono text-gray-600 hover:text-gray-400"
            >
              esc
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input bar */}
      <form
        onSubmit={handleSend}
        className="border-t border-terminal-border bg-terminal-surface px-4 py-3 flex items-center gap-2"
      >
        <button
          type="button"
          onClick={() => setShowCheckpoint(!showCheckpoint)}
          className="p-1.5 rounded text-gray-500 hover:text-amber hover:bg-amber/10 transition-colors"
          title="Save checkpoint"
        >
          <Save size={16} />
        </button>
        <div className="flex-1 flex items-center bg-terminal-bg border border-terminal-border-light rounded-lg px-3 py-2 focus-within:border-neon/30 transition-colors">
          <span className="font-mono text-neon text-sm mr-2">$</span>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message..."
            className="flex-1 bg-transparent border-none outline-none text-sm text-gray-200 placeholder-gray-600"
            disabled={loading}
          />
        </div>
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="p-2 rounded-lg bg-neon/10 text-neon hover:bg-neon/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
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
