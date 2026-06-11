CREATE TABLE {schema}.pillar (
    pillar_id       text PRIMARY KEY,            
    name            text NOT NULL
);

CREATE TABLE {schema}.category (
    category_id     text PRIMARY KEY,
    pillar_id       text NOT NULL REFERENCES {schema}.pillar(pillar_id),
    name            text NOT NULL
);

CREATE TABLE {schema}.capability (
    capability_id   text PRIMARY KEY,
    category_id     text NOT NULL REFERENCES {schema}.category(category_id),
    name            text NOT NULL
);

CREATE TABLE {schema}.subcap (
    subcap_id       text PRIMARY KEY,            
    capability_id   text NOT NULL REFERENCES {schema}.capability(capability_id),
    name            text NOT NULL,
    description     text,
    solution_type   text,
    tier            text,
    lifecycle_state lifecycle_state NOT NULL DEFAULT 'stable',
    zennify_status  text,
    completeness    numeric(4,3),
    target_maturity text,
    story_refs      jsonb NOT NULL DEFAULT '[]',  -- the catalogue's own Jira story references
    search          tsvector,                    
    embedding       vector(768)                  
);

CREATE TABLE {schema}.vendor (
    vendor_id       text PRIMARY KEY,
    name            text NOT NULL,
    homepage        text
);

CREATE TABLE {schema}.l3_platform (              
    l3_id           text PRIMARY KEY,
    vendor_id       text REFERENCES {schema}.vendor(vendor_id),
    name            text NOT NULL,
    category        text,
    description     text,
    reference_url   text
);

CREATE TABLE {schema}.agent (                    
    agent_id        text PRIMARY KEY,
    name            text NOT NULL,
    parent_l3_id    text REFERENCES {schema}.l3_platform(l3_id),  
    lob             text,
    workflow        text,
    status          text,
    description     text
);

CREATE TABLE {schema}.product_component (        
    component_id    text PRIMARY KEY,
    vendor_id       text REFERENCES {schema}.vendor(vendor_id),
    l3_id           text REFERENCES {schema}.l3_platform(l3_id),  
    agent_id        text REFERENCES {schema}.agent(agent_id),     
    name            text NOT NULL,
    component_type  text,
    lob             text,
    workflow        text,
    status          text
);

CREATE TABLE {schema}.construct (                
    construct_id    text PRIMARY KEY,
    vendor_id       text REFERENCES {schema}.vendor(vendor_id),
    name            text NOT NULL,
    syntax_hint     text,
    docs_url        text
);

CREATE TABLE {schema}.persona (
    persona_id      text PRIMARY KEY,
    canonical_name  text NOT NULL,
    role_description text,
    family          text
);

CREATE TABLE {schema}.offering (                 
    offering_id     text PRIMARY KEY,
    name            text NOT NULL,
    category        text,
    status          text,
    primary_vendor_id text REFERENCES {schema}.vendor(vendor_id),
    description     text
);

CREATE TABLE {schema}.data_product (             
    module_id       text PRIMARY KEY,
    name            text NOT NULL,
    category        text,
    description     text,
    validation_strength text
);

CREATE TABLE {schema}.theme (                    
    theme_id        text PRIMARY KEY,
    name            text NOT NULL
);

CREATE TABLE {schema}.l4_feature (               
    feature_id      text PRIMARY KEY,
    subcap_id       text NOT NULL REFERENCES {schema}.subcap(subcap_id),
    l3_id           text REFERENCES {schema}.l3_platform(l3_id),
    name            text NOT NULL,
    feature_type    text,
    customization_level text,
    slug            text
);

CREATE TABLE {schema}.use_case (
    use_case_id     text PRIMARY KEY,
    subcap_id       text NOT NULL REFERENCES {schema}.subcap(subcap_id),
    archetype       text,
    name            text NOT NULL,
    description     text
);

CREATE TABLE {schema}.maturity_descriptor (      
    descriptor_id   text PRIMARY KEY,
    subcap_id       text NOT NULL REFERENCES {schema}.subcap(subcap_id),
    level           text NOT NULL,               
    descriptor      text,
    features        text
);

CREATE TABLE {schema}.subcap_persona  (subcap_id text REFERENCES {schema}.subcap(subcap_id), persona_id text REFERENCES {schema}.persona(persona_id), PRIMARY KEY (subcap_id, persona_id));

CREATE TABLE {schema}.subcap_platform (subcap_id text REFERENCES {schema}.subcap(subcap_id), l3_id text REFERENCES {schema}.l3_platform(l3_id), PRIMARY KEY (subcap_id, l3_id));

CREATE TABLE {schema}.subcap_agent    (subcap_id text REFERENCES {schema}.subcap(subcap_id), agent_id text REFERENCES {schema}.agent(agent_id), PRIMARY KEY (subcap_id, agent_id));

CREATE TABLE {schema}.l4_use_case     (feature_id text REFERENCES {schema}.l4_feature(feature_id), use_case_id text REFERENCES {schema}.use_case(use_case_id), PRIMARY KEY (feature_id, use_case_id));

