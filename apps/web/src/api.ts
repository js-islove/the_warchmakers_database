import {
  HealthStats,
  Manufacturer,
  SearchResponse,
  MovementDetail,
  LineageGraphResponse,
  DonorMatchesResponse,
  SubstitutesResponse,
} from './types';

const API_BASE = '/api';

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API Error [${res.status}]: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function getHealthStats(): Promise<HealthStats> {
  return fetchJson<HealthStats>(`${API_BASE}/health`);
}

export async function getManufacturers(): Promise<Manufacturer[]> {
  return fetchJson<Manufacturer[]>(`${API_BASE}/manufacturers`);
}

export async function searchMovements(params: {
  q?: string;
  brand?: string;
  winding?: string;
  source?: string;
  limit?: number;
  offset?: number;
}): Promise<SearchResponse> {
  const query = new URLSearchParams();
  if (params.q) query.set('q', params.q);
  if (params.brand) query.set('brand', params.brand);
  if (params.winding) query.set('winding', params.winding);
  if (params.source) query.set('source', params.source);
  if (params.limit) query.set('limit', String(params.limit));
  if (params.offset) query.set('offset', String(params.offset));

  return fetchJson<SearchResponse>(`${API_BASE}/search?${query.toString()}`);
}

export async function getMovementDetail(canonicalKey: string): Promise<MovementDetail> {
  return fetchJson<MovementDetail>(`${API_BASE}/calibers/${encodeURIComponent(canonicalKey)}`);
}

export async function getLineageGraph(canonicalKey: string, depth = 5): Promise<LineageGraphResponse> {
  return fetchJson<LineageGraphResponse>(
    `${API_BASE}/calibers/${encodeURIComponent(canonicalKey)}/lineage?depth=${depth}`
  );
}

export async function getDonorMatches(
  canonicalKey: string,
  partSlot?: string | null
): Promise<DonorMatchesResponse> {
  const query = partSlot ? `?part_slot=${encodeURIComponent(partSlot)}` : '';
  return fetchJson<DonorMatchesResponse>(
    `${API_BASE}/calibers/${encodeURIComponent(canonicalKey)}/donors${query}`
  );
}

export async function getSubstitutes(canonicalKey: string): Promise<SubstitutesResponse> {
  return fetchJson<SubstitutesResponse>(
    `${API_BASE}/calibers/${encodeURIComponent(canonicalKey)}/substitutes`
  );
}
