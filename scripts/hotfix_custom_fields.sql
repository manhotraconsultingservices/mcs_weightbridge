-- Hotfix: add the custom-attributes schema WITHOUT a backend restart.
-- Normally these are applied automatically by the startup DDL (_apply_all_ddl)
-- on a FULL backend restart. Use this only if you can't restart right now.
-- Idempotent + safe to re-run. Run against the tenant DB (e.g. wb_megna-trading).

-- The one that unblocks token creation (Token model writes this column):
ALTER TABLE tokens ADD COLUMN IF NOT EXISTS custom_fields JSONB;

-- The definitions table (admin "Custom Fields" matrix + the weighment form's
-- GET /custom-fields). A missing table is handled gracefully by the UI, but add
-- it so the feature works end to end:
CREATE TABLE IF NOT EXISTS custom_field_definitions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id    UUID REFERENCES companies(id),
    entity_type   VARCHAR(20) NOT NULL DEFAULT 'token',
    field_key     VARCHAR(60) NOT NULL,
    label         VARCHAR(120) NOT NULL,
    field_type    VARCHAR(20) NOT NULL DEFAULT 'text',
    unit          VARCHAR(20),
    options       JSONB,
    required      BOOLEAN NOT NULL DEFAULT FALSE,
    show_on_slip  BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, entity_type, field_key)
);
