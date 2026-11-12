import React, { useState, useEffect, useTransition } from 'react';
import {
  Search,
  RotateCcw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  HealthStats,
  Manufacturer,
  MovementSummary,
  MovementDetail,
  LineageGraphResponse,
  DonorMatchesResponse,
  SubstitutesResponse,
} from './types';
import {
  getHealthStats,
  getManufacturers,
  searchMovements,
  getMovementDetail,
  getLineageGraph,
  getDonorMatches,
  getSubstitutes,
} from './api';
import { FamilyTreeTab } from './components/FamilyTreeTab';
import { DonorPartsTab } from './components/DonorPartsTab';
import { CaseSwapTab } from './components/CaseSwapTab';

const BENCHMARKS = [
  { key: 'eta:2824-2', label: 'ETA 2824-2' },
  { key: 'sellita:sw200-1', label: 'Sellita SW200-1' },
  { key: 'valjoux:7750', label: 'Valjoux 7750' },
  { key: 'seiko:nh35a', label: 'Seiko NH35A' },
  { key: 'as:1525', label: 'AS 1525' },
];

export const App: React.FC = () => {
  const [selectedKey, setSelectedKey] = useState<string>('eta:2824-2');
  const [activeTab, setActiveTab] = useState<'lineage' | 'donors' | 'substitutes'>('lineage');

  // Search & filter state
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [brandFilter, setBrandFilter] = useState<string>('');
  const [windingFilter, setWindingFilter] = useState<string>('');
  const [, startTransition] = useTransition();

  // Data states
  const [health, setHealth] = useState<HealthStats | null>(null);
  const [manufacturers, setManufacturers] = useState<Manufacturer[]>([]);
  const [searchResults, setSearchResults] = useState<MovementSummary[]>([]);
  const [searchTotal, setSearchTotal] = useState<number>(0);
  const [isSearching, setIsSearching] = useState<boolean>(false);

  // Selected movement details
  const [detail, setDetail] = useState<MovementDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(true);

  // Tab data states
  const [lineage, setLineage] = useState<LineageGraphResponse | null>(null);
  const [loadingLineage, setLoadingLineage] = useState<boolean>(false);

  const [donorData, setDonorData] = useState<DonorMatchesResponse | null>(null);
  const [selectedPartSlot, setSelectedPartSlot] = useState<string | null>(null);
  const [loadingDonors, setLoadingDonors] = useState<boolean>(false);

  const [substitutes, setSubstitutes] = useState<SubstitutesResponse | null>(null);
  const [loadingSubs, setLoadingSubs] = useState<boolean>(false);

  // Secondary details toggle (clean & quiet)
  const [showMoreSpecs, setShowMoreSpecs] = useState<boolean>(false);

  useEffect(() => {
    getHealthStats().then(setHealth).catch(console.error);
    getManufacturers().then(setManufacturers).catch(console.error);
  }, []);

  useEffect(() => {
    setIsSearching(true);
    const timer = setTimeout(() => {
      searchMovements({
        q: searchQuery || undefined,
        brand: brandFilter || undefined,
        winding: windingFilter || undefined,
        limit: 100,
      })
        .then((res) => {
          setSearchResults(res.items);
          setSearchTotal(res.total);
        })
        .catch(console.error)
        .finally(() => setIsSearching(false));
    }, 200);

    return () => clearTimeout(timer);
  }, [searchQuery, brandFilter, windingFilter]);

  useEffect(() => {
    if (!selectedKey) return;
    setLoadingDetail(true);
    getMovementDetail(selectedKey)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoadingDetail(false));
  }, [selectedKey]);

  useEffect(() => {
    if (!selectedKey) return;

    if (activeTab === 'lineage') {
      setLoadingLineage(true);
      getLineageGraph(selectedKey, 5)
        .then(setLineage)
        .catch(console.error)
        .finally(() => setLoadingLineage(false));
    } else if (activeTab === 'donors') {
      setLoadingDonors(true);
      getDonorMatches(selectedKey, selectedPartSlot)
        .then(setDonorData)
        .catch(console.error)
        .finally(() => setLoadingDonors(false));
    } else if (activeTab === 'substitutes') {
      setLoadingSubs(true);
      getSubstitutes(selectedKey)
        .then(setSubstitutes)
        .catch(console.error)
        .finally(() => setLoadingSubs(false));
    }
  }, [selectedKey, activeTab, selectedPartSlot]);

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100 antialiased selection:bg-slate-800">
      {/* ── TOP HEADER ── */}
      <header className="border-b border-slate-800 bg-slate-900/60 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold tracking-tight text-slate-200">
              Watch Movement Reference
            </span>
            {health && (
              <span className="text-[11px] text-slate-500 font-mono hidden sm:inline">
                {health.counts.calibers.toLocaleString()} movements indexed
              </span>
            )}
          </div>

          {/* Clean Search Input */}
          <div className="flex-1 max-w-md mx-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search caliber or maker (e.g. 2824, SW200, 7750, AS)..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-slate-900 border border-slate-800 rounded-md pl-8 pr-7 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-slate-600 transition-colors"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                >
                  <RotateCcw className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* ── MAIN WORKSPACE ── */}
      <div className="flex-1 max-w-7xl w-full mx-auto p-4 grid grid-cols-1 md:grid-cols-12 gap-5">
        {/* Left Column: Movement List (4 cols) */}
        <aside className="md:col-span-4 flex flex-col bg-slate-900/40 border border-slate-800/80 rounded-lg overflow-hidden h-[calc(100vh-80px)]">
          {/* Benchmarks shortcut */}
          <div className="p-3 border-b border-slate-800 bg-slate-900/20">
            <div className="flex flex-wrap gap-1">
              {BENCHMARKS.map((b) => (
                <button
                  key={b.key}
                  onClick={() => startTransition(() => setSelectedKey(b.key))}
                  className={`text-xs px-2 py-0.5 rounded transition-colors ${
                    selectedKey === b.key
                      ? 'bg-slate-800 text-slate-100 font-medium'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-850'
                  }`}
                >
                  {b.label}
                </button>
              ))}
            </div>
          </div>

          {/* Simple Filters */}
          <div className="p-3 border-b border-slate-800 grid grid-cols-2 gap-2 text-xs">
            <select
              value={brandFilter}
              onChange={(e) => setBrandFilter(e.target.value)}
              className="bg-slate-900 border border-slate-800 rounded px-2 py-1 text-slate-300 focus:outline-none focus:border-slate-600"
            >
              <option value="">All Brands</option>
              {manufacturers.map((m) => (
                <option key={m.slug} value={m.slug}>
                  {m.name}
                </option>
              ))}
            </select>

            <select
              value={windingFilter}
              onChange={(e) => setWindingFilter(e.target.value)}
              className="bg-slate-900 border border-slate-800 rounded px-2 py-1 text-slate-300 focus:outline-none focus:border-slate-600"
            >
              <option value="">All Winding</option>
              <option value="automatic">Automatic</option>
              <option value="manual">Manual</option>
              <option value="quartz">Quartz</option>
            </select>
          </div>

          {/* List Count Header */}
          <div className="px-3 py-1.5 border-b border-slate-800 text-[11px] text-slate-500 font-mono flex items-center justify-between">
            <span>{searchTotal} matches</span>
            {isSearching && <span>searching...</span>}
          </div>

          {/* Movement List */}
          <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60">
            {searchResults.map((item) => {
              const active = item.canonical_key === selectedKey;
              return (
                <div
                  key={item.canonical_key}
                  onClick={() => setSelectedKey(item.canonical_key)}
                  className={`p-3 cursor-pointer text-left transition-colors ${
                    active ? 'bg-slate-800 text-slate-100' : 'hover:bg-slate-900/60 text-slate-300'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-200 truncate">
                      {item.display_name}
                    </span>
                    <span className="text-[11px] text-slate-400 capitalize flex-shrink-0">
                      {item.winding}
                    </span>
                  </div>

                  <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                    <span className="truncate">{item.manufacturer_name}</span>
                    {item.diameter_mm && (
                      <>
                        <span>•</span>
                        <span className="font-mono">{item.diameter_mm} mm</span>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        {/* Right Column: Selected Movement Workspace (8 cols) */}
        <main className="md:col-span-8 flex flex-col gap-4">
          {loadingDetail && !detail ? (
            <div className="h-64 flex items-center justify-center bg-slate-900/20 border border-slate-800 rounded-lg text-slate-500 text-xs">
              Loading movement details...
            </div>
          ) : detail ? (
            <>
              {/* Movement Summary Banner */}
              <div className="bg-slate-900/40 border border-slate-800 rounded-lg p-5">
                <div className="flex flex-wrap items-start justify-between gap-3 pb-3 border-b border-slate-800/80">
                  <div>
                    <h2 className="text-xl font-bold text-slate-100">
                      {detail.display_name}
                    </h2>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {detail.manufacturer_name} • <span className="capitalize">{detail.winding}</span>
                      {detail.jewels ? ` • ${detail.jewels} Jewels` : ''}
                      {detail.source_url && (
                        <a
                          href={detail.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="ml-2 text-slate-500 hover:text-slate-300 inline-flex items-center gap-0.5"
                        >
                          Source <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </p>
                  </div>

                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 capitalize">
                    {detail.status}
                  </span>
                </div>

                {/* 4 Essential Specs Row (Clean, readable, zero noise) */}
                <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
                  <div>
                    <span className="text-slate-500 text-[11px] block">Diameter</span>
                    <span className="text-sm font-semibold text-slate-200 font-mono">
                      {detail.diameter_mm ? `${detail.diameter_mm} mm` : '—'}
                    </span>
                  </div>

                  <div>
                    <span className="text-slate-500 text-[11px] block">Height (Thickness)</span>
                    <span className="text-sm font-semibold text-slate-200 font-mono">
                      {detail.height_mm ? `${detail.height_mm} mm` : '—'}
                    </span>
                  </div>

                  <div>
                    <span className="text-slate-500 text-[11px] block">Beat Rate</span>
                    <span className="text-sm font-semibold text-slate-200 font-mono">
                      {detail.beat_rate_vph ? `${detail.beat_rate_vph.toLocaleString()} vph` : '—'}
                    </span>
                  </div>

                  <div>
                    <span className="text-slate-500 text-[11px] block">Power Reserve</span>
                    <span className="text-sm font-semibold text-slate-200 font-mono">
                      {detail.power_reserve_h ? `${detail.power_reserve_h} hours` : (detail.lift_angle_deg ? `${detail.lift_angle_deg}° lift` : '—')}
                    </span>
                  </div>
                </div>

                {/* Optional Collapsible Technical Notes (Uncluttered) */}
                <div className="mt-4 pt-3 border-t border-slate-800/80">
                  <button
                    onClick={() => setShowMoreSpecs(!showMoreSpecs)}
                    className="text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1 font-medium"
                  >
                    {showMoreSpecs ? 'Hide secondary specifications' : 'Show secondary specifications (stem, shock, hand sizes)'}
                    {showMoreSpecs ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  </button>

                  {showMoreSpecs && (
                    <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs text-slate-400 bg-slate-950 p-3 rounded border border-slate-800 font-mono">
                      <div>
                        <span className="text-slate-500 block text-[10px]">Stem Height</span>
                        <span>{detail.stem_height_mm ? `${detail.stem_height_mm} mm` : '—'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">Shock Protection</span>
                        <span>{detail.shock_protection || '—'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">Hand Hole Sizes</span>
                        <span>
                          {detail.hour_hand_hole_mm
                            ? `${detail.hour_hand_hole_mm}/${detail.minute_hand_post_mm}/${detail.seconds_hand_post_mm}`
                            : '—'}
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">Escapement</span>
                        <span>{detail.escapement || 'Lever'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">Lift Angle</span>
                        <span>{detail.lift_angle_deg ? `${detail.lift_angle_deg}°` : '—'}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">Production Period</span>
                        <span>
                          {detail.production_start ? `${detail.production_start} - ${detail.production_end || 'present'}` : 'Vintage'}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* ── 3 CLEAN TABS ── */}
              <div className="bg-slate-900/40 border border-slate-800 rounded-lg overflow-hidden">
                {/* Tab Buttons */}
                <div className="flex border-b border-slate-800 bg-slate-900/60 px-4 text-xs font-medium">
                  <button
                    onClick={() => setActiveTab('lineage')}
                    className={`py-3 px-3 border-b-2 transition-colors ${
                      activeTab === 'lineage'
                        ? 'border-slate-100 text-slate-100 font-semibold'
                        : 'border-transparent text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    1. Family Tree (Lineage)
                  </button>

                  <button
                    onClick={() => setActiveTab('donors')}
                    className={`py-3 px-3 border-b-2 transition-colors ${
                      activeTab === 'donors'
                        ? 'border-slate-100 text-slate-100 font-semibold'
                        : 'border-transparent text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    2. Compatible Donors
                  </button>

                  <button
                    onClick={() => setActiveTab('substitutes')}
                    className={`py-3 px-3 border-b-2 transition-colors ${
                      activeTab === 'substitutes'
                        ? 'border-slate-100 text-slate-100 font-semibold'
                        : 'border-transparent text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    3. Case Substitutes
                  </button>
                </div>

                {/* Tab Content */}
                <div className="p-4">
                  {activeTab === 'lineage' && (
                    <FamilyTreeTab
                      lineage={lineage}
                      loading={loadingLineage}
                      onSelectMovement={(key) => setSelectedKey(key)}
                    />
                  )}

                  {activeTab === 'donors' && (
                    <DonorPartsTab
                      donorData={donorData}
                      loading={loadingDonors}
                      selectedPartSlot={selectedPartSlot}
                      onFilterSlot={(slot) => setSelectedPartSlot(slot)}
                      onSelectDonor={(key) => setSelectedKey(key)}
                    />
                  )}

                  {activeTab === 'substitutes' && (
                    <CaseSwapTab
                      substitutesData={substitutes}
                      loading={loadingSubs}
                      onSelectSubstitute={(key) => setSelectedKey(key)}
                    />
                  )}
                </div>
              </div>
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
};
export default App;
