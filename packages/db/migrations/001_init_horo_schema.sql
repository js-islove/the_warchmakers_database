-- =============================================================================
-- 001_init_horo_schema.sql
-- Horological Caliber Lineage & Compatibility Graph Engine (PostgreSQL 16)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE SCHEMA IF NOT EXISTS horo;

-- -----------------------------------------------------------------------------
-- 1. ENUM TYPES (Idempotent creation)
-- -----------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE horo.winding_type AS ENUM (
        'manual', 'automatic', 'quartz', 'mechaquartz', 'tuning_fork', 'spring_drive', 'solar'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE horo.production_status AS ENUM (
        'current', 'discontinued', 'vintage', 'obscure'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE horo.relation_kind AS ENUM (
        'DERIVED_FROM',
        'CLONE_OF',
        'USES_EBAUCHE',
        'HAS_MODULE',
        'SUCCESSION',
        'SHARES_ARCHITECTURE'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE horo.part_compatibility AS ENUM (
        'direct',        -- 100% drop-in interchangeable part
        'with_caveat',   -- Fits with minor adjustment (e.g. trim stem / swap regulator)
        'incompatible'   -- Known trap / does NOT fit
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------------------------------------------------------
-- 2. MANUFACTURERS & ARCHITECTURE FAMILIES
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS horo.manufacturer (
    id              BIGSERIAL PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    aliases         TEXT[] NOT NULL DEFAULT '{}',
    country_code    CHAR(2),
    founded_year    SMALLINT,
    roles           TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS horo.architecture_family (
    id              BIGSERIAL PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    root_maker_id   BIGINT REFERENCES horo.manufacturer(id),
    origin_year     SMALLINT,
    summary         TEXT
);

-- -----------------------------------------------------------------------------
-- 3. CALIBERS (Watch Movements - Curated YAML + 17jewels Scraped Data)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS horo.caliber (
    id                      BIGSERIAL PRIMARY KEY,
    canonical_key           TEXT NOT NULL UNIQUE,           -- e.g. 'eta:2824-2', 'agat:4282'
    manufacturer_id         BIGINT NOT NULL REFERENCES horo.manufacturer(id),
    family_id               BIGINT REFERENCES horo.architecture_family(id),
    reference               TEXT NOT NULL,                  -- e.g. '2824-2'
    display_name            TEXT NOT NULL,                  -- e.g. 'ETA 2824-2'

    winding                 horo.winding_type NOT NULL DEFAULT 'manual',
    functions               TEXT[] NOT NULL DEFAULT '{}',

    -- Physical Fitment Envelope (Used for Case / Hand Swap Substitute Matching)
    ligne                   NUMERIC(5,2),                   -- e.g. 11.50
    size_raw                TEXT,                           -- e.g. '11 1/2'''''
    diameter_mm             NUMERIC(5,2),                   -- e.g. 25.60
    casing_diameter_mm      NUMERIC(5,2),
    height_mm               NUMERIC(4,2),                   -- e.g. 4.60
    stem_height_mm          NUMERIC(4,2),                   -- e.g. 1.80
    crown_position_oclock   NUMERIC(3,1) NOT NULL DEFAULT 3.0,

    hour_hand_hole_mm       NUMERIC(4,2),                   -- e.g. 1.50
    minute_hand_post_mm     NUMERIC(4,2),                   -- e.g. 0.90
    seconds_hand_post_mm    NUMERIC(4,2),                   -- e.g. 0.25
    dial_feet_positions     NUMERIC(4,1)[] DEFAULT '{}',
    date_position_oclock    SMALLINT,

    -- Horological Performance & Escapement Specs
    beat_rate_vph           INTEGER,                        -- e.g. 28800
    jewels                  SMALLINT,                       -- e.g. 25
    power_reserve_h          NUMERIC(5,1),                   -- e.g. 38.0
    lift_angle_deg          NUMERIC(4,1),                   -- e.g. 50.0
    shock_protection        TEXT,                           -- e.g. 'Incabloc'
    escapement              TEXT,
    balance_type            TEXT,
    hairspring_direction    TEXT,
    moveable_stud           TEXT,
    adjust_mechanism        TEXT,

    -- Production & Sourcing Availability
    production_start        SMALLINT,
    production_end          SMALLINT,
    status                  horo.production_status NOT NULL DEFAULT 'vintage',
    accessibility_score     REAL NOT NULL DEFAULT 0.50 CHECK (accessibility_score BETWEEN 0 AND 1),

    -- Provenance, Diff Fingerprints & Flexible Scraped Specs (JSONB)
    source                  TEXT NOT NULL DEFAULT 'curated_yaml', -- 'curated_yaml' | '17jewels'
    source_url              TEXT,
    index_row_hash          TEXT,
    record_hash             TEXT,
    raw_specs               JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes                   TEXT,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS caliber_trgm_idx
    ON horo.caliber USING gin (display_name gin_trgm_ops, reference gin_trgm_ops);
CREATE INDEX IF NOT EXISTS caliber_envelope_idx
    ON horo.caliber (diameter_mm, height_mm, crown_position_oclock, winding);
CREATE INDEX IF NOT EXISTS caliber_family_idx
    ON horo.caliber (family_id);
CREATE INDEX IF NOT EXISTS caliber_manufacturer_idx
    ON horo.caliber (manufacturer_id);
CREATE INDEX IF NOT EXISTS caliber_raw_specs_gin_idx
    ON horo.caliber USING gin (raw_specs);

CREATE TABLE IF NOT EXISTS horo.caliber_alias (
    id              BIGSERIAL PRIMARY KEY,
    caliber_id      BIGINT NOT NULL REFERENCES horo.caliber(id) ON DELETE CASCADE,
    alias           TEXT NOT NULL,
    alias_norm      TEXT GENERATED ALWAYS AS (
                        regexp_replace(lower(alias), '[^a-z0-9]+', '', 'g')
                    ) STORED,
    kind            TEXT NOT NULL DEFAULT 'official',
    UNIQUE (caliber_id, alias)
);

CREATE INDEX IF NOT EXISTS caliber_alias_norm_idx ON horo.caliber_alias (alias_norm);
CREATE INDEX IF NOT EXISTS caliber_alias_trgm_idx ON horo.caliber_alias USING gin (alias gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- 4. INTERCHANGEABLE PARTS & PART CLASSES (Donor Matching Model)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS horo.part_type (
    id              SMALLSERIAL PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,           -- e.g. 'balance_complete', 'winding_stem'
    cs_number       TEXT,                           -- Swiss Ebauches dictionary code, e.g. '721', '401'
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    donor_weight    REAL NOT NULL DEFAULT 0.5 CHECK (donor_weight BETWEEN 0.05 AND 1.0),
    is_wear_item    BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS horo.part_class (
    id              BIGSERIAL PRIMARY KEY,
    part_type_id    SMALLINT NOT NULL REFERENCES horo.part_type(id),
    class_code      TEXT NOT NULL UNIQUE,           -- e.g. 'grp:eta2824_2_stem_401'
    description     TEXT,
    geometry        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS part_class_type_idx ON horo.part_class (part_type_id);

CREATE TABLE IF NOT EXISTS horo.part (
    id              BIGSERIAL PRIMARY KEY,
    part_type_id    SMALLINT NOT NULL REFERENCES horo.part_type(id),
    part_class_id   BIGINT NOT NULL REFERENCES horo.part_class(id),
    manufacturer_id BIGINT REFERENCES horo.manufacturer(id),
    part_number     TEXT NOT NULL,                  -- e.g. 'ETA-2801-2-401'
    supplier_codes  JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (manufacturer_id, part_number)
);

CREATE INDEX IF NOT EXISTS part_class_lookup_idx ON horo.part (part_class_id);

CREATE TABLE IF NOT EXISTS horo.caliber_part (
    caliber_id      BIGINT NOT NULL REFERENCES horo.caliber(id) ON DELETE CASCADE,
    part_id         BIGINT NOT NULL REFERENCES horo.part(id) ON DELETE CASCADE,
    part_type_id    SMALLINT NOT NULL REFERENCES horo.part_type(id),
    part_class_id   BIGINT NOT NULL REFERENCES horo.part_class(id),
    compatibility   horo.part_compatibility NOT NULL DEFAULT 'direct',
    quantity        SMALLINT NOT NULL DEFAULT 1,
    notes           TEXT,
    confidence      REAL NOT NULL DEFAULT 0.95 CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (caliber_id, part_id)
);

CREATE INDEX IF NOT EXISTS caliber_part_by_class_idx
    ON horo.caliber_part (part_class_id, caliber_id, compatibility);
CREATE INDEX IF NOT EXISTS caliber_part_by_caliber_idx
    ON horo.caliber_part (caliber_id, part_type_id);

-- -----------------------------------------------------------------------------
-- 5. LINEAGE GRAPH EDGES & PRECOMPUTED DONOR RANKINGS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS horo.caliber_relation (
    id                  BIGSERIAL PRIMARY KEY,
    from_caliber_id     BIGINT NOT NULL REFERENCES horo.caliber(id) ON DELETE CASCADE,
    to_caliber_id       BIGINT NOT NULL REFERENCES horo.caliber(id) ON DELETE CASCADE,
    kind                horo.relation_kind NOT NULL,
    subtype             TEXT,
    modification_degree SMALLINT CHECK (modification_degree BETWEEN 0 AND 5),
    valid_from_year     SMALLINT,
    notes               TEXT,
    confidence          REAL NOT NULL DEFAULT 0.95,
    CHECK (from_caliber_id <> to_caliber_id),
    UNIQUE (from_caliber_id, to_caliber_id, kind)
);

CREATE INDEX IF NOT EXISTS rel_from_idx ON horo.caliber_relation (from_caliber_id, kind);
CREATE INDEX IF NOT EXISTS rel_to_idx   ON horo.caliber_relation (to_caliber_id, kind);

CREATE TABLE IF NOT EXISTS horo.caliber_similarity (
    target_caliber_id   BIGINT NOT NULL REFERENCES horo.caliber(id) ON DELETE CASCADE,
    donor_caliber_id    BIGINT NOT NULL REFERENCES horo.caliber(id) ON DELETE CASCADE,
    shared_direct_cnt   SMALLINT NOT NULL,
    shared_caveat_cnt   SMALLINT NOT NULL,
    weighted_coverage   REAL NOT NULL,
    jaccard_score       REAL NOT NULL,
    donor_rank_score    REAL NOT NULL,
    top_shared_types    TEXT[] NOT NULL,
    PRIMARY KEY (target_caliber_id, donor_caliber_id)
);

CREATE INDEX IF NOT EXISTS sim_target_rank_idx
    ON horo.caliber_similarity (target_caliber_id, donor_rank_score DESC);

-- -----------------------------------------------------------------------------
-- 6. GRAPH TRAVERSAL & COMPATIBILITY SQL FUNCTIONS
-- -----------------------------------------------------------------------------

-- 6A. Upstream Ancestors (Base calibers / Ebauches / Cloned originals)
CREATE OR REPLACE FUNCTION horo.lineage_up(
    p_caliber_id BIGINT,
    p_max_depth  INT DEFAULT 6
)
RETURNS TABLE (
    depth           INT,
    from_id         BIGINT,
    to_id           BIGINT,
    kind            horo.relation_kind,
    subtype         TEXT,
    mod_degree      SMALLINT,
    confidence      REAL,
    notes           TEXT,
    path            BIGINT[]
) LANGUAGE sql STABLE AS $$
    WITH RECURSIVE walk AS (
        SELECT
            1 AS depth,
            r.from_caliber_id AS from_id,
            r.to_caliber_id   AS to_id,
            r.kind,
            r.subtype,
            r.modification_degree AS mod_degree,
            r.confidence,
            r.notes,
            ARRAY[r.from_caliber_id, r.to_caliber_id] AS path
        FROM horo.caliber_relation r
        WHERE r.from_caliber_id = p_caliber_id
          AND r.kind IN ('DERIVED_FROM', 'CLONE_OF', 'USES_EBAUCHE', 'SUCCESSION')

        UNION ALL

        SELECT
            w.depth + 1,
            r.from_caliber_id,
            r.to_caliber_id,
            r.kind,
            r.subtype,
            r.modification_degree,
            (w.confidence * r.confidence)::REAL,
            r.notes,
            w.path || r.to_caliber_id
        FROM walk w
        JOIN horo.caliber_relation r ON r.from_caliber_id = w.to_id
        WHERE w.depth < p_max_depth
          AND r.kind IN ('DERIVED_FROM', 'CLONE_OF', 'USES_EBAUCHE', 'SUCCESSION')
          AND NOT (r.to_caliber_id = ANY(w.path))
    )
    SELECT * FROM walk;
$$;

-- 6B. Downstream Descendants (Derivatives / Clones / Modified Calibers)
CREATE OR REPLACE FUNCTION horo.lineage_down(
    p_caliber_id BIGINT,
    p_max_depth  INT DEFAULT 6
)
RETURNS TABLE (
    depth           INT,
    from_id         BIGINT,
    to_id           BIGINT,
    kind            horo.relation_kind,
    subtype         TEXT,
    mod_degree      SMALLINT,
    confidence      REAL,
    notes           TEXT,
    path            BIGINT[]
) LANGUAGE sql STABLE AS $$
    WITH RECURSIVE walk AS (
        SELECT
            1 AS depth,
            r.from_caliber_id AS from_id,
            r.to_caliber_id   AS to_id,
            r.kind,
            r.subtype,
            r.modification_degree AS mod_degree,
            r.confidence,
            r.notes,
            ARRAY[r.to_caliber_id, r.from_caliber_id] AS path
        FROM horo.caliber_relation r
        WHERE r.to_caliber_id = p_caliber_id
          AND r.kind IN ('DERIVED_FROM', 'CLONE_OF', 'USES_EBAUCHE', 'SUCCESSION')

        UNION ALL

        SELECT
            w.depth + 1,
            r.from_caliber_id,
            r.to_caliber_id,
            r.kind,
            r.subtype,
            r.modification_degree,
            (w.confidence * r.confidence)::REAL,
            r.notes,
            w.path || r.from_caliber_id
        FROM walk w
        JOIN horo.caliber_relation r ON r.to_caliber_id = w.from_id
        WHERE w.depth < p_max_depth
          AND r.kind IN ('DERIVED_FROM', 'CLONE_OF', 'USES_EBAUCHE', 'SUCCESSION')
          AND NOT (r.from_caliber_id = ANY(w.path))
    )
    SELECT * FROM walk;
$$;

-- 6C. Live Donor Part-Sharing Query
CREATE OR REPLACE FUNCTION horo.donor_matches(
    p_target_caliber_id BIGINT,
    p_part_type_codes   TEXT[] DEFAULT NULL,
    p_limit             INT    DEFAULT 25
)
RETURNS TABLE (
    donor_caliber_id    BIGINT,
    donor_key           TEXT,
    donor_name          TEXT,
    accessibility       REAL,
    shared_direct_cnt   INT,
    shared_caveat_cnt   INT,
    weighted_coverage   REAL,
    donor_score         REAL,
    shared_parts        JSONB
) LANGUAGE sql STABLE AS $$
    WITH target_parts AS (
        SELECT
            cp.part_class_id,
            cp.part_type_id,
            pt.code         AS part_type_code,
            pt.name         AS part_type_name,
            pt.cs_number    AS cs_number,
            pt.donor_weight AS weight,
            p.part_number   AS target_part_number
        FROM horo.caliber_part cp
        JOIN horo.part_type pt ON pt.id = cp.part_type_id
        JOIN horo.part p       ON p.id  = cp.part_id
        WHERE cp.caliber_id = p_target_caliber_id
          AND cp.compatibility <> 'incompatible'
          AND (p_part_type_codes IS NULL OR pt.code = ANY(p_part_type_codes))
    ),
    target_total AS (
        SELECT COALESCE(SUM(weight), 1.0) AS total_weight FROM target_parts
    ),
    matches AS (
        SELECT
            dc.id              AS donor_id,
            tp.part_type_code,
            tp.part_type_name,
            tp.cs_number,
            tp.target_part_number,
            dp.part_number     AS donor_part_number,
            tp.weight,
            dcp.compatibility,
            dcp.notes,
            CASE dcp.compatibility
                WHEN 'direct'      THEN 1.0
                WHEN 'with_caveat' THEN 0.6
                ELSE 0.0
            END AS compat_factor
        FROM target_parts tp
        JOIN horo.caliber_part dcp ON dcp.part_class_id = tp.part_class_id
        JOIN horo.part dp          ON dp.id = dcp.part_id
        JOIN horo.caliber dc       ON dc.id = dcp.caliber_id
        WHERE dcp.caliber_id <> p_target_caliber_id
          AND dcp.compatibility <> 'incompatible'
    )
    SELECT
        c.id                                                                 AS donor_caliber_id,
        c.canonical_key                                                      AS donor_key,
        c.display_name                                                       AS donor_name,
        c.accessibility_score                                                AS accessibility,
        COUNT(*) FILTER (WHERE m.compatibility = 'direct')::INT              AS shared_direct_cnt,
        COUNT(*) FILTER (WHERE m.compatibility = 'with_caveat')::INT         AS shared_caveat_cnt,
        (SUM(m.weight * m.compat_factor) / tt.total_weight)::REAL            AS weighted_coverage,
        (
            0.65 * (SUM(m.weight * m.compat_factor) / tt.total_weight) +
            0.35 * c.accessibility_score
        )::REAL                                                              AS donor_score,
        jsonb_agg(
            jsonb_build_object(
                'slot',         m.part_type_code,
                'name',         m.part_type_name,
                'cs_number',    m.cs_number,
                'target_part',  m.target_part_number,
                'donor_part',   m.donor_part_number,
                'compat',       m.compatibility,
                'notes',        m.notes
            ) ORDER BY m.weight DESC
        )                                                                    AS shared_parts
    FROM matches m
    JOIN horo.caliber c ON c.id = m.donor_id
    CROSS JOIN target_total tt
    GROUP BY c.id, c.canonical_key, c.display_name, c.accessibility_score, tt.total_weight
    ORDER BY donor_score DESC
    LIMIT p_limit;
$$;

-- 6D. Drop-In Movement Substitute Finder (Physical Envelope & Hand Fitment)
CREATE OR REPLACE FUNCTION horo.substitutes(
    p_target_caliber_id BIGINT,
    p_diameter_tol_mm   NUMERIC DEFAULT 0.30,
    p_height_tol_mm     NUMERIC DEFAULT 0.60,
    p_stem_tol_mm       NUMERIC DEFAULT 0.15
)
RETURNS TABLE (
    candidate_id        BIGINT,
    candidate_key       TEXT,
    candidate_name      TEXT,
    winding             horo.winding_type,
    fit_class           TEXT,
    compatibility_score REAL,
    delta_diameter_mm   NUMERIC,
    delta_height_mm     NUMERIC,
    delta_stem_mm       NUMERIC,
    hands_compatible    BOOLEAN,
    date_aligned        BOOLEAN,
    modifications       TEXT[]
) LANGUAGE sql STABLE AS $$
    WITH t AS (
        SELECT * FROM horo.caliber WHERE id = p_target_caliber_id
    )
    SELECT
        c.id,
        c.canonical_key,
        c.display_name,
        c.winding,
        CASE
            WHEN ABS(c.diameter_mm - t.diameter_mm) <= 0.05
             AND ABS(COALESCE(c.height_mm, t.height_mm) - COALESCE(t.height_mm, c.height_mm)) <= 0.15
             AND COALESCE(ABS(c.stem_height_mm - t.stem_height_mm), 0) <= 0.05
             AND COALESCE(c.hour_hand_hole_mm = t.hour_hand_hole_mm, true)
             AND COALESCE(c.minute_hand_post_mm = t.minute_hand_post_mm, true)
                THEN 'direct_swap'
            WHEN ABS(c.diameter_mm - t.diameter_mm) <= 0.15
             AND ABS(COALESCE(c.height_mm, t.height_mm) - COALESCE(t.height_mm, c.height_mm)) <= 0.35
                THEN 'minor_mod'
            ELSE 'case_mod'
        END AS fit_class,
        GREATEST(0.0, (
            1.0
            - 0.8 * ABS(c.diameter_mm - t.diameter_mm)
            - 0.4 * ABS(COALESCE(c.height_mm, t.height_mm) - COALESCE(t.height_mm, c.height_mm))
            - 1.2 * COALESCE(ABS(c.stem_height_mm - t.stem_height_mm), 0.05)
            - CASE WHEN COALESCE(c.hour_hand_hole_mm = t.hour_hand_hole_mm, true) THEN 0 ELSE 0.15 END
        ))::REAL AS compatibility_score,
        (c.diameter_mm - t.diameter_mm) AS delta_diameter_mm,
        (c.height_mm   - t.height_mm)   AS delta_height_mm,
        (c.stem_height_mm - t.stem_height_mm) AS delta_stem_mm,
        (
            COALESCE(c.hour_hand_hole_mm = t.hour_hand_hole_mm, true) AND
            COALESCE(c.minute_hand_post_mm = t.minute_hand_post_mm, true) AND
            COALESCE(c.seconds_hand_post_mm = t.seconds_hand_post_mm, true)
        ) AS hands_compatible,
        (c.date_position_oclock IS NOT DISTINCT FROM t.date_position_oclock) AS date_aligned,
        ARRAY_REMOVE(ARRAY[
            CASE WHEN ABS(c.diameter_mm - t.diameter_mm) > 0.05
                 THEN format('Movement spacer ring adjustment (%s mm diameter delta)', c.diameter_mm - t.diameter_mm) END,
            CASE WHEN c.height_mm IS NOT NULL AND t.height_mm IS NOT NULL AND ABS(c.height_mm - t.height_mm) > 0.15
                 THEN format('Caseback clearance check (%s mm height delta)', c.height_mm - t.height_mm) END,
            CASE WHEN c.stem_height_mm IS NOT NULL AND t.stem_height_mm IS NOT NULL AND ABS(c.stem_height_mm - t.stem_height_mm) > 0.05
                 THEN format('Stem height offset (%s mm)', c.stem_height_mm - t.stem_height_mm) END,
            CASE WHEN c.hour_hand_hole_mm IS DISTINCT FROM t.hour_hand_hole_mm
                  AND c.hour_hand_hole_mm IS NOT NULL AND t.hour_hand_hole_mm IS NOT NULL
                 THEN format('Hour hand hole differs (%s mm vs %s mm)', c.hour_hand_hole_mm, t.hour_hand_hole_mm) END,
            CASE WHEN c.minute_hand_post_mm IS DISTINCT FROM t.minute_hand_post_mm
                  AND c.minute_hand_post_mm IS NOT NULL AND t.minute_hand_post_mm IS NOT NULL
                 THEN format('Minute hand hole differs (%s mm vs %s mm)', c.minute_hand_post_mm, t.minute_hand_post_mm) END,
            CASE WHEN c.date_position_oclock IS DISTINCT FROM t.date_position_oclock
                  AND (c.date_position_oclock IS NOT NULL OR t.date_position_oclock IS NOT NULL)
                 THEN 'Date window alignment differs' END
        ], NULL) AS modifications
    FROM horo.caliber c
    CROSS JOIN t
    WHERE c.id <> t.id
      AND t.diameter_mm IS NOT NULL
      AND c.diameter_mm IS NOT NULL
      AND c.crown_position_oclock = t.crown_position_oclock
      AND ABS(c.diameter_mm - t.diameter_mm) <= p_diameter_tol_mm
      AND (
          (t.height_mm IS NOT NULL AND c.height_mm IS NOT NULL AND ABS(c.height_mm - t.height_mm) <= p_height_tol_mm)
          OR (c.family_id IS NOT NULL AND c.family_id = t.family_id)
      )
      AND COALESCE(ABS(c.stem_height_mm - t.stem_height_mm), 0) <= p_stem_tol_mm
    ORDER BY compatibility_score DESC;
$$;
