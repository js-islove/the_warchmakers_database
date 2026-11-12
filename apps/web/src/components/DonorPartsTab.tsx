import React from 'react';
import { DonorMatchesResponse } from '../types';
import { ArrowUpRight } from 'lucide-react';

interface DonorPartsTabProps {
  donorData: DonorMatchesResponse | null;
  loading: boolean;
  selectedPartSlot: string | null;
  onFilterSlot: (slot: string | null) => void;
  onSelectDonor: (donorKey: string) => void;
}

const COMMON_PARTS = [
  { code: null, label: 'All Parts' },
  { code: 'balance_complete', label: 'Balance Wheel' },
  { code: 'winding_stem', label: 'Winding Stem' },
  { code: 'mainspring', label: 'Mainspring' },
  { code: 'pallet_fork', label: 'Pallet Fork' },
  { code: 'escape_wheel', label: 'Escape Wheel' },
];

export const DonorPartsTab: React.FC<DonorPartsTabProps> = ({
  donorData,
  loading,
  selectedPartSlot,
  onFilterSlot,
  onSelectDonor,
}) => {
  if (loading) {
    return (
      <div className="h-64 flex items-center justify-center bg-slate-900/40 rounded-xl border border-slate-800">
        <span className="text-xs text-slate-400 font-mono">Finding donor movements...</span>
      </div>
    );
  }

  const donors = donorData?.donors || [];

  return (
    <div className="space-y-4">
      {/* Friendly Filter Bar */}
      <div className="flex flex-wrap items-center gap-1.5 pb-2 border-b border-slate-800">
        <span className="text-xs text-slate-400 mr-2">Filter by part:</span>
        {COMMON_PARTS.map((p) => {
          const active = selectedPartSlot === p.code;
          return (
            <button
              key={p.label}
              onClick={() => onFilterSlot(p.code)}
              className={`text-xs px-2.5 py-1 rounded-md transition-colors ${
                active
                  ? 'bg-slate-800 text-slate-100 font-medium'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      {/* Clean Donor Cards */}
      {donors.length === 0 ? (
        <div className="bg-slate-900/30 rounded-xl border border-slate-800/80 p-8 text-center text-xs text-slate-400">
          No donor matches found for this filter. Full part-level cross-references are currently cataloged for major Swiss & Japanese workhorse families (ETA, Sellita, Valjoux, Seiko).
        </div>
      ) : (
        <div className="divide-y divide-slate-800/80 border border-slate-800 rounded-xl bg-slate-900/60 overflow-hidden">
          {donors.map((donor) => (
            <div
              key={donor.donor_key}
              className="p-4 hover:bg-slate-850/50 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-semibold text-slate-100">
                    {donor.donor_name}
                  </h4>
                  <button
                    onClick={() => onSelectDonor(donor.donor_key)}
                    className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-0.5 font-medium"
                  >
                    View <ArrowUpRight className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="text-xs text-slate-400">
                  <span className="text-emerald-400 font-medium">{donor.shared_parts.length} compatible parts</span>
                  {' • '}
                  <span>{donor.coverage_pct}% of target assembly</span>
                </div>

                {/* Plain-English list of swappable parts */}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {donor.shared_parts.map((part) => (
                    <span
                      key={part.slot}
                      className="text-[11px] px-2 py-0.5 rounded bg-slate-950 text-slate-300 border border-slate-800"
                    >
                      {part.name}
                    </span>
                  ))}
                </div>
              </div>

              {/* Match Score Badge */}
              <div className="sm:text-right flex-shrink-0">
                <span className="text-[10px] text-slate-500 block uppercase font-mono tracking-wider">
                  Suitability
                </span>
                <span className="text-sm font-semibold text-slate-200">
                  {(donor.donor_score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
