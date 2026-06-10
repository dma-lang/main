-- Capability Intelligence Agent - backend schema (PostgreSQL 16 + pgvector)
-- Generated reference DDL. Control plane = migrations; data plane (cat_<version>) = emitted by the schema-mapping studio.
-- Requires: CREATE EXTENSION IF NOT EXISTS vector;  CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS control;

-- ============ Enumerations (shared) ============
CREATE TYPE claim_label      AS ENUM ('FACT','INFERENCE','HYPOTHESIS','CEILING_ESTIMATE');
CREATE TYPE source_tier      AS ENUM ('T1','T2','T3','T4','T5');
CREATE TYPE lifecycle_state  AS ENUM ('emerging','rising','stable','declining','fading','dead');
CREATE TYPE suggestion_status AS ENUM ('pending','staged','applied','rejected','expired');
CREATE TYPE gate_verdict     AS ENUM ('pass','fail');
CREATE TYPE magnitude        AS ENUM ('HIGH','MEDIUM','LOW');
CREATE TYPE confidence_level AS ENUM ('HIGH','MEDIUM','LOW');
CREATE TYPE mapping_status   AS ENUM ('confirmed','review','custom','ignored','unmapped');
CREATE TYPE carry_status     AS ENUM ('confirmed','review','unmapped');
CREATE TYPE relation_type    AS ENUM ('belongs_to','addresses','delivered_by','maps_to_offering',
                                      'uses_platform','tagged_theme','has_persona','has_usecase','custom');
CREATE TYPE evidence_kind    AS ENUM ('sow_chunk','news','vendor_event','benchmark','regulatory','catalogue');
CREATE TYPE vendor_event_type AS ENUM ('product_launch','partnership','deprecation','pricing_change',
                                       'executive_move','security_incident','regulatory_action','case_study');
CREATE TYPE kg_layer         AS ENUM ('A_deterministic','B_proposed');
CREATE TYPE sheet_role       AS ENUM ('entity','link','matrix','aggregate','control','crosswalk','narrative');
CREATE TYPE cardinality      AS ENUM ('one_to_one','one_to_many','many_to_one','many_to_many');
CREATE TYPE cascade_kind     AS ENUM ('direct','indirect','none');


-- ============ Control plane: identity, versions, mapping, ingest ============
CREATE TABLE control.users (
    uid             text PRIMARY KEY,
    email           text NOT NULL UNIQUE,
    is_admin        boolean NOT NULL DEFAULT false,
    preferences     jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- One row per catalogue version; schema_name points at its data-plane namespace (e.g. cat_v7).
CREATE TABLE control.catalogue_version (
    version_id      text PRIMARY KEY,            -- 'v5', 'v7', ...
    label           text NOT NULL,
    source_layout   text,                        -- detected adapter
    schema_name     text NOT NULL UNIQUE,        -- 'cat_v5'
    status          text NOT NULL DEFAULT 'draft', -- draft | provisioned | archived
    created_by      text REFERENCES control.users(uid),
    created_at      timestamptz NOT NULL DEFAULT now(),
    notes           text
);

CREATE TABLE control.ingest_run (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text REFERENCES control.catalogue_version(version_id),
    source          text NOT NULL,               -- workbook | jira | news | vendor | sow
    status          text NOT NULL,               -- running | ok | failed
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    stats           jsonb NOT NULL DEFAULT '{}'
);

-- Every sheet/tab in a version workbook, with the role it plays and the entity it maps to.
-- This is what lets the studio reason about sheet-to-sheet relationships rather than loose fields.
CREATE TABLE control.catalogue_sheet (
    sheet_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    sheet_name      text NOT NULL,               -- '2_Capability_Map', '12_Offering_SubCap_Matrix', ...
    sheet_role      sheet_role NOT NULL,
    maps_to_entity  text,                         -- canonical entity this sheet populates
    row_count       integer,
    UNIQUE (version_id, sheet_name)
);

-- The schema-mapping studio output: how each source field maps to the canonical model (FR-2).
CREATE TABLE control.source_field_mapping (
    mapping_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    sheet_id        uuid REFERENCES control.catalogue_sheet(sheet_id),
    source_field    text NOT NULL,
    canonical_entity text,                        -- null when ignored
    canonical_field text,                         -- null when ignored / custom
    confidence      numeric(4,3),                 -- 0..1 from auto-map
    status          mapping_status NOT NULL,
    is_custom       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version_id, source_field)
);

