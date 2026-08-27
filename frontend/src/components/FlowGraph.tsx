"use client";

import { useCallback, useMemo, useState } from "react";
import dagre from "dagre";
import { toPng } from "html-to-image";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  Position,
  MarkerType,
  Handle,
  NodeProps,
  ReactFlowProvider,
  useReactFlow,
  getNodesBounds,
  getViewportForBounds,
} from "reactflow";
import "reactflow/dist/style.css";
import { layerColor } from "@/components/ui";

export interface FlowNodeSpec {
  id: string;
  label: string;
  sublabel?: string;
  color: string;
}

export interface FlowEdgeSpec {
  id: string;
  source: string;
  target: string;
  label?: string;
}

/** Every node/edge connected to `selectedId`, walking both upstream
 * (ancestors) and downstream (descendants) -- "the path this node goes
 * through," not just its direct neighbors. Used to light up the whole
 * chain a clicked node belongs to and fade everything unrelated,
 * instead of a flat click highlight that only marks the node itself. */
function connectedPath(edges: FlowEdgeSpec[], selectedId: string | null | undefined) {
  const nodeIds = new Set<string>();
  const edgeIds = new Set<string>();
  if (!selectedId) return { nodeIds, edgeIds };

  const outgoing = new Map<string, FlowEdgeSpec[]>();
  const incoming = new Map<string, FlowEdgeSpec[]>();
  for (const e of edges) {
    (outgoing.get(e.source) ?? outgoing.set(e.source, []).get(e.source)!).push(e);
    (incoming.get(e.target) ?? incoming.set(e.target, []).get(e.target)!).push(e);
  }

  nodeIds.add(selectedId);
  const walk = (start: string, byNode: Map<string, FlowEdgeSpec[]>, next: (e: FlowEdgeSpec) => string) => {
    const stack = [start];
    while (stack.length) {
      const current = stack.pop()!;
      for (const e of byNode.get(current) ?? []) {
        edgeIds.add(e.id);
        const neighbor = next(e);
        if (!nodeIds.has(neighbor)) {
          nodeIds.add(neighbor);
          stack.push(neighbor);
        }
      }
    }
  };
  walk(selectedId, outgoing, (e) => e.target);
  walk(selectedId, incoming, (e) => e.source);

  return { nodeIds, edgeIds };
}

interface LabeledNodeData {
  label: string;
  sublabel?: string;
  color: string;
  isSelected: boolean;
  isLit: boolean;
  dimmed: boolean;
}

/** A custom node so both `label` (e.g. a column name) and `sublabel`
 * (e.g. which model it belongs to) are actually visible -- React Flow's
 * built-in default node only ever renders `data.label`, silently
 * dropping anything else stashed in `data`. Two lines: the label bold
 * and prominent, the sublabel muted underneath, so "order_id" from
 * three different models never looks like the same thing three times. */
function LabeledNode({ data }: NodeProps<LabeledNodeData>) {
  const borderColor = data.isSelected
    ? "var(--accent)"
    : data.isLit
      ? "rgba(255,122,69,0.55)"
      : "var(--line)";
  return (
    <div
      style={{
        width: 190,
        background: "var(--ink-900)",
        border: `1px solid ${borderColor}`,
        borderRadius: 8,
        padding: "8px 10px",
        opacity: data.dimmed ? 0.3 : 1,
        boxShadow: data.isSelected ? "0 0 0 1.5px var(--accent), 0 0 16px rgba(255,122,69,0.35)" : "none",
        transition: "opacity 200ms ease, border-color 200ms ease, box-shadow 200ms ease",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "var(--line)", border: "none" }} />
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: data.color }} />
        <span
          className="truncate font-mono text-[13px] font-medium"
          style={{ color: "var(--text-hi)" }}
          title={data.label}
        >
          {data.label}
        </span>
      </div>
      {data.sublabel && (
        <div
          className="truncate pl-3 font-mono text-[11px]"
          style={{ color: "var(--text-lo)" }}
          title={data.sublabel}
        >
          {data.sublabel}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: "var(--line)", border: "none" }} />
    </div>
  );
}

// Defined once at module scope -- passing a fresh object literal to
// ReactFlow's `nodeTypes` prop on every render is what triggers its
// "you've created a new nodeTypes object" perf warning (and a real
// remount-on-every-render cost), not just a cosmetic dev-console note.
const NODE_TYPES = { labeled: LabeledNode };