CREATE TABLE {schema}.construct_feature (construct_id text REFERENCES {schema}.construct(construct_id), feature_id text REFERENCES {schema}.l4_feature(feature_id), PRIMARY KEY (construct_id, feature_id));

CREATE TABLE {schema}.construct_subcap  (construct_id text REFERENCES {schema}.construct(construct_id), subcap_id  text REFERENCES {schema}.subcap(subcap_id),  PRIMARY KEY (construct_id, subcap_id));

CREATE TABLE {schema}.offering_platform (offering_id text REFERENCES {schema}.offering(offering_id), l3_id text REFERENCES {schema}.l3_platform(l3_id), PRIMARY KEY (offering_id, l3_id));

CREATE TABLE {schema}.offering_persona  (offering_id text REFERENCES {schema}.offering(offering_id), persona_id text REFERENCES {schema}.persona(persona_id), PRIMARY KEY (offering_id, persona_id));

CREATE TABLE {schema}.data_product_offering (module_id text REFERENCES {schema}.data_product(module_id), offering_id text REFERENCES {schema}.offering(offering_id), PRIMARY KEY (module_id, offering_id));

CREATE TABLE {schema}.offering_subcap (
    offering_id     text REFERENCES {schema}.offering(offering_id),
    subcap_id       text REFERENCES {schema}.subcap(subcap_id),
    mapping_rationale text,
    maturity_lift   text,                        
    status          text,
    PRIMARY KEY (offering_id, subcap_id)
);

CREATE TABLE {schema}.data_product_subcap (
    module_id       text REFERENCES {schema}.data_product(module_id),
    subcap_id       text REFERENCES {schema}.subcap(subcap_id),
    mapping_rationale text,
    maturity_lift   text,
    status          text,
    PRIMARY KEY (module_id, subcap_id)
);

CREATE TABLE {schema}.theme_subcap (
    theme_id        text REFERENCES {schema}.theme(theme_id),
    subcap_id       text REFERENCES {schema}.subcap(subcap_id),
    mapping_rationale text,
    story_count     integer,
    status          text,
    PRIMARY KEY (theme_id, subcap_id)
);

CREATE TABLE {schema}.value_chain_cluster (vcc_id text PRIMARY KEY, name text NOT NULL);

CREATE TABLE {schema}.subcap_vcc (
    subcap_id       text REFERENCES {schema}.subcap(subcap_id),
    vcc_id          text REFERENCES {schema}.value_chain_cluster(vcc_id),
    subvertical     text,
    stage           text,
    stage_ord       int,                          -- chain position (first-seen order per subvertical)
    PRIMARY KEY (subcap_id, vcc_id, subvertical)
);

CREATE TABLE {schema}.subvertical (sv_code text PRIMARY KEY, name text NOT NULL);

CREATE TABLE {schema}.subcap_subvertical (
    subcap_id       text REFERENCES {schema}.subcap(subcap_id),
    sv_code         text REFERENCES {schema}.subvertical(sv_code),
    applicability   text,
    PRIMARY KEY (subcap_id, sv_code)
);

CREATE VIEW {schema}.subcap_completeness AS
SELECT s.subcap_id,
       (SELECT count(*) FROM {schema}.l4_feature f         WHERE f.subcap_id = s.subcap_id) AS l4_count,
       (SELECT count(*) FROM {schema}.maturity_descriptor m WHERE m.subcap_id = s.subcap_id) AS maturity_count,
       (SELECT count(*) FROM {schema}.use_case u           WHERE u.subcap_id = s.subcap_id) AS use_case_count,
       (SELECT count(*) FROM {schema}.subcap_platform p     WHERE p.subcap_id = s.subcap_id) AS l3_count,
       (SELECT count(*) FROM {schema}.offering_subcap o     WHERE o.subcap_id = s.subcap_id) AS offering_count,
       (SELECT count(*) FROM {schema}.data_product_subcap d WHERE d.subcap_id = s.subcap_id) AS data_product_count,
       (SELECT count(*) FROM {schema}.theme_subcap t        WHERE t.subcap_id = s.subcap_id) AS theme_count
FROM {schema}.subcap s;

CREATE INDEX ix_subcap_embedding ON {schema}.subcap USING hnsw (embedding vector_cosine_ops);

CREATE INDEX ix_subcap_search    ON {schema}.subcap USING gin (search);

CREATE INDEX ix_subcap_capability ON {schema}.subcap (capability_id);

CREATE INDEX ix_l4_subcap         ON {schema}.l4_feature (subcap_id);

CREATE INDEX ix_offering_subcap   ON {schema}.offering_subcap (subcap_id);

CREATE INDEX ix_dp_subcap         ON {schema}.data_product_subcap (subcap_id);

CREATE INDEX ix_theme_subcap      ON {schema}.theme_subcap (subcap_id);

CREATE INDEX ix_subcap_platform   ON {schema}.subcap_platform (subcap_id);
