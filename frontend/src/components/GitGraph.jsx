import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion } from "framer-motion";
import { GitCommit } from "lucide-react";

// ---- Custom commit node ----
function CommitNode({ data }) {
  const isHead = data.isHead;
  const isMerge = data.isMerge;

  return (
    <div
      className={`group cursor-pointer transition-all ${isHead ? "scale-105" : ""}`}
      onClick={data.onClick}
    >
      <div
        className={`flex items-start gap-2 rounded-lg px-3 py-2 border transition-all ${
          isHead
            ? "bg-neon/10 border-neon/40 pulse-neon"
            : isMerge
              ? "bg-amber/5 border-amber/20 hover:border-amber/40"
              : "bg-terminal-surface border-terminal-border hover:border-terminal-border-light"
        }`}
        style={{ minWidth: 180, maxWidth: 260 }}
      >
        {/* Commit dot */}
        <div className="flex-shrink-0 mt-1">
          <div
            className={`w-3 h-3 rounded-full border-2 ${
              isHead
                ? "bg-neon border-neon"
                : isMerge
                  ? "bg-amber border-amber"
                  : "bg-terminal-border-light border-gray-600 group-hover:border-gray-400"
            }`}
          />
        </div>

        <div className="flex-1 min-w-0">
          {/* SHA */}
          <div className="flex items-center gap-1.5">
            <span
              className={`font-mono text-[10px] ${
                isHead ? "text-neon" : "text-gray-500"
              }`}
            >
              {data.sha?.slice(0, 7) || "???????"}
            </span>
            {isHead && (
              <span className="text-[9px] font-mono px-1 py-0 rounded bg-neon/20 text-neon">
                HEAD
              </span>
            )}
            {data.branch && (
              <span className="text-[9px] font-mono px-1 py-0 rounded bg-amber/15 text-amber">
                {data.branch}
              </span>
            )}
          </div>

          {/* Message */}
          <div className="text-[11px] text-gray-400 truncate mt-0.5 group-hover:text-gray-200 transition-colors">
            {data.message || "checkpoint"}
          </div>

          {/* Timestamp */}
          {data.timestamp && (
            <div className="text-[9px] font-mono text-gray-700 mt-0.5">
              {data.timestamp}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { commit: CommitNode };

// ---- Parse log text into graph data ----
function parseLogToGraph(logText, onTimeTravel) {
  if (!logText || logText.includes("not found") || logText.includes("No threads")) {
    return { nodes: [], edges: [] };
  }

  const lines = logText.split("\n").filter((l) => l.trim());
  const nodes = [];
  const edges = [];
  const commitRegex = /\*?\s*([a-f0-9]{7,40})\s/;
  const branchRegex = /\(([^)]+)\)/;

  let y = 0;
  const SPACING_Y = 80;
  const branchLanes = {};
  let laneCount = 0;

  for (const line of lines) {
    const shaMatch = line.match(commitRegex);
    if (!shaMatch) continue;

    const sha = shaMatch[1];
    const branchMatch = line.match(branchRegex);
    const branches = branchMatch ? branchMatch[1].split(",").map((b) => b.trim()) : [];
    const isHead = line.includes("HEAD") || line.includes("*");
    const isMerge = line.toLowerCase().includes("merge");

    // Determine lane
    let lane = 0;
    for (const b of branches) {
      if (!(b in branchLanes)) {
        branchLanes[b] = laneCount++;
      }
      lane = branchLanes[b];
    }

    // Extract message (everything after SHA and optional branch refs)
    let message = line
      .replace(/\*?\s*/, "")
      .replace(sha, "")
      .replace(/\([^)]+\)/, "")
      .trim();
    if (!message) message = "checkpoint";

    // Extract timestamp if present
    const timeMatch = line.match(/(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})/);
    const timestamp = timeMatch ? timeMatch[1].replace("T", " ") : null;

    const nodeId = `commit-${sha}`;
    nodes.push({
      id: nodeId,
      type: "commit",
      position: { x: lane * 200, y },
      data: {
        sha,
        message,
        timestamp,
        isHead: isHead && y === 0,
        isMerge,
        branch: branches[0] || null,
        onClick: () => onTimeTravel && onTimeTravel(sha),
      },
    });

    // Edge to previous node
    if (nodes.length > 1) {
      const prevNode = nodes[nodes.length - 2];
      edges.push({
        id: `edge-${prevNode.id}-${nodeId}`,
        source: prevNode.id,
        target: nodeId,
        type: "smoothstep",
        style: {
          stroke: isMerge ? "#ffb800" : "#2a2a2a",
          strokeWidth: isMerge ? 2 : 1.5,
        },
        animated: isHead && y === 0,
      });
    }

    y += SPACING_Y;
  }

  return { nodes, edges };
}

export default function GitGraph({ logData, threadId, onTimeTravel }) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => parseLogToGraph(logData, onTimeTravel),
    [logData, onTimeTravel]
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes when log data changes
  useMemo(() => {
    if (initialNodes.length > 0) {
      onNodesChange(
        initialNodes.map((n) => ({ type: "reset", item: n }))
      );
      onEdgesChange(
        initialEdges.map((e) => ({ type: "reset", item: e }))
      );
    }
  }, [initialNodes, initialEdges]);

  if (!logData || initialNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <GitCommit size={24} className="text-gray-700 mx-auto mb-2" />
          <p className="text-xs text-gray-600 font-mono">no commits yet</p>
          <p className="text-[10px] text-gray-700 mt-1">
            chat to create your first checkpoint
          </p>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="h-full w-full"
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="#1a1a1a" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </motion.div>
  );
}
