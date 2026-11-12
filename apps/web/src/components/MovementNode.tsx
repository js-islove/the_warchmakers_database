import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { LineageNode } from '../types';

interface MovementNodeProps {
  data: {
    node: LineageNode;
    onSelect: (key: string) => void;
  };
}

export const MovementNode: React.FC<MovementNodeProps> = ({ data }) => {
  const { node, onSelect } = data;
  const isFocus = node.is_focus;

  return (
    <div
      onClick={() => onSelect(node.id)}
      className={`rounded-lg p-3 min-w-[200px] max-w-[240px] cursor-pointer transition-all border text-left ${
        isFocus
          ? 'bg-slate-900 border-amber-500 shadow-md ring-1 ring-amber-500/30'
          : 'bg-slate-900/90 border-slate-800 hover:border-slate-700 hover:bg-slate-850'
      }`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-2 h-2 !bg-slate-500 !border-slate-950"
      />

      <div className="flex items-center justify-between text-[11px] text-slate-400 mb-1">
        <span className="font-medium truncate">{node.manufacturer}</span>
        {node.production_start && (
          <span className="text-slate-500 font-mono text-[10px]">{node.production_start}</span>
        )}
      </div>

      <div className="text-sm font-semibold text-slate-100 truncate">
        {node.display_name}
      </div>

      <div className="mt-2 pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400 font-mono">
        <span>{node.diameter_mm ? `${node.diameter_mm} mm` : '—'}</span>
        <span>{node.beat_rate_vph ? `${(node.beat_rate_vph / 1000).toFixed(1)}k vph` : '—'}</span>
        <span>{node.jewels ? `${node.jewels}J` : '—'}</span>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="w-2 h-2 !bg-slate-500 !border-slate-950"
      />
    </div>
  );
};
