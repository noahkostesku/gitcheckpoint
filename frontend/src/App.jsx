import { useState, useEffect, useCallback, useRef } from "react";
import { AnimatePresence } from "framer-motion";
import {
  GitBranch,
  Activity,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Mic,
  MicOff,
} from "lucide-react";

import ThreadSidebar from "./components/ThreadSidebar";
import ChatPanel from "./components/ChatPanel";
import GitGraph from "./components/GitGraph";
import ControlsBar from "./components/ControlsBar";
import DiffViewer from "./components/DiffViewer";
import VoiceOrb from "./components/VoiceOrb";
import { api } from "./lib/api";

function parseThreadList(raw) {
  if (!raw || raw.includes("No threads")) return [];
  const threads = [];
  const lines = raw.split("\n").filter((l) => l.trim());
  for (const line of lines) {
    const match = line.match(/thread-(\S+)/);
    if (match) {
      const name = match[1];
      const commitMatch = line.match(/(\d+)\s+commit/);
      threads.push({
        name,
        commits: commitMatch ? parseInt(commitMatch[1]) : 0,
      });
    }
  }
  return threads;
}

function formatThreadName(name) {
  return name
    .replace(/^thread-/, "")
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function flashElement(id) {
  const el = document.querySelector(`[data-ui-id="${id}"]`);
  if (el) {
    el.classList.add("flash-highlight");
    setTimeout(() => el.classList.remove("flash-highlight"), 1500);
  }
}

export default function App() {
  const [threads, setThreads] = useState([]);
  const [currentThread, setCurrentThread] = useState("default");
  const [messages, setMessages] = useState([]);
  const [logData, setLogData] = useState(null);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showGraph, setShowGraph] = useState(true);
  const [showChat, setShowChat] = useState(false);
  const [connected, setConnected] = useState(false);
  const [highlightedCommit, setHighlightedCommit] = useState(null);
  const [alwaysListening, setAlwaysListening] = useState(() => {
    try { return localStorage.getItem("gitcheckpoint_always_listening") === "true"; }
    catch { return false; }
  });

  const highlightTimerRef = useRef(null);

  useEffect(() => {
    api.health().then(() => setConnected(true)).catch(() => setConnected(false));
  }, []);

  // Persist always-listening preference
  useEffect(() => {
    try { localStorage.setItem("gitcheckpoint_always_listening", String(alwaysListening)); }
    catch {}
  }, [alwaysListening]);

  const refreshThreads = useCallback(async () => {
    setThreadsLoading(true);
    try {
      const data = await api.getThreads();
      setThreads(parseThreadList(data.result));
    } catch {}
    setThreadsLoading(false);
  }, []);

  const refreshLog = useCallback(async () => {
    try {
      const data = await api.getLog(currentThread);
      setLogData(data.result);
    } catch {
      setLogData(null);
    }
  }, [currentThread]);

  useEffect(() => { refreshThreads(); }, [refreshThreads]);
  useEffect(() => { refreshLog(); }, [refreshLog]);

  useEffect(() => {
    if (messages.length > 0) {
      const timer = setTimeout(() => {
        refreshThreads();
        refreshLog();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [messages.length, refreshThreads, refreshLog]);

  function handleSelectThread(name) {
    setCurrentThread(name);
    setMessages([]);
    setLogData(null);
  }

  function handleNewThread(name) {
    setCurrentThread(name);
    setMessages([]);
    setLogData(null);
  }

  async function handleTimeTravel(sha) {
    try {
      await api.timeTravel(currentThread, sha);
      refreshLog();
    } catch (err) {
      alert(`Time travel failed: ${err.message}`);
    }
  }

  function handleRefresh() {
    refreshThreads();
    refreshLog();
  }

  function handleVoiceTranscript(transcript) {
    setMessages((prev) => [...prev, { role: "user", content: transcript }]);
  }

  function handleVoiceMessage(msg) {
    setMessages((prev) => [...prev, msg]);
  }

  function handleVoiceUiCommand(action, params = {}) {
    switch (action) {
      case "switch_thread":
        handleSelectThread(params.thread_name || params.thread_id || params.value || currentThread);
        break;
      case "toggle_sidebar":
        setShowSidebar((prev) => params.visible !== undefined ? params.visible : !prev);
        break;
      case "toggle_graph":
        setShowGraph((prev) => params.visible !== undefined ? params.visible : !prev);
        break;
      case "show_diff":
        setShowDiff(true);
        break;
      case "new_thread":
        if (params.thread_name) handleNewThread(params.thread_name);
        break;
      // --- Autonomous UI commands from Git ---
      case "flash_element":
        flashElement(params.value || params.element || "");
        break;
      case "highlight_commit": {
        const sha = params.value || params.sha || "";
        setHighlightedCommit(sha);
        if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
        highlightTimerRef.current = setTimeout(() => setHighlightedCommit(null), 3000);
        break;
      }
      case "open_sidebar":
        setShowSidebar(true);
        break;
      case "open_graph":
        setShowGraph(true);
        break;
      case "scroll_to_commit":
        // Highlight + ensure graph is visible
        setShowGraph(true);
        setHighlightedCommit(params.value || params.sha || "");
        if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
        highlightTimerRef.current = setTimeout(() => setHighlightedCommit(null), 3000);
        break;
    }
  }

  function handleVoiceStateUpdate(kind, data) {
    if (kind === "threads_changed" && data?.raw) {
      setThreads(parseThreadList(data.raw));
    }
    if (kind === "log_changed" && data?.raw) {
      setLogData(data.raw);
    }
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-white overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-border bg-surface flex-shrink-0">
        <div className="flex items-center gap-4">
          <button
            onClick={() => setShowSidebar(!showSidebar)}
            className="p-1.5 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-tertiary transition-colors"
          >
            {showSidebar ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
          </button>
          <div className="flex items-center gap-2">
            <GitBranch size={16} className="text-accent" />
            <span className="text-sm font-semibold text-text-primary">
              GitCheckpoint
            </span>
          </div>
          <span className="text-sm text-text-muted">/</span>
          <span className="text-sm font-semibold text-accent">
            Git
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Always listening toggle */}
          <button
            onClick={() => setAlwaysListening(!alwaysListening)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              alwaysListening
                ? "bg-accent-light text-accent"
                : "text-text-muted hover:text-text-secondary hover:bg-surface-tertiary"
            }`}
            title={alwaysListening
              ? "Always listening — say 'Hey Git' to activate"
              : "Click to enable wake word detection"
            }
          >
            {alwaysListening ? <Mic size={13} /> : <MicOff size={13} />}
            {alwaysListening ? "Listening" : "Wake Word"}
          </button>

          {/* Toggle between voice and chat */}
          <button
            onClick={() => setShowChat(!showChat)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              showChat
                ? "bg-accent-light text-accent"
                : "text-text-muted hover:text-text-secondary hover:bg-surface-tertiary"
            }`}
          >
            {showChat ? "Voice Mode" : "Text Chat"}
          </button>
          <div className="flex items-center gap-1.5">
            <div
              className={`w-2 h-2 rounded-full ${connected ? "bg-success" : "bg-error"}`}
            />
            <span className="text-xs text-text-muted">
              {connected ? "Connected" : "Offline"}
            </span>
          </div>
          <button
            onClick={() => setShowGraph(!showGraph)}
            className="p-1.5 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-tertiary transition-colors"
          >
            {showGraph ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Thread sidebar */}
        {showSidebar && (
          <div className="w-60 flex-shrink-0" data-ui-id="sidebar">
            <ThreadSidebar
              threads={threads}
              currentThread={currentThread}
              onSelectThread={handleSelectThread}
              onNewThread={handleNewThread}
              onRefresh={refreshThreads}
              loading={threadsLoading}
            />
          </div>
        )}

        {/* Center area */}
        <div className="flex-1 flex flex-col min-w-0 relative">
          {showChat ? (
            /* Text chat mode */
            <>
              <div className="flex-1 overflow-hidden">
                <ChatPanel
                  threadId={currentThread}
                  messages={messages}
                  setMessages={setMessages}
                  onCheckpointCreated={handleRefresh}
                />
              </div>
              <ControlsBar
                threadId={currentThread}
                threads={threads}
                onRefresh={handleRefresh}
                onShowDiff={() => setShowDiff(true)}
              />
            </>
          ) : (
            /* Voice mode — orb in center */
            <>
              <div className="flex-1 flex items-center justify-center" data-ui-id="orb">
                <VoiceOrb
                  threadId={currentThread}
                  onTranscript={handleVoiceTranscript}
                  onMessage={handleVoiceMessage}
                  onUiCommand={handleVoiceUiCommand}
                  onStateUpdate={handleVoiceStateUpdate}
                  alwaysListening={alwaysListening}
                />
              </div>
              {/* Thread info at bottom */}
              <div className="px-4 py-2 border-t border-border flex items-center justify-between">
                <span className="text-xs font-mono text-text-muted">
                  thread-{currentThread}
                </span>
                <ControlsBar
                  threadId={currentThread}
                  threads={threads}
                  onRefresh={handleRefresh}
                  onShowDiff={() => setShowDiff(true)}
                />
              </div>
            </>
          )}
        </div>

        {/* Right: Git Graph */}
        {showGraph && (
          <div className="w-80 flex-shrink-0 border-l border-border bg-white" data-ui-id="graph">
            <div className="px-4 py-3 border-b border-border flex items-center gap-2">
              <Activity size={14} className="text-accent" />
              <span className="text-xs font-semibold text-text-secondary tracking-wide">
                Commit Graph
              </span>
            </div>
            <div className="h-[calc(100%-45px)]">
              <GitGraph
                logData={logData}
                threadId={currentThread}
                onTimeTravel={handleTimeTravel}
                highlightedCommit={highlightedCommit}
              />
            </div>
          </div>
        )}
      </div>

      {/* Diff viewer modal */}
      <AnimatePresence>
        {showDiff && (
          <DiffViewer
            threadId={currentThread}
            onClose={() => setShowDiff(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
