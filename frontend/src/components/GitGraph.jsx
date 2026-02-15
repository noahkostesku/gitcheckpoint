import { useMemo } from "react";
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

function CommitNode({ data }) {
  const isHead = data.isHead;
  const isMerge = data.isMerge;
  const isHighlighted = data.isHighlighted;

  return (
    <div
      className={`group cursor-pointer transition-all ${isHead ? "scale-105" : ""} ${isHighlighted ? "scale-110" : ""}`}
      onClick={data.onClick}
    >
      <div
        className={`flex items-start gap-2.5 rounded-xl px-3 py-2.5 border transition-all ${
          isHighlighted
            ? "bg-accent-light border-accent/50 commit-highlighted shadow-md"
            : isHead
              ? "bg-accent-light border-accent/30 pulse-accent shadow-sm"
              : isMerge
                ? "bg-warning-light border-warning/20 hover:border-warning/40"
                : "bg-white border-border hover:border-border hover:shadow-sm"
        }`}
        style={{ minWidth: 180, maxWidth: 260 }}
      >
        {/* Commit dot */}
        <div className="flex-shrink-0 mt-1">
          <div
            className={`w-3 h-3 rounded-full border-2 ${
              isHead
                ? "bg-accent border-accent"
                : isMerge
                  ? "bg-warning border-warning"
                  : "bg-surface-tertiary border-text-muted group-hover:border-text-secondary"
            }`}
          />
        </div>

        <div className="flex-1 min-w-0">
          {/* SHA + badges */}
          <div className="flex items-center gap-1.5">
            <span
              className={`font-mono text-[11px] ${
                isHead ? "text-accent font-medium" : "text-text-muted"
              }`}
            >
              {data.sha?.slice(0, 7) || "???????"}
            </span>
            {isHead && (
              <span className="text-[9px] font-medium px-1.5 py-0 rounded-full bg-accent text-white">
                HEAD
              </span>
            )}
            {data.branch && (
              <span className="text-[9px] font-medium px-1.5 py-0 rounded-full bg-warning-light text-warning">
                {data.branch}
              </span>
            )}
          </div>

          {/* Message */}
          <div className="text-xs text-text-secondary truncate mt-0.5 group-hover:text-text-primary transition-colors">
            {data.message || "checkpoint"}
          </div>

          {/* Timestamp */}
          {data.timestamp && (
            <div className="text-[10px] font-mono text-text-muted mt-0.5">
              {data.timestamp}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { commit: CommitNode };

function parseLogToGraph(logText, onTimeTravel, highlightedCommit) {
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

    let lane = 0;
    for (const b of branches) {
      if (!(b in branchLanes)) branchLanes[b] = laneCount++;
      lane = branchLanes[b];
    }

    let message = line
      .replace(/\*?\s*/, "")
      .replace(sha, "")
      .replace(/\([^)]+\)/, "")
      .trim();
    if (!message) message = "checkpoint";

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
        isHighlighted: highlightedCommit && sha.startsWith(highlightedCommit),
        branch: branches[0] || null,
        onClick: () => onTimeTravel && onTimeTravel(sha),
      },
    });

    if (nodes.length > 1) {
      const prevNode = nodes[nodes.length - 2];
      edges.push({
        id: `edge-${prevNode.id}-${nodeId}`,
        source: prevNode.id,
        target: nodeId,
        type: "smoothstep",
        style: {
          stroke: isMerge ? "#d97706" : "#d1d5db",
          strokeWidth: isMerge ? 2 : 1.5,
        },
        animated: isHead && y === 0,
      });
    }

    y += SPACING_Y;
  }

  return { nodes, edges };
}

export default function GitGraph({ logData, threadId, onTimeTravel, highlightedCommit }) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => parseLogToGraph(logData, onTimeTravel, highlightedCommit),
    [logData, onTimeTravel, highlightedCommit]
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  useMemo(() => {
    if (initialNodes.length > 0) {
      onNodesChange(initialNodes.map((n) => ({ type: "reset", item: n })));
      onEdgesChange(initialEdges.map((e) => ({ type: "reset", item: e })));
    }
  }, [initialNodes, initialEdges]);

  if (!logData || initialNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <GitCommit size={24} className="text-text-muted mx-auto mb-2" />
          <p className="text-sm text-text-muted">No commits yet</p>
          <p className="text-xs text-text-muted mt-1">
            Chat to create your first checkpoint
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
        <Background color="#f3f4f6" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </motion.div>
  );
}
