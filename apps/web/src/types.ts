/**
 * TypeScript Data Models for Horological Engine
 * Matches FastAPI responses exactly
 */

export interface HealthStats {
  status: string;
  engine: 'postgresql' | 'memory_fallback';
  counts: {
    calibers: number;
    manufacturers: number;
    lineage_relations: number;
    caliber_parts: number;
  };
}

export interface Manufacturer {
  slug: string;
  name: string;
  country_code: string | null;
  founded_year: number | null;
  caliber_count: number;
}

export interface MovementSummary {
  canonical_key: string;
  display_name: string;
  reference: string;
  manufacturer_slug: string;
  manufacturer_name: string;
  winding: string;
  ligne: number | null;
  diameter_mm: number | null;
  height_mm: number | null;
  beat_rate_vph: number | null;
  jewels: number | null;
  shock_protection: string | null;
  status: string;
  source: 'curated_yaml' | '17jewels';
  source_url: string | null;
}

export interface SearchResponse {
  total: number;
  limit: number;
  offset: number;
  items: MovementSummary[];
}

export interface DocumentedPart {
  slot: string;
  name: string;
  cs_number: string;
  category: string;
  part_number: string;
  interchange_group: string;
  compatibility: 'direct' | 'with_caveat' | 'incompatible';
  donor_weight: number;
  notes?: string | null;
}

export interface MovementDetail extends MovementSummary {
  family_slug?: string | null;
  family_name?: string | null;
  functions: string[];
  size_raw?: string | null;
  stem_height_mm?: number | null;
  crown_position_oclock: number;
  hour_hand_hole_mm?: number | null;
  minute_hand_post_mm?: number | null;
  seconds_hand_post_mm?: number | null;
  date_position_oclock?: number | null;
  power_reserve_h?: number | null;
  lift_angle_deg?: number | null;
  escapement?: string | null;
  balance_type?: string | null;
  hairspring_direction?: string | null;
  moveable_stud?: string | null;
  adjust_mechanism?: string | null;
  production_start?: number | null;
  production_end?: number | null;
  accessibility_score: number;
  raw_specs: Record<string, string>;
  parts: DocumentedPart[];
}

export interface LineageNode {
  id: string; // canonical_key
  display_name: string;
  manufacturer: string;
  winding: string;
  diameter_mm: number | null;
  height_mm: number | null;
  beat_rate_vph: number | null;
  jewels: number | null;
  production_start: number | null;
  status: string;
  is_focus: boolean;
}

export interface LineageEdge {
  id: string;
  source: string;
  target: string;
  kind: 'DERIVED_FROM' | 'CLONE_OF' | 'USES_EBAUCHE' | 'SUCCESSION' | 'SHARES_ARCHITECTURE';
  subtype?: string | null;
  modification_degree?: number | null;
  confidence: number;
  notes?: string | null;
}

export interface LineageGraphResponse {
  focus: string;
  nodes: LineageNode[];
  edges: LineageEdge[];
  meta: {
    node_count: number;
    edge_count: number;
    max_depth: number;
  };
}

export interface SharedPartMatch {
  slot: string;
  name: string;
  cs_number: string;
  target_part: string;
  donor_part: string;
  compat: 'direct' | 'with_caveat';
  notes?: string | null;
}

export interface DonorMatch {
  donor_key: string;
  donor_name: string;
  accessibility: number;
  shared_direct_cnt: number;
  shared_caveat_cnt: number;
  coverage_pct: number;
  donor_score: number;
  shared_parts: SharedPartMatch[];
}

export interface DonorMatchesResponse {
  target_caliber: string;
  target_display_name: string;
  part_filter: string | null;
  donors: DonorMatch[];
}

export interface SubstituteCandidate {
  candidate_key: string;
  candidate_name: string;
  winding: string;
  fit_class: 'direct_swap' | 'minor_mod' | 'case_mod';
  compatibility_score: number;
  delta_diameter_mm: number | null;
  delta_height_mm: number | null;
  delta_stem_mm: number | null;
  hands_compatible: boolean;
  date_aligned: boolean;
  modifications: string[];
}

export interface SubstitutesResponse {
  target_caliber: string;
  target_display_name: string;
  target_diameter_mm: number | null;
  target_height_mm: number | null;
  substitutes: SubstituteCandidate[];
}
