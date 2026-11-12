import React from 'react';
import { SubstitutesResponse } from '../types';
import { ArrowUpRight } from 'lucide-react';

interface CaseSwapTabProps {
  substitutesData: SubstitutesResponse | null;
  loading: boolean;
  onSelectSubstitute: (key: string) => void;
}

export const CaseSwapTab: React.FC<CaseSwapTabProps> = ({
  substitutesData,
  loading,
  onSelectSubstitute,
}) => {
  if (loading) {
    return (
      <div className="h-64 flex items-center justify-center bg-slate-900/40 rounded-xl border border-slate-800">
        <span className="text-xs text-slate-400 font-mono">Checking case dimensions...</span>
      </div>
    );
  }

  const subs = substitutesData?.substitutes || [];

  return (
    <div className="space-y-4">
      {/* Target summary bar */}
      <div className="flex items-center justify-between text-xs text-slate-400 pb-2 border-b border-slate-800">
        <span>Replacement options based on physical dimensions</span>
        <span className="font-mono text-slate-400">
          Target: {substitutesData?.target_diameter_mm ? `${substitutesData.target_diameter_mm} mm` : '—'} ⌀
          {substitutesData?.target_height_mm ? ` × ${substitutesData.target_height_mm} mm` : ''}
        </span>
      </div>

      {subs.length === 0 ? (
        <div className="bg-slate-900/30 rounded-xl border border-slate-800/80 p-8 text-center text-xs text-slate-400">
          No alternative movements in the catalog currently fit within case envelope tolerances (±0.30mm diameter).
        </div>
      ) : (
        <div className="divide-y divide-slate-800/80 border border-slate-800 rounded-xl bg-slate-900/60 overflow-hidden">
          {subs.map((cand) => {
            const isDirect = cand.fit_class === 'direct_swap';

            return (
              <div
                key={cand.candidate_key}
                className="p-4 hover:bg-slate-850/50 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-4"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    <h4 className="text-sm font-semibold text-slate-100">
                      {cand.candidate_name}
                    </h4>
                    <button
                      onClick={() => onSelectSubstitute(cand.candidate_key)}
                      className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-0.5 font-medium"
                    >
                      View <ArrowUpRight className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <p className="text-xs text-slate-400">
                    {isDirect ? (
                      <span className="text-emerald-400 font-medium">Direct swap</span>
                    ) : (
                      <span className="text-amber-400/90 font-medium">Requires minor adjustment</span>
                    )}
                    {' • '}
                    <span>{cand.hands_compatible ? 'Reuses hands' : 'Different hand hole sizes'}</span>
                    {' • '}
                    <span className="capitalize">{cand.winding}</span>
                  </p>

                  {/* Clean, plain notes if adjustments needed */}
                  {cand.modifications.length > 0 && (
                    <div className="text-[11px] text-slate-400 pt-0.5">
                      Note: {cand.modifications.join(' • ')}
                    </div>
                  )}
                </div>

                <div className="sm:text-right flex-shrink-0">
                  <span className="text-[10px] text-slate-500 block uppercase font-mono tracking-wider">
                    Compatibility
                  </span>
                  <span className="text-sm font-semibold text-slate-200">
                    {(cand.compatibility_score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