-- Inter-sheet relationships, captured during mapping. Each row is a join between two sheets
-- (entities): the key columns, the cardinality, the link/matrix sheet that realises it, and
-- whether toggling the parent cascades to the child (and directly or indirectly). The cascade
-- engine reads these rows for a version to compute the dependency set; provisioning turns
-- one_to_many / many_to_one rows into foreign keys and many_to_many rows into link tables.
CREATE TABLE control.relation_def (
    relation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    from_entity     text NOT NULL,               -- e.g. subcap
    from_field      text NOT NULL,               -- e.g. subcap_id
    rel_type        relation_type NOT NULL,
    to_entity       text NOT NULL,               -- e.g. offering
    to_field        text NOT NULL,
    card            cardinality NOT NULL,
    via_sheet       text,                         -- the link/matrix sheet, e.g. 12_Offering_SubCap_Matrix
    is_cascade      boolean NOT NULL DEFAULT false,
    cascade_kind    cascade_kind NOT NULL DEFAULT 'none',
    cascaded_from   uuid REFERENCES control.relation_def(relation_id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Subcap-level crosswalk between catalogue versions (from each version _R1_Source_Reference sheet).
-- This is the deterministic bridge the story carry-forward uses to relate v5 subcaps to v7 subcaps.
CREATE TABLE control.version_crosswalk (
    crosswalk_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_version    text NOT NULL REFERENCES control.catalogue_version(version_id),
    from_subcap     text NOT NULL,               -- base id in from_version (SV suffix stripped)
    to_version      text NOT NULL REFERENCES control.catalogue_version(version_id),
    to_subcap       text,                         -- null when a v5 subcap has no v7 successor
    note            text,
    UNIQUE (from_version, from_subcap, to_version)
);


-- ============ Canonical story corpus + carry-forward (control plane) ============
-- The Jira Full Story Catalog is THE canonical, authoritative story source (FR-3, D11): the
-- "Actual (Real Client)" export, 14,406 real stories (the full export is on the order of ~16,000
-- rows; synthetic rows are flagged and excluded from analysis unless a trend surfaces them, D12).
-- It is version-independent: a story is mapped once (against v5) and then related to each catalogue
-- version through control.story_subcap_carry, never duplicated per version.
CREATE TABLE control.story (
    story_key           text PRIMARY KEY,
    source_system       text NOT NULL DEFAULT 'jira',     -- canonical source = Jira
    source_export       text,                              -- the export this row came from
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    project_key         text,
    epic_key            text,
    sub_cap_id          text NOT NULL,           -- as mapped in the source version (may carry a SV suffix)
    cap_id              text,
    pillar_id           text,
    category_id         text,
    category_name       text,
    cap_name            text,
    sub_cap_name        text,
    tier                text,
    story_sv_code       text,
    project_sv_code     text,
    reusability_layer   text,
    population          text,
    summary             text,
    description         text,
    ac_text             text,
    solution_design_text text,
    ac_quality          numeric,
    sd_quality          numeric,
    delivery_score      numeric,
    composite_score     numeric,
    confidence_level    confidence_level,
    confidence_score    numeric,
    target_maturity     text,
    source_version      text NOT NULL DEFAULT 'v5',
    is_synthetic        boolean NOT NULL DEFAULT false,  -- excluded from analysis unless trend-flagged (D12)
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- The relationship between a Jira story and the CATALOGUE is materialised here, PER VERSION.
-- Because the catalogue is segmented per version (cat_v5, cat_v7, ...), a story does not hold a
-- foreign key into a single subcap; instead it has one row per target version giving the subcap it
-- maps to IN THAT VERSION. For v5 (the version the stories were mapped to) the link is native
-- (via 'native', similarity 1.0); for v7 and any later version it is produced by the carry-forward
-- script (via 'crosswalk' or 'nearest_neighbour'). carried_to_subcap is a logical reference into
-- cat_<target_version>.subcap, validated by the job at write time (a hard FK is impossible because
-- the target schema name varies by version). FR-4, D13.
CREATE TABLE control.story_subcap_carry (
    carry_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    story_key           text NOT NULL REFERENCES control.story(story_key),
    source_version      text NOT NULL,
    mapped_in_source    text NOT NULL,           -- original id, e.g. P3C1.8.CL2
    base_subcap         text NOT NULL,           -- SV suffix stripped, e.g. P3C1.8
    subvertical         text,
    target_version      text NOT NULL,
    carried_to_subcap   text,                    -- logical ref into cat_<target_version>.subcap; null when unmapped
    similarity          numeric(4,3),
    status              carry_status NOT NULL,
    via                 text NOT NULL,           -- native | crosswalk | nearest_neighbour | none
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (story_key, target_version)
);


-- ============ Evidence, reliability, reasoning, gates, citations ============
CREATE TABLE control.evidence_item (
    evidence_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            evidence_kind NOT NULL,
    title           text,
    url             text,
    source_tier     source_tier NOT NULL,
    published_at    timestamptz,
    body_ref        text,                        -- GCS pointer for the full text
    redacted        boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.ers (                       -- evidence reliability score
    ers_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_id     uuid NOT NULL REFERENCES control.evidence_item(evidence_id),
    score           numeric(4,3) NOT NULL,
    components      jsonb NOT NULL DEFAULT '{}',  -- tier, recency, corroboration, directness
    computed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.reasoning_chain (
    chain_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    operation       text NOT NULL,               -- match | impact_score | suggestion | edge | digest
    subject_ref     text,                        -- e.g. subcap id, story key
    claim_label     claim_label,
    summary         text,
    model           text,
    cost_usd        numeric(10,5),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.reasoning_step (
    step_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id        uuid NOT NULL REFERENCES control.reasoning_chain(chain_id) ON DELETE CASCADE,
    ordinal         integer NOT NULL,
    kind            text NOT NULL,               -- observation | inference | check
    text            text NOT NULL,
    evidence_id     uuid REFERENCES control.evidence_item(evidence_id)
);

-- One row per run of the eight gates G1..G8 (TRD section 8); detail holds the per-gate result.
CREATE TABLE control.validation_gate_run (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    target_ref      text NOT NULL,
    gate_results    jsonb NOT NULL,              -- {"G1":"pass", ..., "G6":"fail"}
    verdict         gate_verdict NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.citation (
    citation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id        uuid NOT NULL REFERENCES control.reasoning_chain(chain_id) ON DELETE CASCADE,
    evidence_id     uuid NOT NULL REFERENCES control.evidence_item(evidence_id),
    quote_span      text,
    verified        boolean NOT NULL DEFAULT false  -- G7 citation verification
);


-- ============ Governance: suggestions, flags, cascade, exports, audit ============
CREATE TABLE control.suggestion (
    suggestion_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target_version  text NOT NULL REFERENCES control.catalogue_version(version_id),
    target_subcap   text,
    kind            text NOT NULL,               -- descriptor_update | new_subcap | offering | ...
    payload         jsonb NOT NULL,
    claim_label     claim_label,
    source_tier     source_tier,
    ers             numeric(4,3),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    status          suggestion_status NOT NULL DEFAULT 'pending',
    reason          text,                        -- required on reject
    created_by      text REFERENCES control.users(uid),
    created_at      timestamptz NOT NULL DEFAULT now(),
    applied_at      timestamptz
);

CREATE TABLE control.change_flag (
    flag_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL,               -- low_confidence | contradicted_evidence | pending_edge | drift
    severity        text NOT NULL,
    target_ref      text NOT NULL,
    detail          jsonb NOT NULL DEFAULT '{}',
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    status          text NOT NULL DEFAULT 'open',
    created_at      timestamptz NOT NULL DEFAULT now(),
    resolved_at     timestamptz
);

CREATE TABLE control.cascade_report (
    report_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    root_subcap     text NOT NULL,
    changes         jsonb NOT NULL,              -- denormalised list of affected rows
    applied         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.export_manifest (
    export_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL,               -- digest | dma_packet | report
    target_ref      text,
    artifact_uri    text NOT NULL,               -- GCS
    hmac_sig        text NOT NULL,               -- signed (D-security)
    signed_at       timestamptz NOT NULL DEFAULT now(),
    created_by      text REFERENCES control.users(uid)
);

-- Append-only audit trail; no UPDATE/DELETE granted to the app role.
CREATE TABLE control.audit_log (
    audit_id        bigserial PRIMARY KEY,
    actor           text REFERENCES control.users(uid),
    action          text NOT NULL,
    target_ref      text,
    at              timestamptz NOT NULL DEFAULT now(),
    meta            jsonb NOT NULL DEFAULT '{}'
);


-- ============ Intelligence & synthesis ============
CREATE TABLE control.news_item (
    news_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_id     uuid REFERENCES control.evidence_item(evidence_id),
    source          text,
    headline        text,
    published_at    timestamptz,
    fs_relevance    numeric(4,3),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE control.news_subcap_impact (
    news_id         uuid NOT NULL REFERENCES control.news_item(news_id),
    version_id      text NOT NULL,
    subcap_id       text NOT NULL,
    mag             magnitude NOT NULL,
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    PRIMARY KEY (news_id, version_id, subcap_id)
);

CREATE TABLE control.vendor (
    vendor_id       text PRIMARY KEY,
    name            text NOT NULL,
    homepage        text,
    category        text
);
CREATE TABLE control.vendor_event (
    event_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_id       text NOT NULL REFERENCES control.vendor(vendor_id),
    event_type      vendor_event_type NOT NULL,
    headline        text,
    occurred_at     timestamptz,
    evidence_id     uuid REFERENCES control.evidence_item(evidence_id)
);
CREATE TABLE control.vendor_subcap_impact (    -- heatmap = frequency x recency, not a static join
    event_id        uuid NOT NULL REFERENCES control.vendor_event(event_id),
    version_id      text NOT NULL,
    subcap_id       text NOT NULL,
    mag             magnitude NOT NULL,
    recency_weight  numeric(4,3),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    PRIMARY KEY (event_id, version_id, subcap_id)
);

CREATE TABLE control.lifecycle_transition (
    transition_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    subcap_id       text NOT NULL,
    from_state      lifecycle_state,
    to_state        lifecycle_state NOT NULL,
    reason          text,
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.trend (
    trend_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label           text NOT NULL,
    status          text NOT NULL DEFAULT 'staged', -- staged | promoted | consumed
    window_start    date,
    window_end      date,
    evidence_count  integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- A subcap flagged emergent here is what permits an otherwise-excluded synthetic story to surface.
CREATE TABLE control.trend_subcap (
    trend_id        uuid NOT NULL REFERENCES control.trend(trend_id),
    version_id      text NOT NULL,
    subcap_id       text NOT NULL,
    emergent        boolean NOT NULL DEFAULT false,
    PRIMARY KEY (trend_id, version_id, subcap_id)
);

-- Lifecycle manager output: delivery-to-offering opportunity (FR-12, D17).
CREATE TABLE control.offering_opportunity (
    opp_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    proposed_name   text NOT NULL,
    rationale       text,
    subcap_ids      jsonb NOT NULL,              -- the uncovered high-delivery subcaps bundled
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    status          suggestion_status NOT NULL DEFAULT 'pending',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.digest (
    digest_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    quarter         text NOT NULL,
    summary         text,
    model           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE control.digest_priority (
    priority_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    digest_id       uuid NOT NULL REFERENCES control.digest(digest_id) ON DELETE CASCADE,
    subvertical     text,
    title           text,
    body            text,
    adversary_verdict text
);

CREATE TABLE control.what_if_result (           -- read-only sandbox
    whatif_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    change          jsonb NOT NULL,
    cascade_preview jsonb NOT NULL,
    created_by      text REFERENCES control.users(uid),
    created_at      timestamptz NOT NULL DEFAULT now()
);


-- ============ Knowledge graph (admin) ============
CREATE TABLE control.kg_node (
    node_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    kind            text NOT NULL,               -- subcap | offering | platform | theme | ...
    ref_id          text NOT NULL,               -- id within the data plane
    label           text,
    UNIQUE (version_id, kind, ref_id)
);
CREATE TABLE control.kg_edge (
    edge_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    from_node       uuid NOT NULL REFERENCES control.kg_node(node_id),
    to_node         uuid NOT NULL REFERENCES control.kg_node(node_id),
    kind            text NOT NULL,
    layer           kg_layer NOT NULL,           -- A_deterministic | B_proposed
    weight          numeric(4,3)
);
-- AI-proposed edges wait here until gated and human-approved; never written live to kg_edge.
CREATE TABLE control.pending_edge (
    pending_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    from_node       uuid NOT NULL REFERENCES control.kg_node(node_id),
    to_node         uuid NOT NULL REFERENCES control.kg_node(node_id),
    kind            text NOT NULL,               -- semantically_similar | shares_feature
    weight          numeric(4,3),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    status          text NOT NULL DEFAULT 'pending', -- pending | approved | rejected | deferred
    created_at      timestamptz NOT NULL DEFAULT now()
);


-- ============ Data plane: per-version catalogue (schema cat_<version>) ============
-- Created by the mapping studio when a version is provisioned. Shown here as the canonical
-- template; the version is encoded by the schema namespace, so these tables carry no version_id.
-- The structure mirrors the workbook sheets and, crucially, the relationships BETWEEN them:
-- 2_Capability_Map is the hub; sheets 12/13/15 are many-to-many matrices; sheet 5 is the
-- subcap x platform x feature join; sheets 4/8/10/11 are entities cross-referenced from many sheets.
-- The version is the schema namespace: v5 and v7 are SEGMENTED into separate schemas that hold the
-- identical table set. The template below is shown for cat_v7; cat_v5 is generated identically.
CREATE SCHEMA IF NOT EXISTS cat_v5;   -- identical table set to cat_v7 (omitted for brevity)
CREATE SCHEMA IF NOT EXISTS cat_v7;

-- ---- hierarchy (sheet 2 spine) ----
CREATE TABLE cat_v7.pillar (
    pillar_id       text PRIMARY KEY,            -- P1..P4
    name            text NOT NULL
);
CREATE TABLE cat_v7.category (
    category_id     text PRIMARY KEY,
    pillar_id       text NOT NULL REFERENCES cat_v7.pillar(pillar_id),
    name            text NOT NULL
);
CREATE TABLE cat_v7.capability (
    capability_id   text PRIMARY KEY,
    category_id     text NOT NULL REFERENCES cat_v7.category(category_id),
    name            text NOT NULL
);
CREATE TABLE cat_v7.subcap (
    subcap_id       text PRIMARY KEY,            -- P1C2.3.1
    capability_id   text NOT NULL REFERENCES cat_v7.capability(capability_id),
    name            text NOT NULL,
    description     text,
    solution_type   text,
    tier            text,
    lifecycle_state lifecycle_state NOT NULL DEFAULT 'stable',
    zennify_status  text,
    completeness    numeric(4,3),
    target_maturity text,
    search          tsvector,                    -- lexical retrieval
    embedding       vector(768)                  -- catalogue-tuned dense retrieval (pgvector)
);

-- ---- shared dimension: vendor (sheets 4, 7, 8, 9, 10 all reference a vendor) ----
CREATE TABLE cat_v7.vendor (
    vendor_id       text PRIMARY KEY,
    name            text NOT NULL,
    homepage        text
);

-- ---- entities cross-referenced from many sheets ----
CREATE TABLE cat_v7.l3_platform (              -- sheet 4
    l3_id           text PRIMARY KEY,
    vendor_id       text REFERENCES cat_v7.vendor(vendor_id),
    name            text NOT NULL,
    category        text,
    description     text,
    reference_url   text
);
CREATE TABLE cat_v7.agent (                    -- sheet 8
    agent_id        text PRIMARY KEY,
    name            text NOT NULL,
    parent_l3_id    text REFERENCES cat_v7.l3_platform(l3_id),  -- 8.Parent_L3
    lob             text,
    workflow        text,
    status          text,
    description     text
);
CREATE TABLE cat_v7.product_component (        -- sheet 7 (product catalogue)
    component_id    text PRIMARY KEY,
    vendor_id       text REFERENCES cat_v7.vendor(vendor_id),
    l3_id           text REFERENCES cat_v7.l3_platform(l3_id),  -- 7.L3_Platform_Area
    agent_id        text REFERENCES cat_v7.agent(agent_id),     -- 7.Agent_ID
    name            text NOT NULL,
    component_type  text,
    lob             text,
    workflow        text,
    status          text
);
CREATE TABLE cat_v7.construct (                -- sheet 9 (platform constructs library)
    construct_id    text PRIMARY KEY,
    vendor_id       text REFERENCES cat_v7.vendor(vendor_id),
    name            text NOT NULL,
    syntax_hint     text,
    docs_url        text
);
CREATE TABLE cat_v7.persona (
    persona_id      text PRIMARY KEY,
    canonical_name  text NOT NULL,
    role_description text,
    family          text
);
CREATE TABLE cat_v7.offering (                 -- sheet 10
    offering_id     text PRIMARY KEY,
    name            text NOT NULL,
    category        text,
    status          text,
    primary_vendor_id text REFERENCES cat_v7.vendor(vendor_id),
    description     text
);
CREATE TABLE cat_v7.data_product (             -- sheet 11
    module_id       text PRIMARY KEY,
    name            text NOT NULL,
    category        text,
    description     text,
    validation_strength text
);
CREATE TABLE cat_v7.theme (                    -- sheet 15 dimension
    theme_id        text PRIMARY KEY,
    name            text NOT NULL
);

-- ---- subcap-owned detail (sheets 5, 6, use cases) ----
CREATE TABLE cat_v7.l4_feature (               -- sheet 5: subcap x L3 x feature (3-way)
    feature_id      text PRIMARY KEY,
    subcap_id       text NOT NULL REFERENCES cat_v7.subcap(subcap_id),
    l3_id           text REFERENCES cat_v7.l3_platform(l3_id),
    name            text NOT NULL,
    feature_type    text,
    customization_level text,
    slug            text
);
CREATE TABLE cat_v7.use_case (
    use_case_id     text PRIMARY KEY,
    subcap_id       text NOT NULL REFERENCES cat_v7.subcap(subcap_id),
    archetype       text,
    name            text NOT NULL,
    description     text
);
CREATE TABLE cat_v7.maturity_descriptor (      -- sheet 6 (M1..M5 per subcap)
    descriptor_id   text PRIMARY KEY,
    subcap_id       text NOT NULL REFERENCES cat_v7.subcap(subcap_id),
    level           text NOT NULL,               -- M1..M5
    descriptor      text,
    features        text
);

-- ---- relationship (link / matrix) tables: the joins between sheets ----
-- subcap <-> persona  (2.Personas)
CREATE TABLE cat_v7.subcap_persona  (subcap_id text REFERENCES cat_v7.subcap(subcap_id), persona_id text REFERENCES cat_v7.persona(persona_id), PRIMARY KEY (subcap_id, persona_id));
-- subcap <-> L3 platform  (2.L3_Platforms_Addressing_SubCap / 4.Linked_Sub_Caps_Top5)
CREATE TABLE cat_v7.subcap_platform (subcap_id text REFERENCES cat_v7.subcap(subcap_id), l3_id text REFERENCES cat_v7.l3_platform(l3_id), PRIMARY KEY (subcap_id, l3_id));
-- subcap <-> agent
CREATE TABLE cat_v7.subcap_agent    (subcap_id text REFERENCES cat_v7.subcap(subcap_id), agent_id text REFERENCES cat_v7.agent(agent_id), PRIMARY KEY (subcap_id, agent_id));
-- L4 feature <-> use case  (5.Use_Case_IDs_Using_Feature)
CREATE TABLE cat_v7.l4_use_case     (feature_id text REFERENCES cat_v7.l4_feature(feature_id), use_case_id text REFERENCES cat_v7.use_case(use_case_id), PRIMARY KEY (feature_id, use_case_id));
-- construct <-> L4 feature  (9.Used_In_L4_Features) and construct <-> subcap (9.Sub_Caps_Top5)
CREATE TABLE cat_v7.construct_feature (construct_id text REFERENCES cat_v7.construct(construct_id), feature_id text REFERENCES cat_v7.l4_feature(feature_id), PRIMARY KEY (construct_id, feature_id));
CREATE TABLE cat_v7.construct_subcap  (construct_id text REFERENCES cat_v7.construct(construct_id), subcap_id  text REFERENCES cat_v7.subcap(subcap_id),  PRIMARY KEY (construct_id, subcap_id));
-- offering relationships  (10.L3_Platforms_Used / 10.Target_Personas)
CREATE TABLE cat_v7.offering_platform (offering_id text REFERENCES cat_v7.offering(offering_id), l3_id text REFERENCES cat_v7.l3_platform(l3_id), PRIMARY KEY (offering_id, l3_id));
CREATE TABLE cat_v7.offering_persona  (offering_id text REFERENCES cat_v7.offering(offering_id), persona_id text REFERENCES cat_v7.persona(persona_id), PRIMARY KEY (offering_id, persona_id));
-- data product <-> offering pairing  (11.Typical_Pairing)
CREATE TABLE cat_v7.data_product_offering (module_id text REFERENCES cat_v7.data_product(module_id), offering_id text REFERENCES cat_v7.offering(offering_id), PRIMARY KEY (module_id, offering_id));

-- offering <-> subcap matrix  (sheet 12): the relationship carries its own attributes
CREATE TABLE cat_v7.offering_subcap (
    offering_id     text REFERENCES cat_v7.offering(offering_id),
    subcap_id       text REFERENCES cat_v7.subcap(subcap_id),
    mapping_rationale text,
    maturity_lift   text,                        -- 'current -> target'
    status          text,
    PRIMARY KEY (offering_id, subcap_id)
);
-- data product <-> subcap matrix  (sheet 13)
CREATE TABLE cat_v7.data_product_subcap (
    module_id       text REFERENCES cat_v7.data_product(module_id),
    subcap_id       text REFERENCES cat_v7.subcap(subcap_id),
    mapping_rationale text,
    maturity_lift   text,
    status          text,
    PRIMARY KEY (module_id, subcap_id)
);
-- theme <-> subcap matrix  (sheet 15)
CREATE TABLE cat_v7.theme_subcap (
    theme_id        text REFERENCES cat_v7.theme(theme_id),
    subcap_id       text REFERENCES cat_v7.subcap(subcap_id),
    mapping_rationale text,
    story_count     integer,
    status          text,
    PRIMARY KEY (theme_id, subcap_id)
);

-- ---- value chain (sheet 21) and subvertical applicability ----
CREATE TABLE cat_v7.value_chain_cluster (vcc_id text PRIMARY KEY, name text NOT NULL);  -- VCC-01..08
CREATE TABLE cat_v7.subcap_vcc (
    subcap_id       text REFERENCES cat_v7.subcap(subcap_id),
    vcc_id          text REFERENCES cat_v7.value_chain_cluster(vcc_id),
    subvertical     text,
    stage           text,
    PRIMARY KEY (subcap_id, vcc_id, subvertical)
);
CREATE TABLE cat_v7.subvertical (sv_code text PRIMARY KEY, name text NOT NULL);  -- BK,CL,CIB,FC,CU,WM,RIA,IC,IB
CREATE TABLE cat_v7.subcap_subvertical (
    subcap_id       text REFERENCES cat_v7.subcap(subcap_id),
    sv_code         text REFERENCES cat_v7.subvertical(sv_code),
    applicability   text,
    PRIMARY KEY (subcap_id, sv_code)
);

-- ---- denormalised rollup (sheet 18 completeness profile) as a view over the relationships ----
CREATE VIEW cat_v7.subcap_completeness AS
SELECT s.subcap_id,
       (SELECT count(*) FROM cat_v7.l4_feature f         WHERE f.subcap_id = s.subcap_id) AS l4_count,
       (SELECT count(*) FROM cat_v7.maturity_descriptor m WHERE m.subcap_id = s.subcap_id) AS maturity_count,
       (SELECT count(*) FROM cat_v7.use_case u           WHERE u.subcap_id = s.subcap_id) AS use_case_count,
       (SELECT count(*) FROM cat_v7.subcap_platform p     WHERE p.subcap_id = s.subcap_id) AS l3_count,
       (SELECT count(*) FROM cat_v7.offering_subcap o     WHERE o.subcap_id = s.subcap_id) AS offering_count,
       (SELECT count(*) FROM cat_v7.data_product_subcap d WHERE d.subcap_id = s.subcap_id) AS data_product_count,
       (SELECT count(*) FROM cat_v7.theme_subcap t        WHERE t.subcap_id = s.subcap_id) AS theme_count
FROM cat_v7.subcap s;
-- Story counts per subcap come from the control plane (control.story_subcap_carry for this version).


-- ============ Indexes: vector, full-text, and hot paths ============
-- Dense retrieval (pgvector, cosine) and lexical retrieval (GIN over tsvector).
CREATE INDEX ix_subcap_embedding ON cat_v7.subcap USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_subcap_search    ON cat_v7.subcap USING gin (search);

-- Catalogue hot paths.
CREATE INDEX ix_subcap_capability ON cat_v7.subcap (capability_id);
CREATE INDEX ix_l4_subcap         ON cat_v7.l4_feature (subcap_id);
-- Relationship (matrix) tables, indexed on the subcap side for cascade + completeness rollups.
CREATE INDEX ix_offering_subcap   ON cat_v7.offering_subcap (subcap_id);
CREATE INDEX ix_dp_subcap         ON cat_v7.data_product_subcap (subcap_id);
CREATE INDEX ix_theme_subcap      ON cat_v7.theme_subcap (subcap_id);
CREATE INDEX ix_subcap_platform   ON cat_v7.subcap_platform (subcap_id);
-- Relationship registry, queried per version by the cascade engine.
CREATE INDEX ix_relation_version  ON control.relation_def (version_id, to_entity);

-- Story corpus filters.
CREATE INDEX ix_story_subcap      ON control.story (sub_cap_id);
CREATE INDEX ix_story_synth       ON control.story (is_synthetic);
CREATE INDEX ix_story_conf        ON control.story (confidence_level);
CREATE INDEX ix_carry_target      ON control.story_subcap_carry (target_version, status);

-- Evidence, reasoning, governance.
CREATE INDEX ix_evidence_kind     ON control.evidence_item (kind, source_tier);
CREATE INDEX ix_reasoning_subject ON control.reasoning_chain (subject_ref);
CREATE INDEX ix_suggestion_status ON control.suggestion (target_version, status);
CREATE INDEX ix_flag_status       ON control.change_flag (status, severity);

-- Impact lookups.
CREATE INDEX ix_news_impact       ON control.news_subcap_impact (version_id, subcap_id);
CREATE INDEX ix_vendor_impact     ON control.vendor_subcap_impact (version_id, subcap_id);


-- ============ Version segmentation + story-to-catalogue bridge (worked example) ============
-- Each catalogue version is its own schema (cat_v5, cat_v7); cross-version facts (this crosswalk
-- and the story carry-forward) live in the control plane. The data-plane template (section 12) is
-- generated once per version, so v5 and v7 hold the identical table set in separate namespaces.
INSERT INTO control.catalogue_version (version_id, label, schema_name, status) VALUES
 ('v5', 'Catalogue v5.0', 'cat_v5', 'provisioned'),
 ('v7', 'Catalogue v7.0', 'cat_v7', 'provisioned')
ON CONFLICT (version_id) DO NOTHING;

-- Subcap crosswalk v5 -> v7 (seed; the real set is read from the v7 _R1_Source_Reference sheet).
INSERT INTO control.version_crosswalk (from_version, from_subcap, to_version, to_subcap, note) VALUES
 ('v5','P3C1.8','v7','P3C2.1','renamed in v7'),
 ('v5','P1C1.1.1','v7','P1C1.1.1','unchanged')
ON CONFLICT (from_version, from_subcap, to_version) DO NOTHING;

-- Canonical Jira stories (two sample rows; the production load is the full ~14,406-row export).
INSERT INTO control.story (story_key, source_system, sub_cap_id, pillar_id, confidence_level, source_version, is_synthetic, summary) VALUES
 ('CL-1042','jira','P3C1.8.CL2','P3','HIGH','v5',false,'Commercial lending onboarding automation'),
 ('BK-2210','jira','P1C1.1.1','P1','HIGH','v5',false,'Retail KYC document intake')
ON CONFLICT (story_key) DO NOTHING;

-- The story-to-catalogue relationship, materialised PER VERSION in story_subcap_carry:
--   v5 = native  (the version the stories were originally mapped to)        -> via 'native'
--   v7 = carried forward by carry_forward_subcap_mappings.py, crosswalk     -> via 'crosswalk'
--        bridge confirmed by the catalogue-tuned embeddings (similarity).
INSERT INTO control.story_subcap_carry
 (story_key, source_version, mapped_in_source, base_subcap, subvertical, target_version, carried_to_subcap, similarity, status, via) VALUES
 ('CL-1042','v5','P3C1.8.CL2','P3C1.8','CL2','v5','P3C1.8',1.000,'confirmed','native'),
 ('CL-1042','v5','P3C1.8.CL2','P3C1.8','CL2','v7','P3C2.1',0.913,'confirmed','crosswalk'),
 ('BK-2210','v5','P1C1.1.1','P1C1.1.1',NULL,'v5','P1C1.1.1',1.000,'confirmed','native'),
 ('BK-2210','v5','P1C1.1.1','P1C1.1.1',NULL,'v7','P1C1.1.1',0.997,'confirmed','crosswalk')
ON CONFLICT (story_key, target_version) DO NOTHING;

-- Convenience: resolve each story to its subcap in a chosen version (active confirmed/native links).
CREATE VIEW control.story_catalogue_link AS
SELECT story_key, target_version AS version_id, carried_to_subcap AS subcap_id, similarity, via, status
FROM control.story_subcap_carry
WHERE status IN ('confirmed','review') AND carried_to_subcap IS NOT NULL;


-- ============ Sheet relationship registry (worked example for v7) ============
-- This is what the schema-mapping studio captures in addition to field mappings: the joins
-- BETWEEN sheets. Provisioning turns these into the foreign keys and link tables above, and the
-- cascade engine reads them to compute what a subcap toggle affects. Seeded here for v7.
INSERT INTO control.catalogue_sheet (version_id, sheet_name, sheet_role, maps_to_entity) VALUES
 ('v7','2_Capability_Map','entity','subcap'),
 ('v7','3_User_Stories_Catalogue','entity','story'),
 ('v7','4_L3_Detailed','entity','l3_platform'),
 ('v7','5_L4_Detailed_Features','entity','l4_feature'),
 ('v7','6_Maturity_Descriptors','entity','maturity_descriptor'),
 ('v7','7_Product_Catalogue','entity','product_component'),
 ('v7','8_Agentforce_Agents_List','entity','agent'),
 ('v7','9_Platform_Constructs_Library','entity','construct'),
 ('v7','10_Productized_Offerings','entity','offering'),
 ('v7','11_Data_Products','entity','data_product'),
 ('v7','12_Offering_SubCap_Matrix','matrix','offering_subcap'),
 ('v7','13_DataProduct_SubCap_Matrix','matrix','data_product_subcap'),
 ('v7','15_Theme_SubCap_Mapping','matrix','theme_subcap'),
 ('v7','18_SubCap_Completeness_Profile','aggregate','subcap_completeness'),
 ('v7','19_Toggle_Cascade_Simulation','control','cascade'),
 ('v7','21_VC_Mapping_PerSubcap','matrix','subcap_vcc'),
 ('v7','_R1_Source_Reference','crosswalk','version_crosswalk')
ON CONFLICT (version_id, sheet_name) DO NOTHING;

-- relation(from_entity, from_field, rel_type, to_entity, to_field, card, via_sheet, is_cascade, cascade_kind)
INSERT INTO control.relation_def
 (version_id, from_entity, from_field, rel_type, to_entity, to_field, card, via_sheet, is_cascade, cascade_kind) VALUES
 ('v7','subcap','subcap_id','belongs_to','capability','capability_id','many_to_one','2_Capability_Map',false,'none'),
 ('v7','subcap','subcap_id','has_persona','persona','persona_id','many_to_many','2_Capability_Map',true,'direct'),
 ('v7','subcap','subcap_id','uses_platform','l3_platform','l3_id','many_to_many','2_Capability_Map',true,'direct'),
 ('v7','subcap','subcap_id','has_usecase','use_case','use_case_id','one_to_many','2_Capability_Map',true,'direct'),
 ('v7','subcap','subcap_id','addresses','l4_feature','feature_id','one_to_many','5_L4_Detailed_Features',true,'direct'),
 ('v7','subcap','subcap_id','addresses','maturity_descriptor','descriptor_id','one_to_many','6_Maturity_Descriptors',true,'direct'),
 ('v7','subcap','subcap_id','delivered_by','story','story_key','many_to_many','3_User_Stories_Catalogue',true,'direct'),
 ('v7','l4_feature','feature_id','uses_platform','l3_platform','l3_id','many_to_one','5_L4_Detailed_Features',false,'none'),
 ('v7','l4_feature','feature_id','has_usecase','use_case','use_case_id','many_to_many','5_L4_Detailed_Features',false,'none'),
 ('v7','offering','offering_id','maps_to_offering','subcap','subcap_id','many_to_many','12_Offering_SubCap_Matrix',true,'direct'),
 ('v7','data_product','module_id','maps_to_offering','subcap','subcap_id','many_to_many','13_DataProduct_SubCap_Matrix',true,'direct'),
 ('v7','theme','theme_id','tagged_theme','subcap','subcap_id','many_to_many','15_Theme_SubCap_Mapping',true,'direct'),
 ('v7','offering','offering_id','uses_platform','l3_platform','l3_id','many_to_many','10_Productized_Offerings',false,'none'),
 ('v7','offering','offering_id','has_persona','persona','persona_id','many_to_many','10_Productized_Offerings',false,'none'),
 ('v7','data_product','module_id','custom','offering','offering_id','many_to_many','11_Data_Products',false,'none'),
 ('v7','agent','agent_id','uses_platform','l3_platform','l3_id','many_to_one','8_Agentforce_Agents_List',false,'none'),
 ('v7','construct','construct_id','addresses','l4_feature','feature_id','many_to_many','9_Platform_Constructs_Library',false,'none'),
 ('v7','product_component','component_id','custom','agent','agent_id','many_to_one','7_Product_Catalogue',false,'none'),
 ('v7','subcap','subcap_id','custom','value_chain_cluster','vcc_id','many_to_many','21_VC_Mapping_PerSubcap',false,'none');

