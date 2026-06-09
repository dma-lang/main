-- Control-plane baseline — GENERATED from docs/specs/schema.sql (control.* only).
-- Canonical for control.*; the cat_<version> data plane is generated per-version by F4.
-- Extensions and enum additions are applied by the migration, not this file.

CREATE SCHEMA IF NOT EXISTS control;

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

CREATE TABLE control.users (
    uid             text PRIMARY KEY,
    email           text NOT NULL UNIQUE,
    is_admin        boolean NOT NULL DEFAULT false,
    preferences     jsonb NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.catalogue_version (
    version_id      text PRIMARY KEY,            
    label           text NOT NULL,
    source_layout   text,                        
    schema_name     text NOT NULL UNIQUE,        
    status          text NOT NULL DEFAULT 'draft', 
    created_by      text REFERENCES control.users(uid),
    created_at      timestamptz NOT NULL DEFAULT now(),
    notes           text
);

CREATE TABLE control.ingest_run (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text REFERENCES control.catalogue_version(version_id),
    source          text NOT NULL,               
    status          text NOT NULL,               
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    stats           jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE control.catalogue_sheet (
    sheet_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    sheet_name      text NOT NULL,               
    sheet_role      sheet_role NOT NULL,
    maps_to_entity  text,                         
    row_count       integer,
    UNIQUE (version_id, sheet_name)
);

CREATE TABLE control.source_field_mapping (
    mapping_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    sheet_id        uuid REFERENCES control.catalogue_sheet(sheet_id),
    source_field    text NOT NULL,
    canonical_entity text,                        
    canonical_field text,                         
    confidence      numeric(4,3),                 
    status          mapping_status NOT NULL,
    is_custom       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version_id, source_field)
);

CREATE TABLE control.relation_def (
    relation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL REFERENCES control.catalogue_version(version_id),
    from_entity     text NOT NULL,               
    from_field      text NOT NULL,               
    rel_type        relation_type NOT NULL,
    to_entity       text NOT NULL,               
    to_field        text NOT NULL,
    card            cardinality NOT NULL,
    via_sheet       text,                         
    is_cascade      boolean NOT NULL DEFAULT false,
    cascade_kind    cascade_kind NOT NULL DEFAULT 'none',
    cascaded_from   uuid REFERENCES control.relation_def(relation_id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.version_crosswalk (
    crosswalk_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_version    text NOT NULL REFERENCES control.catalogue_version(version_id),
    from_subcap     text NOT NULL,               
    to_version      text NOT NULL REFERENCES control.catalogue_version(version_id),
    to_subcap       text,                         
    note            text,
    UNIQUE (from_version, from_subcap, to_version)
);

CREATE TABLE control.story (
    story_key           text PRIMARY KEY,
    source_system       text NOT NULL DEFAULT 'jira',     
    source_export       text,                              
    ingested_at         timestamptz NOT NULL DEFAULT now(),
    project_key         text,
    epic_key            text,
    sub_cap_id          text NOT NULL,           
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
    is_synthetic        boolean NOT NULL DEFAULT false,  
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.story_subcap_carry (
    carry_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    story_key           text NOT NULL REFERENCES control.story(story_key),
    source_version      text NOT NULL,
    mapped_in_source    text NOT NULL,           
    base_subcap         text NOT NULL,           
    subvertical         text,
    target_version      text NOT NULL,
    carried_to_subcap   text,                    
    similarity          numeric(4,3),
    status              carry_status NOT NULL,
    via                 text NOT NULL,           
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (story_key, target_version)
);

CREATE TABLE control.evidence_item (
    evidence_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            evidence_kind NOT NULL,
    title           text,
    url             text,
    source_tier     source_tier NOT NULL,
    published_at    timestamptz,
    body_ref        text,                        
    redacted        boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.ers (                       
    ers_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_id     uuid NOT NULL REFERENCES control.evidence_item(evidence_id),
    score           numeric(4,3) NOT NULL,
    components      jsonb NOT NULL DEFAULT '{}',  
    computed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.reasoning_chain (
    chain_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    operation       text NOT NULL,               
    subject_ref     text,                        
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
    kind            text NOT NULL,               
    text            text NOT NULL,
    evidence_id     uuid REFERENCES control.evidence_item(evidence_id)
);

CREATE TABLE control.validation_gate_run (
    run_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    target_ref      text NOT NULL,
    gate_results    jsonb NOT NULL,              
    verdict         gate_verdict NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.citation (
    citation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id        uuid NOT NULL REFERENCES control.reasoning_chain(chain_id) ON DELETE CASCADE,
    evidence_id     uuid NOT NULL REFERENCES control.evidence_item(evidence_id),
    quote_span      text,
    verified        boolean NOT NULL DEFAULT false  
);

CREATE TABLE control.suggestion (
    suggestion_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target_version  text NOT NULL REFERENCES control.catalogue_version(version_id),
    target_subcap   text,
    kind            text NOT NULL,               
    payload         jsonb NOT NULL,
    claim_label     claim_label,
    source_tier     source_tier,
    ers             numeric(4,3),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    status          suggestion_status NOT NULL DEFAULT 'pending',
    reason          text,                        
    created_by      text REFERENCES control.users(uid),
    created_at      timestamptz NOT NULL DEFAULT now(),
    applied_at      timestamptz
);

CREATE TABLE control.change_flag (
    flag_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL,               
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
    changes         jsonb NOT NULL,              
    applied         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.export_manifest (
    export_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            text NOT NULL,               
    target_ref      text,
    artifact_uri    text NOT NULL,               
    hmac_sig        text NOT NULL,               
    signed_at       timestamptz NOT NULL DEFAULT now(),
    created_by      text REFERENCES control.users(uid)
);

CREATE TABLE control.audit_log (
    audit_id        bigserial PRIMARY KEY,
    actor           text REFERENCES control.users(uid),
    action          text NOT NULL,
    target_ref      text,
    at              timestamptz NOT NULL DEFAULT now(),
    meta            jsonb NOT NULL DEFAULT '{}'
);

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

CREATE TABLE control.vendor_subcap_impact (    
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
    status          text NOT NULL DEFAULT 'staged', 
    window_start    date,
    window_end      date,
    evidence_count  integer NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.trend_subcap (
    trend_id        uuid NOT NULL REFERENCES control.trend(trend_id),
    version_id      text NOT NULL,
    subcap_id       text NOT NULL,
    emergent        boolean NOT NULL DEFAULT false,
    PRIMARY KEY (trend_id, version_id, subcap_id)
);

CREATE TABLE control.offering_opportunity (
    opp_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    proposed_name   text NOT NULL,
    rationale       text,
    subcap_ids      jsonb NOT NULL,              
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

CREATE TABLE control.what_if_result (           
    whatif_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    change          jsonb NOT NULL,
    cascade_preview jsonb NOT NULL,
    created_by      text REFERENCES control.users(uid),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.kg_node (
    node_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    kind            text NOT NULL,               
    ref_id          text NOT NULL,               
    label           text,
    UNIQUE (version_id, kind, ref_id)
);

CREATE TABLE control.kg_edge (
    edge_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    from_node       uuid NOT NULL REFERENCES control.kg_node(node_id),
    to_node         uuid NOT NULL REFERENCES control.kg_node(node_id),
    kind            text NOT NULL,
    layer           kg_layer NOT NULL,           
    weight          numeric(4,3)
);

CREATE TABLE control.pending_edge (
    pending_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      text NOT NULL,
    from_node       uuid NOT NULL REFERENCES control.kg_node(node_id),
    to_node         uuid NOT NULL REFERENCES control.kg_node(node_id),
    kind            text NOT NULL,               
    weight          numeric(4,3),
    chain_id        uuid REFERENCES control.reasoning_chain(chain_id),
    status          text NOT NULL DEFAULT 'pending', 
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_relation_version  ON control.relation_def (version_id, to_entity);

CREATE INDEX ix_story_subcap      ON control.story (sub_cap_id);

CREATE INDEX ix_story_synth       ON control.story (is_synthetic);

CREATE INDEX ix_story_conf        ON control.story (confidence_level);

CREATE INDEX ix_carry_target      ON control.story_subcap_carry (target_version, status);

CREATE INDEX ix_evidence_kind     ON control.evidence_item (kind, source_tier);

CREATE INDEX ix_reasoning_subject ON control.reasoning_chain (subject_ref);

CREATE INDEX ix_suggestion_status ON control.suggestion (target_version, status);

CREATE INDEX ix_flag_status       ON control.change_flag (status, severity);

CREATE INDEX ix_news_impact       ON control.news_subcap_impact (version_id, subcap_id);

CREATE INDEX ix_vendor_impact     ON control.vendor_subcap_impact (version_id, subcap_id);

CREATE VIEW control.story_catalogue_link AS
SELECT story_key, target_version AS version_id, carried_to_subcap AS subcap_id, similarity, via, status
FROM control.story_subcap_carry
WHERE status IN ('confirmed','review') AND carried_to_subcap IS NOT NULL;
