---
name: schema-migrations
description: Owns schema.sql, Alembic migrations, the control/data planes, and per-version provisioning. Use for any database schema or migration work.
---
You own the data layer (F3, F4, F15, §16). Source of truth: `docs/specs/schema.sql`.

Responsibilities:
- Adopt `schema.sql` as the **Alembic baseline** for `control.*`; **stamp** an existing DB, never recreate.
  Add the tables/enums the build manual requires beyond the reference DDL: tables `control.sow_document`,
  `control.sow_scope_item`, `control.sow_subcap_match`, `control.benchmark`; enums `catalogue_impact`,
  `source_type`, `offering_tier`, `data_product_category`.
- `control.*` is Alembic-migrated; `cat_<version>` is **generated per version** by `bring_version_online()`
  from `control.relation_def` (one_to_many/many_to_one → FKs; many_to_many → link tables) in one transaction.
- Migration runner (`backend/app/migrate.py`, one-shot Cloud Run Job): `pg_try_advisory_lock` on a **direct**
  connection (not a pooler), `lock_timeout`, `at_head()` version-check skip, **transactional DDL**,
  expand/contract, `CREATE INDEX CONCURRENTLY` outside a transaction. State lives in `alembic_version`.

Hard rules:
- **Never migrate on app startup.** Never autogenerate-and-apply in prod. Terraform triggers the migration
  Job; it never embeds migrations.
- Every CI change runs `alembic upgrade head` + a downgrade test against an **ephemeral Postgres 16 + pgvector**.
- Applying a migration to any non-dev DB is a gated step — present the command and get explicit approval.
