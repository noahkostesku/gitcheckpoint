import { useState, useEffect, useCallback } from "react";
import { AnimatePresence } from "framer-motion";
import {
  GitBranch,
  Activity,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";

import ThreadSidebar from "./components/ThreadSidebar";
import ChatPanel from "./components/ChatPanel";
import GitGraph from "./components/GitGraph";
import ControlsBar from "./components/ControlsBar";
import DiffViewer from "./components/DiffViewer";
import VoiceControls from "./components/VoiceControls";
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

export default function App() {
  const [threads, setThreads] = useState([]);
  const [currentThread, setCurrentThread] = useState("default");
  const [messages, setMessages] = useState([]);
  const [logData, setLogData] = useState(null);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showGraph, setShowGraph] = useState(true);
  const [connected, setConnected] = useState(false);

  // Health check
  useEffect(() => {
    api.health().then(() => setConnected(true)).catch(() => setConnected(false));
  }, []);

  // Fetch threads
  const refreshThreads = useCallback(async () => {
    setThreadsLoading(true);
    try {
      const data = await api.getThreads();
      setThreads(parseThreadList(data.result));
    } catch {
      // server might not be running
    }
    setThreadsLoading(false);
  }, []);

  // Fetch log for current thread
  const refreshLog = useCallback(async () => {
    try {
      const data = await api.getLog(currentThread);
      setLogData(data.result);
    } catch {
      setLogData(null);
    }
  }, [currentThread]);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  useEffect(() => {
    refreshLog();
  }, [refreshLog]);

  // Refresh threads + log after messages change
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
    // Thread gets created when first message is sent
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

  async function handleVoiceTranscript(transcript) {
    // Add the transcript as a user message and send via chat API
    setMessages((prev) => [...prev, { role: "user", content: transcript }]);
    try {
      const data = await api.chat(transcript, currentThread);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          checkpoint_id: data.checkpoint_id,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "error", content: `Error: ${err.message}` },
      ]);
    }
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-terminal-bg overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-terminal-border bg-terminal-surface flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowSidebar(!showSidebar)}
            className="p-1 text-gray-600 hover:text-gray-300 transition-colors"
          >
            {showSidebar ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
          </button>
          <div className="flex items-center gap-2">
            <GitBranch size={14} className="text-neon" />
            <span className="font-mono text-sm text-gray-200">
              GitCheckpoint
            </span>
          </div>
          <div className="w-px h-4 bg-terminal-border" />
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs text-gray-500">on</span>
            <span className="font-mono text-xs text-amber font-medium">
              {currentThread}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <VoiceControls threadId={currentThread} onTranscript={handleVoiceTranscript} />
          <div className="w-px h-4 bg-terminal-border" />
          <div className="flex items-center gap-1.5">
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                connected ? "bg-neon" : "bg-red"
              }`}
            />
            <span className="text-[10px] font-mono text-gray-600">
              {connected ? "connected" : "offline"}
            </span>
          </div>
          <button
            onClick={() => setShowGraph(!showGraph)}
            className="p-1 text-gray-600 hover:text-gray-300 transition-colors"
          >
            {showGraph ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Thread sidebar */}
        {showSidebar && (
          <div className="w-56 flex-shrink-0">
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

        {/* Center: Chat */}
        <div className="flex-1 flex flex-col min-w-0 relative">
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
        </div>

        {/* Right: Git Graph */}
        {showGraph && (
          <div className="w-80 flex-shrink-0 border-l border-terminal-border bg-terminal-bg">
            <div className="px-3 py-2 border-b border-terminal-border flex items-center gap-2">
              <Activity size={12} className="text-neon" />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                Commit Graph
              </span>
            </div>
            <div className="h-[calc(100%-33px)]">
              <GitGraph
                logData={logData}
                threadId={currentThread}
                onTimeTravel={handleTimeTravel}
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
