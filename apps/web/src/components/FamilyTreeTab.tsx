import React, { useMemo } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  Node,
  Edge,
  MarkerType,
} from '@xyflow/react';
import dagre from 'dagre';
import { LineageGraphResponse } from '../types';
import { MovementNode } from './MovementNode';

interface FamilyTreeTabProps {
  lineage: LineageGraphResponse | null;
  loading: boolean;
  onSelectMovement: (key: string) => void;
}

const nodeTypes = {
  movementNode: MovementNode,
};

function getLayoutedElements(
  nodes: LineageGraphResponse['nodes'],
  edges: LineageGraphResponse['edges'],
  onSelectMovement: (key: string) => void
) {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));

  const nodeWidth = 220;
  const nodeHeight = 90;

  dagreGraph.setGraph({
    rankdir: 'TB',
    nodesep: 35,
    ranksep: 60,
  });

  nodes.forEach((node) => {
    dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  const layoutedNodes: Node[] = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id);
    return {
      id: node.id,
      type: 'movementNode',
      position: {
        x: nodeWithPosition.x - nodeWidth / 2,
        y: nodeWithPosition.y - nodeHeight / 2,
      },
      data: {
        node,
        onSelect: onSelectMovement,
      },
    };
  });

  const layoutedEdges: Edge[] = edges.map((edge) => {
    const isClone = edge.kind === 'CLONE_OF';
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      label: isClone ? 'Clone' : (edge.subtype || 'Derived'),
      labelStyle: {
        fill: '#94a3b8',
        fontWeight: 500,
        fontSize: 10,
      },
      labelBgStyle: {
        fill: '#0f172a',
        fillOpacity: 0.85,
      },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 4,
      style: {
        stroke: isClone ? '#0ea5e9' : '#d97706',
        strokeWidth: 1.5,
        strokeDasharray: isClone ? '4 4' : undefined,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isClone ? '#0ea5e9' : '#d97706',
        width: 14,
        height: 14,
      },
    };
  });

  return { nodes: layoutedNodes, edges: layoutedEdges };
}

export const FamilyTreeTab: React.FC<FamilyTreeTabProps> = ({
  lineage,
  loading,
  onSelectMovement,
}) => {
  const { nodes, edges } = useMemo(() => {
    if (!lineage || lineage.nodes.length === 0) {
      return { nodes: [], edges: [] };
    }
    return getLayoutedElements(lineage.nodes, lineage.edges, onSelectMovement);
  }, [lineage, onSelectMovement]);

  if (loading) {
    return (
      <div className="h-[460px] flex items-center justify-center bg-slate-900/40 rounded-xl border border-slate-800/80">
        <span className="text-xs text-slate-400 font-mono">Loading lineage tree...</span>
      </div>
    );
  }

  if (!lineage || nodes.length === 0) {
    return (
      <div className="h-[400px] flex items-center justify-center bg-slate-900/40 rounded-xl border border-slate-800 p-8 text-center">
        <div>
          <h4 className="text-sm font-medium text-slate-300">No Family Tree Links Documented</h4>
          <p className="text-xs text-slate-500 max-w-sm mt-1">
            This movement does not currently have documented parent ebauches or clone relationships.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-[520px] rounded-xl overflow-hidden border border-slate-800 bg-slate-950">
      {/* Subtle Legend Bar */}
      <div className="absolute top-3 left-3 z-10 flex items-center gap-3 bg-slate-900/90 backdrop-blur px-3 py-1.5 rounded-md border border-slate-800 text-xs text-slate-400">
        <span>Click any node to view details</span>
        <span className="text-slate-600">•</span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-0.5 bg-amber-500 inline-block" /> Evolution
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2 h-0.5 border-t border-dashed border-sky-400 inline-block" /> Clone
        </span>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        maxZoom={1.5}
      >
        <Background color="#1e293b" gap={20} size={1} />
        <Controls className="!m-3" />
        <MiniMap
          nodeColor={(n) => {
            const isFocus = (n.data as { node?: { is_focus?: boolean } })?.node?.is_focus;
            return isFocus ? '#f59e0b' : '#334155';
          }}
          className="!bottom-3 !right-3 !bg-slate-900 !border !border-slate-800 !rounded-md"
          maskColor="rgba(3, 7, 18, 0.7)"
        />
      </ReactFlow>
    </div>
  );
};