function layout(nodes: FlowNodeSpec[], edges: FlowEdgeSpec[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 36, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));

  const width = 190;
  const height = 52;
  nodes.forEach((n) => g.setNode(n.id, { width, height }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  const positions = new Map(nodes.map((n) => [n.id, g.node(n.id)]));
  return { positions, width, height };
}

/** Top-right overlay: export the current graph as a PNG (for a Slack
 * message or a PR comment -- the exact thing a "trace →" link can't do,
 * since the recipient may not have the tool open) and copy the page's
 * own URL (every graph view is already a real, shareable URL thanks to
 * the deep-link query params, this just saves retyping it). Needs
 * useReactFlow, so it has to live inside <ReactFlowProvider>. */
function GraphToolbar() {
  const { getNodes } = useReactFlow();
  const [copied, setCopied] = useState(false);

  const exportPng = useCallback(() => {
    const viewport = document.querySelector(".react-flow__viewport") as HTMLElement | null;
    if (!viewport) return;
    const bounds = getNodesBounds(getNodes());
    const imageWidth = Math.max(bounds.width + 80, 400);
    const imageHeight = Math.max(bounds.height + 80, 300);
    const { x, y, zoom } = getViewportForBounds(bounds, imageWidth, imageHeight, 0.5, 2, 0.1);
    toPng(viewport, {
      backgroundColor: "#0b0e14",
      width: imageWidth,
      height: imageHeight,
      style: {
        width: `${imageWidth}px`,
        height: `${imageHeight}px`,
        transform: `translate(${x}px, ${y}px) scale(${zoom})`,
      },
    }).then((dataUrl) => {
      const a = document.createElement("a");
      a.setAttribute("download", "lineage-graph.png");
      a.setAttribute("href", dataUrl);
      a.click();
    });
  }, [getNodes]);

  const copyLink = useCallback(() => {
    const url = window.location.href;
    const flash = () => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    };
    const fallbackCopy = () => {
      const textarea = document.createElement("textarea");
      textarea.value = url;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand("copy");
        flash();
      } catch {
        // Nothing more we can do -- leave the button unflashed.
      }
      document.body.removeChild(textarea);
    };
    // Some embedded/sandboxed browser contexts deny the async Clipboard
    // API outright -- either as a rejected promise, or (in at least one
    // observed sandbox) as a *synchronous* throw before the promise
    // chain even attaches. Guard both, and fall back to the old
    // execCommand path rather than leaving the button looking like it
    // silently did nothing.
    try {
      navigator.clipboard.writeText(url).then(flash, fallbackCopy);
    } catch {
      fallbackCopy();
    }
  }, []);

  const btn =
    "rounded-md border border-line bg-ink-900/90 px-2.5 py-1.5 font-mono text-[11px] text-text-lo backdrop-blur transition-colors hover:border-accent hover:text-text-hi";

  return (
    <div className="absolute right-3 top-3 z-10 flex gap-1.5">
      <button onClick={copyLink} className={btn}>
        {copied ? "copied ✓" : "copy link"}
      </button>
      <button onClick={exportPng} className={btn}>
        export png ↓
      </button>
    </div>
  );
}

/** Bottom-left overlay explaining what the node dots' colors mean --
 * the same colored-dot idiom is used everywhere in the app (badges,
 * StatusPill, sidebar), but a graph is the one place it shows up with
 * no adjacent text label, so it's the one place worth spelling out.
 * Caller-supplied rather than inferred from `nodes`, since the same dot
 * color means a different thing on different graphs (a real dbt model
 * layer on Model DAG/Column Lineage, a query-flow step type on Model
 * Explorer's Query Flow tab). */
function GraphLegend({ items }: { items: { label: string; color: string }[] }) {
  if (items.length === 0) return null;
  return (
    <div className="absolute left-3 top-3 z-10 flex flex-wrap gap-x-3 gap-y-1 rounded-md border border-line bg-ink-900/90 px-2.5 py-1.5 backdrop-blur">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5 font-mono text-[11px] text-text-lo">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export function FlowGraph({
  nodes,
  edges,
  height = 420,
  onNodeClick,
  selectedId,
  legend,
}: {
  nodes: FlowNodeSpec[];
  edges: FlowEdgeSpec[];
  height?: number;
  onNodeClick?: (id: string) => void;
  selectedId?: string | null;
  legend?: { label: string; color: string }[];
}) {
  const { positions, width, height: nodeHeight } = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const { nodeIds: litNodeIds, edgeIds: litEdgeIds } = useMemo(
    () => connectedPath(edges, selectedId),
    [edges, selectedId]
  );
  const hasSelection = Boolean(selectedId);

  const rfNodes: Node<LabeledNodeData>[] = nodes.map((n) => {
    const pos = positions.get(n.id)!;
    const isSelected = n.id === selectedId;
    const isLit = litNodeIds.has(n.id);
    return {
      id: n.id,
      type: "labeled",
      position: { x: pos.x - width / 2, y: pos.y - nodeHeight / 2 },
      data: {
        label: n.label,
        sublabel: n.sublabel,
        color: n.color,
        isSelected,
        isLit,
        dimmed: hasSelection && !isLit,
      },
    };
  });

  const rfEdges: Edge[] = edges.map((e) => {
    const isLit = litEdgeIds.has(e.id);
    const dimmed = hasSelection && !isLit;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: isLit,
      labelStyle: { fill: "var(--text-lo)", fontSize: 10 },
      labelBgStyle: { fill: "var(--ink-950)" },
      style: {
        stroke: isLit ? "var(--accent)" : "var(--line)",
        strokeWidth: isLit ? 2 : 1,
        opacity: dimmed ? 0.15 : 1,
        transition: "stroke 200ms ease, opacity 200ms ease",
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isLit ? "var(--accent)" : "var(--line)",
        width: 16,
        height: 16,
      },
    };
  });

  return (
    <div
      style={{ height }}
      className="relative overflow-hidden rounded-lg border border-line bg-ink-950"
    >
      <ReactFlowProvider>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={NODE_TYPES}
          nodesDraggable={false}
          onNodeClick={(_, node) => onNodeClick?.(node.id)}
          onPaneClick={() => onNodeClick?.("")}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background color="var(--line)" gap={20} />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            maskColor="rgba(11,14,20,0.75)"
            nodeColor="var(--ink-800)"
            nodeStrokeColor="var(--line)"
            nodeBorderRadius={4}
            style={{ background: "var(--ink-900)" }}
          />
        </ReactFlow>
        <GraphToolbar />
        {legend && <GraphLegend items={legend} />}
      </ReactFlowProvider>
    </div>
  );
}

export { layerColor };
