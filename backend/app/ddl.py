"""Runtime DDL statements — shared between main.py startup and tenant creation.

Extracted into a standalone module so multitenancy/router.py can import
the same DDL lists without circular-importing main.py.
"""


def get_runtime_ddl() -> list[str]:
    """Return the list of CREATE TABLE / ALTER TABLE statements."""
    return [
        # USB keys (registered USB key UUIDs + HMAC secrets)
        """
        CREATE TABLE IF NOT EXISTS usb_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_uuid VARCHAR(200) NOT NULL UNIQUE,
            hmac_secret VARCHAR(200),
            label VARCHAR(200) NOT NULL DEFAULT 'Primary Key',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # USB recovery sessions (admin-created time-limited PINs)
        """
        CREATE TABLE IF NOT EXISTS usb_recovery_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pin_hash VARCHAR(500) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_by UUID REFERENCES users(id),
            reason TEXT DEFAULT '',
            used BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # USB client sessions (per-user, IP-bound)
        """
        CREATE TABLE IF NOT EXISTS usb_client_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            key_uuid VARCHAR(200) NOT NULL,
            created_by UUID REFERENCES users(id),
            expires_at TIMESTAMPTZ NOT NULL,
            ip_address VARCHAR(45),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Add ip_address column if table already existed without it
        "ALTER TABLE usb_client_sessions ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45)",
        # USB nonces (single-use challenge tokens for HMAC auth)
        """
        CREATE TABLE IF NOT EXISTS usb_nonces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            nonce VARCHAR(200) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # USB lockouts (rate limiting per scope)
        """
        CREATE TABLE IF NOT EXISTS usb_lockouts (
            scope VARCHAR(200) PRIMARY KEY,
            fail_count INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ,
            last_attempt TIMESTAMPTZ
        )
        """,
        # USB auth log (audit trail for all USB auth events)
        """
        CREATE TABLE IF NOT EXISTS usb_auth_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            event_type VARCHAR(50) NOT NULL,
            method VARCHAR(30),
            success BOOLEAN NOT NULL DEFAULT FALSE,
            ip_address VARCHAR(45),
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Add used column to recovery sessions if it already existed without it
        "ALTER TABLE usb_recovery_sessions ADD COLUMN IF NOT EXISTS used BOOLEAN NOT NULL DEFAULT FALSE",
        # Notification config
        """
        CREATE TABLE IF NOT EXISTS notification_config (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            channel VARCHAR(20) NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            smtp_host VARCHAR(200),
            smtp_port INTEGER,
            smtp_user VARCHAR(200),
            smtp_password VARCHAR(500),
            from_email VARCHAR(200),
            from_name VARCHAR(200),
            use_tls BOOLEAN NOT NULL DEFAULT TRUE,
            sms_api_key VARCHAR(500),
            sms_sender_id VARCHAR(20),
            sms_route VARCHAR(10) DEFAULT '4',
            wa_api_url VARCHAR(500),
            wa_api_key VARCHAR(500),
            wa_phone_number_id VARCHAR(50),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Notification templates
        """
        CREATE TABLE IF NOT EXISTS notification_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            event_type VARCHAR(50) NOT NULL,
            channel VARCHAR(20) NOT NULL,
            name VARCHAR(200) NOT NULL,
            subject VARCHAR(500),
            body TEXT NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Notification log
        """
        CREATE TABLE IF NOT EXISTS notification_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            channel VARCHAR(20) NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            entity_type VARCHAR(50),
            entity_id VARCHAR(50),
            recipient VARCHAR(300) NOT NULL,
            subject VARCHAR(500),
            body_preview VARCHAR(500),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            error_message TEXT,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Audit log (ensure exists; model uses audit_log table name)
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            user_id UUID REFERENCES users(id),
            action VARCHAR(20) NOT NULL,
            entity_type VARCHAR(50) NOT NULL,
            entity_id VARCHAR(50),
            details TEXT,
            ip_address VARCHAR(45),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Supplementary entries (private non-GST invoices, AES-256-GCM encrypted)
        """
        CREATE TABLE IF NOT EXISTS supplementary_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            invoice_no VARCHAR(50) NOT NULL,
            invoice_date DATE NOT NULL,
            customer_name VARCHAR(200),
            vehicle_no VARCHAR(50),
            net_weight NUMERIC(12,2),
            rate NUMERIC(12,2),
            amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            notes TEXT,
            customer_name_enc TEXT,
            vehicle_no_enc TEXT,
            net_weight_enc TEXT,
            rate_enc TEXT,
            amount_enc TEXT,
            notes_enc TEXT,
            payment_mode TEXT,
            integrity_hash VARCHAR(200),
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Gap-free supplement sequence (replaces COUNT(*)+1 approach)
        "CREATE SEQUENCE IF NOT EXISTS supplement_seq START 1",
        # New columns on tokens table (nullable token_no + is_supplement flag)
        "ALTER TABLE tokens ALTER COLUMN token_no DROP NOT NULL",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS is_supplement BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS gate_pass VARCHAR(100)",
        # invoice_no now assigned at finalise — make nullable
        "ALTER TABLE invoices ALTER COLUMN invoice_no DROP NOT NULL",
        # New token-context columns on supplementary_entries for cross-reference
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS token_id UUID REFERENCES tokens(id)",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS token_no_enc TEXT",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS token_date_enc TEXT",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS gross_weight_enc TEXT",
        "ALTER TABLE supplementary_entries ADD COLUMN IF NOT EXISTS tare_weight_enc TEXT",
        # Generic key-value app settings (e.g. urgency thresholds)
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Compliance items: insurance, certifications, licenses, permits
        """
        CREATE TABLE IF NOT EXISTS compliance_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            item_type VARCHAR(50) NOT NULL,
            name VARCHAR(200) NOT NULL,
            policy_holder VARCHAR(200),
            issuer VARCHAR(200),
            reference_no VARCHAR(100),
            issue_date DATE,
            expiry_date DATE,
            file_path TEXT,
            notes TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Camera snapshots: one row per camera per token
        """
        CREATE TABLE IF NOT EXISTS token_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            token_id UUID NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
            camera_id VARCHAR(10) NOT NULL,
            camera_label VARCHAR(100),
            file_path TEXT,
            capture_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            captured_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (token_id, camera_id)
        )
        """,
        # ── Inventory Management ──────────────────────────────────────────────
        # Master list of raw material items
        """
        CREATE TABLE IF NOT EXISTS inventory_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            name VARCHAR(200) NOT NULL,
            category VARCHAR(50) NOT NULL,
            unit VARCHAR(30) NOT NULL,
            current_stock NUMERIC(14,3) NOT NULL DEFAULT 0,
            min_stock_level NUMERIC(14,3) NOT NULL DEFAULT 0,
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Immutable audit log of every stock movement
        """
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            transaction_type VARCHAR(20) NOT NULL,
            quantity NUMERIC(14,3) NOT NULL,
            stock_before NUMERIC(14,3) NOT NULL,
            stock_after NUMERIC(14,3) NOT NULL,
            reference_id UUID,
            reference_no VARCHAR(50),
            notes TEXT,
            created_by UUID REFERENCES users(id),
            created_by_name VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Purchase Order header
        """
        CREATE TABLE IF NOT EXISTS inventory_purchase_orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            po_no VARCHAR(30) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending_approval',
            supplier_name VARCHAR(200),
            expected_date DATE,
            notes TEXT,
            requested_by UUID REFERENCES users(id),
            requested_by_name VARCHAR(200) NOT NULL,
            approved_by UUID REFERENCES users(id),
            approved_by_name VARCHAR(200),
            approved_at TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Purchase Order line items
        """
        CREATE TABLE IF NOT EXISTS inventory_po_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            po_id UUID NOT NULL REFERENCES inventory_purchase_orders(id) ON DELETE CASCADE,
            item_id UUID NOT NULL REFERENCES inventory_items(id),
            item_name VARCHAR(200) NOT NULL,
            unit VARCHAR(30) NOT NULL,
            quantity_ordered NUMERIC(14,3) NOT NULL,
            quantity_received NUMERIC(14,3) NOT NULL DEFAULT 0,
            unit_price NUMERIC(14,2)
        )
        """,
        # Login lockouts — brute force protection per IP
        """
        CREATE TABLE IF NOT EXISTS login_lockouts (
            scope          VARCHAR(100) PRIMARY KEY,
            fail_count     INTEGER NOT NULL DEFAULT 0,
            locked_until   TIMESTAMPTZ,
            last_attempt   TIMESTAMPTZ
        )
        """,
        # Login audit log — all login events (success + failure)
        """
        CREATE TABLE IF NOT EXISTS login_audit (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username       VARCHAR(200) NOT NULL,
            user_id        UUID REFERENCES users(id),
            ip_address     VARCHAR(45),
            success        BOOLEAN NOT NULL DEFAULT FALSE,
            detail         TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Owner-managed custom attributes (per-tenant). Definitions live here;
        # values live in a JSONB column on the target entity (e.g. tokens.custom_fields).
        """
        CREATE TABLE IF NOT EXISTS custom_field_definitions (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            entity_type   VARCHAR(20) NOT NULL DEFAULT 'token',   -- token | product | party
            field_key     VARCHAR(60) NOT NULL,
            label         VARCHAR(120) NOT NULL,
            field_type    VARCHAR(20) NOT NULL DEFAULT 'text',    -- text|number|select|date|boolean
            unit          VARCHAR(20),
            options       JSONB,                                   -- choices for field_type='select'
            required      BOOLEAN NOT NULL DEFAULT FALSE,
            show_on_slip  BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (company_id, entity_type, field_key)
        )
        """,
        # Tally SaaS relay queue — in cloud/relay mode the backend builds the
        # voucher XML and enqueues it here; a LAN-side Tally Connector claims
        # jobs, pushes to the local Tally gateway, and reports the result back
        # (which flips the source row's tally_synced). Direct/on-prem mode never
        # touches this table.
        """
        CREATE TABLE IF NOT EXISTS tally_sync_jobs (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id       UUID REFERENCES companies(id),
            entity_type      VARCHAR(20) NOT NULL,          -- invoice|party|sales_order|purchase_order
            entity_id        UUID NOT NULL,
            idempotency_key  VARCHAR(80) NOT NULL,          -- "<entity_type>:<entity_id>"
            priority         INTEGER NOT NULL DEFAULT 100,  -- party=10, order=50, invoice=100 (masters first)
            company_name     VARCHAR(200),                  -- target Tally company
            xml              TEXT NOT NULL,
            status           VARCHAR(12) NOT NULL DEFAULT 'pending',  -- pending|in_progress|done|failed|dead
            attempts         INTEGER NOT NULL DEFAULT 0,
            max_attempts     INTEGER NOT NULL DEFAULT 6,
            next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error       TEXT,
            tally_response   TEXT,
            claim_token      VARCHAR(64),
            claimed_until    TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            picked_at        TIMESTAMPTZ,
            completed_at     TIMESTAMPTZ,
            UNIQUE (company_id, idempotency_key)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tally_jobs_claim ON tally_sync_jobs (status, priority, next_attempt_at, created_at)",
        # Agents (brokers/dalals) master + commission payouts
        """
        CREATE TABLE IF NOT EXISTS agents (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id        UUID REFERENCES companies(id),
            name              VARCHAR(200) NOT NULL,
            phone             VARCHAR(15),
            gstin             VARCHAR(15),
            pan               VARCHAR(10),
            address           VARCHAR(500),
            commission_type   VARCHAR(20) NOT NULL DEFAULT 'pct_of_taxable',
            commission_rate   NUMERIC(12,3) NOT NULL DEFAULT 0,
            notes             VARCHAR(500),
            is_active         BOOLEAN NOT NULL DEFAULT TRUE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_agents_company ON agents (company_id, is_active)",
        """
        CREATE TABLE IF NOT EXISTS agent_commission_payments (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            agent_id      UUID REFERENCES agents(id),
            amount        NUMERIC(14,2) NOT NULL,
            paid_on       DATE NOT NULL,
            payment_mode  VARCHAR(20),
            reference_no  VARCHAR(50),
            notes         VARCHAR(500),
            created_by    UUID REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_agent_payments ON agent_commission_payments (company_id, agent_id)",
        # Per-unit default rates for a product (₹/MT, ₹/CFT, ₹/CBM, ₹/Brass…)
        """
        CREATE TABLE IF NOT EXISTS product_unit_rates (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id  UUID REFERENCES companies(id),
            product_id  UUID REFERENCES products(id),
            unit        VARCHAR(20) NOT NULL,
            rate        NUMERIC(12,2) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_product_unit_rate UNIQUE (product_id, unit)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_product_unit_rates ON product_unit_rates (company_id, product_id)",
    ]


def get_column_migrations() -> list[str]:
    """Return column migration ALTER TABLE statements."""
    return [
        # Direct-expense vouchers: a category tags a voucher as an overhead expense
        # (electricity/rent/…) instead of a supplier payment; such a voucher needs
        # no party, so party_id becomes nullable. Additive → existing vouchers stay
        # supplier payments (category NULL, party set).
        "ALTER TABLE payment_vouchers ADD COLUMN IF NOT EXISTS expense_category VARCHAR(50)",
        "ALTER TABLE payment_vouchers ALTER COLUMN party_id DROP NOT NULL",
        # Operator who physically collected the cash on a receipt (Operator Cash EOD).
        # Nullable → existing rows fall back to created_by. Additive.
        "ALTER TABLE payment_receipts ADD COLUMN IF NOT EXISTS collected_by UUID REFERENCES users(id)",
        # Agents (brokers/dalals) — nullable FK on tokens/invoices/gate_passes
        # + commission snapshot on invoices. Additive → existing rows stay NULL.
        # (The `agents` table is created in get_runtime_ddl, which runs first.)
        "ALTER TABLE tokens      ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES agents(id)",
        "ALTER TABLE invoices    ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES agents(id)",
        "ALTER TABLE invoices    ADD COLUMN IF NOT EXISTS commission_amount NUMERIC(14,2)",
        "ALTER TABLE gate_passes ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES agents(id)",
        # Per-unit rates: unit on customer rates + operator-chosen billing unit on tokens.
        "ALTER TABLE party_rates ADD COLUMN IF NOT EXISTS unit VARCHAR(20)",
        "ALTER TABLE tokens      ADD COLUMN IF NOT EXISTS billing_unit VARCHAR(20)",
        # Fleet fuel & mileage — benchmark km/l + tank capacity on the vehicle master.
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS benchmark_mileage_kmpl NUMERIC(6,2)",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS tank_capacity_litres NUMERIC(8,2)",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS current_odometer_km NUMERIC(12,1)",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS rent_rate_per_km_per_mt NUMERIC(12,4)",
        "ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS rent_rate_per_km_per_cum NUMERIC(12,4)",
        # Custom-attribute values (owner-defined fields) per weighment.
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS custom_fields JSONB",
        "ALTER TABLE compliance_items ADD COLUMN IF NOT EXISTS policy_holder VARCHAR(200)",
        "ALTER TABLE compliance_items ALTER COLUMN item_type TYPE VARCHAR(50)",
        # Tally ledger name mappings (Phase 1)
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_sales VARCHAR(100) NOT NULL DEFAULT 'Sales'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_purchase VARCHAR(100) NOT NULL DEFAULT 'Purchase'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_cgst VARCHAR(100) NOT NULL DEFAULT 'CGST'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_sgst VARCHAR(100) NOT NULL DEFAULT 'SGST'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_igst VARCHAR(100) NOT NULL DEFAULT 'IGST'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_freight VARCHAR(100) NOT NULL DEFAULT 'Freight Outward'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_discount VARCHAR(100) NOT NULL DEFAULT 'Trade Discount'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_tcs VARCHAR(100) NOT NULL DEFAULT 'TCS Payable'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS ledger_roundoff VARCHAR(100) NOT NULL DEFAULT 'Round Off'",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS accounting_only BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS sync_non_gst BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_vehicle BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_token BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_weight BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS sync_invoice_prefix VARCHAR(200)",
        # Sync transport mode (NULL = derive from MULTI_TENANT: cloud=relay, on-prem=direct).
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS mode VARCHAR(10)",
        # Tally Phase 2 — per-party ledger name
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS tally_ledger_name VARCHAR(200)",
        # Inventory — auto-reorder columns (added after initial release)
        "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS reorder_quantity NUMERIC(14,3) NOT NULL DEFAULT 0",
        "ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS auto_po_enabled BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS is_auto_generated BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS used_by_name VARCHAR(200)",
        "ALTER TABLE inventory_transactions ADD COLUMN IF NOT EXISTS used_on DATE",
        # Tally sync tracking for parties, quotations, and inventory purchase orders
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        # Default payment mode — drives whether new invoices for this party are
        # GST or non-GST (Bill of Supply). 'online' = GST invoice + Tally sync;
        # 'cash' = non-GST + blocked from Tally. Default 'cash' (most stone-
        # crusher customers pay in cash; online/GST customers are flagged
        # explicitly).
        "ALTER TABLE parties ADD COLUMN IF NOT EXISTS default_payment_mode VARCHAR(20) NOT NULL DEFAULT 'cash'",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        # eInvoice (GST IRN) columns on invoices
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS vehicle_rent NUMERIC(14,2) DEFAULT 0",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS royalty_amount NUMERIC(14,2) DEFAULT 0",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS draft_snapshot JSONB",
        # Per-item royalty (₹ per MT or per CUM) on invoice lines
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS royalty_unit VARCHAR(8)",
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS royalty_rate NUMERIC(14,2)",
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS royalty_amount NUMERIC(14,2) DEFAULT 0",
        # Per-item vehicle fare (₹/km/MT or ₹/km/CUM × total km × qty) on invoice lines
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS fare_unit VARCHAR(8)",
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS fare_rate NUMERIC(14,2)",
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS fare_km NUMERIC(12,2)",
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS fare_amount NUMERIC(14,2) DEFAULT 0",
        "ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS fare_trips JSONB",
        # Petrol pump name for outside-pump fuel fills (drives the fuel-credit PO)
        "ALTER TABLE vehicle_fuel_entries ADD COLUMN IF NOT EXISTS station_name VARCHAR(120)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn VARCHAR(64)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn_ack_no VARCHAR(30)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn_ack_date TIMESTAMPTZ",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn_qr_code TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn_signed_invoice TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_status VARCHAR(20) NOT NULL DEFAULT 'none'",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_error TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn_cancelled_at TIMESTAMPTZ",
        # Invoice revisions — versioning / amendment system
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS revision_no INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS original_invoice_id UUID REFERENCES invoices(id)",
        """
        CREATE TABLE IF NOT EXISTS invoice_revisions (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            original_invoice_id UUID NOT NULL,
            from_revision_no    INTEGER NOT NULL,
            to_revision_no      INTEGER NOT NULL,
            from_invoice_id     UUID NOT NULL,
            to_invoice_id       UUID NOT NULL,
            snapshot            JSONB NOT NULL,
            diff                JSONB,
            change_summary      TEXT,
            revised_by          UUID REFERENCES users(id),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finalized_at        TIMESTAMPTZ
        )
        """,
        # Camera: weight_stage column for dual-stage capture (1st + 2nd weight)
        "ALTER TABLE token_snapshots ADD COLUMN IF NOT EXISTS weight_stage VARCHAR(20) NOT NULL DEFAULT 'second_weight'",
        # Drop old unique constraint and create new one with weight_stage
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'token_snapshots_token_id_camera_id_key'
            ) THEN
                ALTER TABLE token_snapshots DROP CONSTRAINT token_snapshots_token_id_camera_id_key;
            END IF;
        END $$
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'token_snapshots_token_camera_stage_key'
            ) THEN
                ALTER TABLE token_snapshots ADD CONSTRAINT token_snapshots_token_camera_stage_key
                    UNIQUE (token_id, camera_id, weight_stage);
            END IF;
        END $$
        """,
        # Vehicle type on tokens (operator-selectable at token creation)
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS vehicle_type VARCHAR(50)",
        # Notification engine — Telegram support + named recipients
        "ALTER TABLE notification_config ADD COLUMN IF NOT EXISTS tg_bot_token VARCHAR(500)",
        """
        CREATE TABLE IF NOT EXISTS notification_recipients (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            name VARCHAR(200) NOT NULL,
            channel VARCHAR(20) NOT NULL,
            contact VARCHAR(300) NOT NULL,
            event_types TEXT NOT NULL DEFAULT '["*"]',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Bulk density on products — originally t/m³, migrated to kg/CFT (see
        # units_migrated_to_cft_v1 marker below). Enables volume → weight at token.
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS bulk_density NUMERIC(6,3)",
        # Raw material flag — marks products that are inputs to production (e.g.,
        # raw boulder). When a production cycle is finalised, the raw_material_id
        # gets a negative stock movement = input weight consumed.
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_raw_material BOOLEAN NOT NULL DEFAULT FALSE",
        # NOTE: raw_material_id is added AFTER the production_cycles CREATE TABLE
        # below (see the ALTER following that CREATE). Adding it here — before the
        # table exists on a fresh DB — was the cause of a cascading DDL failure.
        # Volume-based weighment on tokens — canonical unit is m³ (cubic metres).
        # Old tenants migrated from volume_cft in the units_migrated_to_m3_v2 block.
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS weight_method VARCHAR(20) NOT NULL DEFAULT 'weighbridge'",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS volume_m3 NUMERIC(10,5)",
        # ── ONE-SHOT unit migration: m³ → CFT  +  t/m³ → kg/CFT ───────────────
        # Guarded by an app_settings marker so it runs EXACTLY ONCE per DB.
        # Without the marker the UPDATE statements would multiply values on
        # every app startup, silently corrupting data. Conversion factors:
        #   1 m³  = 35.3147 ft³ (CFT)
        #   t/m³  ×  1000 / 35.3147  =  kg/CFT   (≈ × 28.3168)
        # Sanity:  10 m³ × 1.5 t/m³ × 1000 = 15,000 kg
        #         353.147 CFT × 42.475 kg/CFT  = 15,000 kg ✓
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app_settings WHERE key = 'units_migrated_to_cft_v1'
            ) THEN
                -- Step 1: tokens.volume_m3 → tokens.volume_cft  (if old col exists)
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='tokens' AND column_name='volume_m3'
                ) THEN
                    UPDATE tokens
                    SET volume_cft = ROUND((volume_m3 * 35.3147)::NUMERIC, 3)
                    WHERE volume_m3 IS NOT NULL AND volume_cft IS NULL;
                    ALTER TABLE tokens DROP COLUMN volume_m3;
                END IF;

                -- Step 2: products.bulk_density  t/m³ → kg/CFT  (× 28.3168)
                -- NULL rows untouched. Existing kg/CFT rows would only exist in
                -- a partially-migrated DB; the marker prevents that path.
                UPDATE products
                SET bulk_density = ROUND((bulk_density * 28.3168)::NUMERIC, 3)
                WHERE bulk_density IS NOT NULL;

                -- Mark complete so subsequent startups skip this block.
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ('units_migrated_to_cft_v1', 'true', NOW())
                ON CONFLICT (key) DO NOTHING;
            END IF;
        END $$
        """,
        # Tyre count — used by the operator kiosk + printed slips. Stored
        # for ALL tokens (volume + weighbridge) so the slip shows truck class.
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS tyre_count SMALLINT",
        # ── ONE-SHOT remediation: ensure canonical CFT state ─────────────────
        # The units_migrated_to_m3_v2 block (now removed) was an erroneous
        # reversal that dropped volume_cft and re-created volume_m3, contradicting
        # the app's declared canonical unit (CFT).  This block repairs any DB
        # that ran that migration, and is a no-op on DBs that never ran it.
        #
        # Detection logic:
        #   • volume_m3 exists AND volume_cft absent → m3_v2 ran; reverse it.
        #   • volume_cft already present (or both absent) → no-op; just mark.
        #
        # Conversion: m³ × 35.3147 = CFT,  kg/m³ ÷ 35.3147 = kg/CFT
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app_settings WHERE key = 'units_migrated_to_cft_v2'
            ) THEN
                -- Only act when the DB is in the post-m3_v2 broken state:
                -- volume_m3 present and volume_cft absent.
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='tokens' AND column_name='volume_m3'
                ) AND NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='tokens' AND column_name='volume_cft'
                ) THEN
                    -- Step 1: add volume_cft back
                    ALTER TABLE tokens ADD COLUMN volume_cft NUMERIC(10,3);
                    -- Step 2: convert volume_m3 → volume_cft
                    UPDATE tokens
                    SET volume_cft = ROUND((volume_m3 * 35.3147)::NUMERIC, 3)
                    WHERE volume_m3 IS NOT NULL;
                    -- Step 3: drop volume_m3
                    ALTER TABLE tokens DROP COLUMN volume_m3;
                    -- Step 4: revert bulk_density: kg/m³ → kg/CFT (÷ 35.3147)
                    UPDATE products
                    SET bulk_density = ROUND((bulk_density / 35.3147)::NUMERIC, 3)
                    WHERE bulk_density IS NOT NULL;
                END IF;

                -- Mark complete regardless (prevents re-running on next startup)
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ('units_migrated_to_cft_v2', 'true', NOW())
                ON CONFLICT (key) DO NOTHING;
            END IF;
        END $$
        """,
        # ── ONE-SHOT migration: CFT+kg/CFT → m³+MT/m³ ────────────────────────
        # Canonical units changed to m³ (volume) and MT/m³ (density).
        # Conversion: m³ = CFT ÷ 35.3147 ; MT/m³ = kg/CFT × 35.3147 ÷ 1000
        # Guard: bulk_density > 10 identifies kg/CFT values (MT/m³ values are 1–3).
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM app_settings WHERE key = 'units_migrated_to_m3_v2'
            ) THEN
                -- Step 1: rename volume_cft → volume_m3 and convert (if old col exists)
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='tokens' AND column_name='volume_cft'
                ) THEN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='tokens' AND column_name='volume_m3'
                    ) THEN
                        ALTER TABLE tokens ADD COLUMN volume_m3 NUMERIC(10,5);
                    END IF;
                    UPDATE tokens
                    SET volume_m3 = ROUND((volume_cft / 35.3147)::NUMERIC, 5)
                    WHERE volume_cft IS NOT NULL;
                    ALTER TABLE tokens DROP COLUMN volume_cft;
                END IF;

                -- Step 2: convert bulk_density from kg/CFT to MT/m³ (only if values look like kg/CFT)
                IF EXISTS (SELECT 1 FROM products WHERE bulk_density IS NOT NULL AND bulk_density > 10) THEN
                    UPDATE products
                    SET bulk_density = ROUND((bulk_density * 35.3147 / 1000.0)::NUMERIC, 4)
                    WHERE bulk_density IS NOT NULL;
                END IF;

                INSERT INTO app_settings (key, value, updated_at)
                VALUES ('units_migrated_to_m3_v2', 'true', NOW())
                ON CONFLICT (key) DO NOTHING;
            END IF;
        END $$
        """,
        # ── Finished-goods inventory on products ──────────────────────────────
        # One stock row per product. Auto-decremented on sale finalise,
        # auto-incremented on purchase finalise + production cycle output.
        """
        CREATE TABLE IF NOT EXISTS product_stock (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            product_id UUID NOT NULL REFERENCES products(id) UNIQUE,
            current_stock NUMERIC(14,3) NOT NULL DEFAULT 0,
            min_stock_level NUMERIC(14,3) NOT NULL DEFAULT 0,
            last_alerted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # ── Fleet fuel & mileage (diesel-leakage detection) ──────────────────
        # One row per diesel fill (plant tank / outside pump). odometer_km = the
        # meter reading at the fill. Mileage + deviation vs benchmark are computed
        # at read time from these rows (services/fuel.py) — nothing derived stored.
        """
        CREATE TABLE IF NOT EXISTS vehicle_fuel_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            branch_id UUID,
            vehicle_id UUID NOT NULL REFERENCES vehicles(id),
            entry_date DATE NOT NULL,
            odometer_km NUMERIC(12,1) NOT NULL,
            litres NUMERIC(10,2) NOT NULL,
            rate_per_litre NUMERIC(10,2),
            amount NUMERIC(14,2),
            fuel_source VARCHAR(20) NOT NULL DEFAULT 'plant_tank',
            tank_full BOOLEAN NOT NULL DEFAULT TRUE,
            inventory_item_id UUID,
            inventory_txn_id UUID,
            driver_id UUID,
            notes VARCHAR(500),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_fuel_entries_vehicle ON vehicle_fuel_entries (company_id, vehicle_id, odometer_km)",
        "CREATE INDEX IF NOT EXISTS ix_fuel_entries_date ON vehicle_fuel_entries (company_id, entry_date)",
        # ── Petrol-pump fuel-credit POs (auto-created for outside-pump fills on
        #    credit). Pure accounts-payable ledger to the pump — NO inventory
        #    movement, NO P&L re-booking (fuel expense is already in the P&L via
        #    vehicle_fuel_entries). Payments allocate FIFO across a pump's POs.
        """
        CREATE TABLE IF NOT EXISTS fuel_purchase_orders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            po_no VARCHAR(40) NOT NULL,
            station_name VARCHAR(120) NOT NULL,
            supplier_party_id UUID,
            fuel_entry_id UUID,
            vehicle_id UUID,
            po_date DATE NOT NULL,
            litres NUMERIC(10,2),
            rate_per_litre NUMERIC(10,2),
            amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            amount_paid NUMERIC(14,2) NOT NULL DEFAULT 0,
            status VARCHAR(12) NOT NULL DEFAULT 'unpaid',
            notes VARCHAR(500),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_fuel_po_company ON fuel_purchase_orders (company_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_fuel_po_station ON fuel_purchase_orders (company_id, station_name)",
        "CREATE INDEX IF NOT EXISTS ix_fuel_po_entry ON fuel_purchase_orders (fuel_entry_id)",
        """
        CREATE TABLE IF NOT EXISTS fuel_po_payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            station_name VARCHAR(120) NOT NULL,
            amount NUMERIC(14,2) NOT NULL,
            payment_date DATE NOT NULL,
            mode VARCHAR(20) NOT NULL DEFAULT 'cash',
            reference VARCHAR(120),
            notes VARCHAR(500),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_fuel_po_pay_station ON fuel_po_payments (company_id, station_name)",
        # ── Workforce & Payroll (workers · attendance muster · payments) ──────
        # Workers are NOT logins — just payroll records. Earnings + balance are
        # computed at read time (services/payroll.py) from attendance + payments.
        """
        CREATE TABLE IF NOT EXISTS workers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            branch_id UUID,
            name VARCHAR(120) NOT NULL,
            phone VARCHAR(15),
            worker_type VARCHAR(20) NOT NULL DEFAULT 'daily_wage',
            rate NUMERIC(12,2) NOT NULL DEFAULT 0,
            designation VARCHAR(80),
            joining_date DATE,
            aadhaar_no VARCHAR(12),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            notes VARCHAR(500),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS worker_attendance (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            worker_id UUID NOT NULL REFERENCES workers(id),
            att_date DATE NOT NULL,
            status VARCHAR(12) NOT NULL DEFAULT 'present',
            ot_hours NUMERIC(4,1) NOT NULL DEFAULT 0,
            notes VARCHAR(200),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (worker_id, att_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS worker_payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            branch_id UUID,
            worker_id UUID NOT NULL REFERENCES workers(id),
            pay_date DATE NOT NULL,
            payment_type VARCHAR(20) NOT NULL DEFAULT 'wage',
            amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            mode VARCHAR(20) NOT NULL DEFAULT 'cash',
            reference VARCHAR(100),
            notes VARCHAR(300),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_worker_att_date ON worker_attendance (company_id, att_date)",
        "CREATE INDEX IF NOT EXISTS ix_worker_pay_date ON worker_payments (company_id, pay_date)",
        "CREATE INDEX IF NOT EXISTS ix_worker_pay_worker ON worker_payments (worker_id)",
        # Operator → accountant end-of-day cash handover (acknowledgment audit trail)
        """
        CREATE TABLE IF NOT EXISTS cash_handovers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            operator_id UUID,
            operator_name VARCHAR(120),
            handover_date DATE NOT NULL,
            amount NUMERIC(14,2) NOT NULL DEFAULT 0,
            notes VARCHAR(300),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            received_by UUID,
            received_by_name VARCHAR(120),
            acknowledged_at TIMESTAMPTZ,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_cash_handover_date ON cash_handovers (company_id, handover_date)",
        # Per-operator per-day cash-drawer reconciliation: opening float + physically
        # counted cash, so Operator Cash EOD can show variance vs the expected balance.
        """
        CREATE TABLE IF NOT EXISTS operator_cash_counts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            operator_id UUID,
            count_date DATE NOT NULL,
            opening_float NUMERIC(14,2) NOT NULL DEFAULT 0,
            counted_cash NUMERIC(14,2),
            notes VARCHAR(300),
            created_by UUID,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (company_id, operator_id, count_date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_op_cash_count_date ON operator_cash_counts (company_id, count_date)",
        # ── Maker-checker (4-eyes) approval queue ─────────────────────────────
        # When the per-tenant maker_checker toggle is ON, sensitive money actions
        # (write-off, bulk write-off, invoice cancel, day-book opening change) are
        # PARKED here as a pending request instead of executing. A second admin
        # (checker != maker) approves → the real action runs; rejects → it's
        # discarded. payload holds the exact request to replay on approval.
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID NOT NULL REFERENCES companies(id),
            action_type VARCHAR(40) NOT NULL,
            -- write_off | write_off_bulk | invoice_cancel | day_book_opening
            title VARCHAR(300) NOT NULL,
            amount NUMERIC(14,2),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(15) NOT NULL DEFAULT 'pending',
            -- pending | approved | rejected
            requested_by UUID REFERENCES users(id),
            requested_by_name VARCHAR(200),
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            decided_by UUID REFERENCES users(id),
            decided_by_name VARCHAR(200),
            decided_at TIMESTAMPTZ,
            decision_note VARCHAR(500),
            result JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_approval_requests_status ON approval_requests (company_id, status, requested_at DESC)",
        # Append-only audit of every movement
        """
        CREATE TABLE IF NOT EXISTS product_stock_movements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            product_id UUID NOT NULL REFERENCES products(id),
            movement_type VARCHAR(30) NOT NULL,
            -- opening, sale, purchase, adjustment, cycle_output, sale_cancelled, purchase_cancelled
            quantity NUMERIC(14,3) NOT NULL,
            -- signed: positive = in, negative = out
            stock_before NUMERIC(14,3) NOT NULL,
            stock_after NUMERIC(14,3) NOT NULL,
            reference_type VARCHAR(30),
            reference_id UUID,
            reference_no VARCHAR(50),
            notes TEXT,
            created_by UUID REFERENCES users(id),
            created_by_name VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # ── Production cycles (yield tracking) ────────────────────────────────
        # One cycle per day per company. Tracks input boulder → stage outputs.
        """
        CREATE TABLE IF NOT EXISTS production_cycles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id UUID REFERENCES companies(id),
            cycle_no INTEGER NOT NULL,
            cycle_date DATE NOT NULL,
            input_kg NUMERIC(14,2) NOT NULL DEFAULT 0,
            stage1_output_kg NUMERIC(14,2),
            stage2_output_kg NUMERIC(14,2),
            stage3_output_kg NUMERIC(14,2),
            is_finalised BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT,
            created_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (company_id, cycle_date)
        )
        """,
        # raw_material_id added here (AFTER the CREATE) so it applies in the same
        # startup on a fresh DB. Was previously listed before the CREATE, which
        # failed on fresh DBs and (under the old single-transaction runner)
        # aborted every subsequent CREATE TABLE in this list.
        "ALTER TABLE production_cycles ADD COLUMN IF NOT EXISTS raw_material_id UUID REFERENCES products(id)",
        # Per-product finished outputs at stage 4 (after wash)
        """
        CREATE TABLE IF NOT EXISTS production_cycle_outputs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cycle_id UUID NOT NULL REFERENCES production_cycles(id) ON DELETE CASCADE,
            product_id UUID NOT NULL REFERENCES products(id),
            output_kg NUMERIC(14,2) NOT NULL DEFAULT 0,
            UNIQUE (cycle_id, product_id)
        )
        """,
        # Invoice transport & dispatch metadata (Tally-compatible fields)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS royalty_no VARCHAR(50)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_note VARCHAR(100)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS supplier_ref VARCHAR(100)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS buyer_order_no VARCHAR(100)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS buyer_order_date DATE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS dispatch_doc_no VARCHAR(100)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS dispatch_through VARCHAR(200)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS destination VARCHAR(200)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS lr_rr_no VARCHAR(50)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS terms_of_delivery VARCHAR(200)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS driver_name VARCHAR(100)",
        # ── Invoice write-off tracking (admin/accountant action) ─────────────
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS write_off_amount NUMERIC(14,2) NOT NULL DEFAULT 0",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS write_off_reason VARCHAR(500)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS write_off_at TIMESTAMPTZ",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS write_off_by UUID REFERENCES users(id)",
        # ── ANPR (Automatic Number Plate Recognition) — gate cameras ──────────
        # Token columns added: gate_pass_no (auto-allocated via NumberSequence
        # with sequence_type='gate_pass'), anpr_entry_at/exit_at (timestamps
        # stamped by /api/v1/anpr/detect), source ('manual' | 'anpr' | 'kiosk').
        # The existing tokens.gate_pass (free-text, manual) column is left
        # untouched for backward compatibility.
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS gate_pass_no VARCHAR(40)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS anpr_entry_at TIMESTAMPTZ",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS anpr_exit_at TIMESTAMPTZ",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'manual'",
        "CREATE INDEX IF NOT EXISTS ix_tokens_gate_pass ON tokens(gate_pass_no)",
        # ANPR events: append-only log of every plate detection (entry, exit,
        # unmatched, duplicate). One row per detection. token_id is linked
        # when the detection results in token creation (entry) or token closure
        # (exit). needs_review = TRUE when plate didn't fuzzy-match any
        # registered Vehicle — surfaces in the /anpr/review queue.
        """
        CREATE TABLE IF NOT EXISTS anpr_events (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id        UUID REFERENCES companies(id),
            plate_raw         VARCHAR(20) NOT NULL,
            plate_normalized  VARCHAR(20) NOT NULL,
            vehicle_id        UUID REFERENCES vehicles(id),
            token_id          UUID REFERENCES tokens(id) ON DELETE SET NULL,
            direction         VARCHAR(15) NOT NULL,
            confidence        NUMERIC(4,3),
            source            VARCHAR(30) NOT NULL,
            camera_id         VARCHAR(20) NOT NULL,
            snapshot_path     TEXT,
            detected_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ocr_alternates    JSONB,
            needs_review      BOOLEAN NOT NULL DEFAULT FALSE,
            reviewed_by       UUID REFERENCES users(id),
            reviewed_at       TIMESTAMPTZ,
            notes             TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_anpr_events_company_at ON anpr_events(company_id, detected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_anpr_events_plate ON anpr_events(plate_normalized, detected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_anpr_events_token ON anpr_events(token_id)",
        "CREATE INDEX IF NOT EXISTS ix_anpr_events_unmatched ON anpr_events(needs_review) WHERE needs_review = TRUE",

        # ── Horizon-1: Delivery Challan (GST Rule 55 dispatch document) ──────
        # Own tables so a challan never leaks into GSTR-1 / P&L / receivables.
        # challan_no allocated gap-free at create (prefix DC). Converts to a
        # sale invoice (invoice_id links the two). EWB columns are populated by
        # the standalone NIC EWB flow for challan-based goods movement.
        """
        CREATE TABLE IF NOT EXISTS delivery_challans (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id       UUID REFERENCES companies(id),
            fy_id            UUID REFERENCES financial_years(id),
            challan_no       VARCHAR(30),
            challan_date     DATE NOT NULL,
            purpose          VARCHAR(30) NOT NULL DEFAULT 'supply',
            party_id         UUID REFERENCES parties(id),
            customer_name    VARCHAR(200),
            token_id         UUID REFERENCES tokens(id),
            vehicle_no       VARCHAR(20),
            transporter_name VARCHAR(200),
            driver_name      VARCHAR(100),
            distance_km      INTEGER,
            destination      VARCHAR(200),
            tax_type         VARCHAR(20) NOT NULL DEFAULT 'gst',
            sub_total        NUMERIC(14,2) NOT NULL DEFAULT 0,
            total_amount     NUMERIC(14,2) NOT NULL DEFAULT 0,
            status           VARCHAR(15) NOT NULL DEFAULT 'open',
            invoice_id       UUID REFERENCES invoices(id),
            notes            TEXT,
            ewb_no           VARCHAR(20),
            ewb_date         TIMESTAMPTZ,
            ewb_valid_till   TIMESTAMPTZ,
            ewb_status       VARCHAR(20) NOT NULL DEFAULT 'none',
            ewb_error        TEXT,
            created_by       UUID REFERENCES users(id),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delivery_challan_items (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            challan_id    UUID NOT NULL REFERENCES delivery_challans(id) ON DELETE CASCADE,
            product_id    UUID NOT NULL REFERENCES products(id),
            description   VARCHAR(300),
            hsn_code      VARCHAR(8),
            quantity      NUMERIC(12,3) NOT NULL,
            unit          VARCHAR(10) NOT NULL DEFAULT 'MT',
            rate          NUMERIC(12,2) NOT NULL DEFAULT 0,
            amount        NUMERIC(14,2) NOT NULL DEFAULT 0,
            gst_rate      NUMERIC(5,2) NOT NULL DEFAULT 0,
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_dc_company_date ON delivery_challans(company_id, challan_date DESC)",
        "CREATE INDEX IF NOT EXISTS ix_dc_status ON delivery_challans(company_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_dc_items_challan ON delivery_challan_items(challan_id)",

        # ── Horizon-1: E-Way Bill columns on invoices (eway_bill_no already
        # exists). ewb_status drives the generate/cancel UI; validity is shown
        # on the PDF. Populated by IRN-integrated capture + standalone NIC EWB.
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS ewb_date TIMESTAMPTZ",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS ewb_valid_till TIMESTAMPTZ",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS ewb_status VARCHAR(20) NOT NULL DEFAULT 'none'",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS ewb_error TEXT",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS ewb_distance_km INTEGER",

        # ── Horizon-1: GST Credit / Debit Notes reuse the invoices table with
        # invoice_type IN ('credit_note','debit_note'). reference_invoice_id
        # points at the original invoice the note adjusts; note_reason is the
        # statutory reason code shown on GSTR-1 CDNR.
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS reference_invoice_id UUID REFERENCES invoices(id)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS note_reason VARCHAR(200)",

        # ── Horizon-2: Royalty / Mining Transit-Pass ────────────────────────
        """
        CREATE TABLE IF NOT EXISTS royalty_passes (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            fy_id         UUID REFERENCES financial_years(id),
            pass_no       VARCHAR(60) NOT NULL,
            pass_type     VARCHAR(20) NOT NULL DEFAULT 'royalty',
            source_name   VARCHAR(200),
            party_id      UUID REFERENCES parties(id),
            mineral       VARCHAR(120),
            product_id    UUID REFERENCES products(id),
            issue_date    DATE,
            valid_till    DATE,
            quantity_mt   NUMERIC(14,3) NOT NULL DEFAULT 0,
            rate          NUMERIC(12,2) NOT NULL DEFAULT 0,
            amount        NUMERIC(14,2) NOT NULL DEFAULT 0,
            vehicle_no    VARCHAR(20),
            status        VARCHAR(15) NOT NULL DEFAULT 'active',
            notes         TEXT,
            created_by    UUID REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS royalty_pass_consumptions (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            pass_id       UUID NOT NULL REFERENCES royalty_passes(id) ON DELETE CASCADE,
            company_id    UUID REFERENCES companies(id),
            token_id      UUID REFERENCES tokens(id),
            invoice_id    UUID REFERENCES invoices(id),
            quantity_mt   NUMERIC(14,3) NOT NULL,
            consumed_date DATE NOT NULL,
            notes         TEXT,
            created_by    UUID REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_royalty_company_status ON royalty_passes(company_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_royalty_valid_till ON royalty_passes(company_id, valid_till)",
        "CREATE INDEX IF NOT EXISTS ix_royalty_cons_pass ON royalty_pass_consumptions(pass_id)",

        # Royalty P1: link token to its transit pass + variance tracking on consumptions
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS transit_pass_id UUID REFERENCES royalty_passes(id)",
        # Vehicle rent — payment to truck owner per trip (stone crusher practice)
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS vehicle_rent NUMERIC(14,2) DEFAULT 0",
        # Operator-entered trip distance (km) → vehicle_rent = vehicle rate × km × net MT
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS rent_km NUMERIC(10,2)",
        # Operator-overridable rent rates (₹/km/MT for weighed, ₹/km/CUM for volume)
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS rent_rate_per_km_per_mt NUMERIC(12,4)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS rent_rate_per_km_per_cum NUMERIC(12,4)",
        # Operator-set material price (₹ per billing_unit); auto-invoice uses it, else the resolver
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS rate NUMERIC(12,2)",
        # Operator-chosen payment mode (cash|credit|upi|bank_transfer); overrides party default → tax_type
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS payment_mode VARCHAR(20)",
        # Royalty (govt mineral levy): per-item rate ₹/CUM or ₹/MT + per-token CUM + basis + computed charge
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS royalty_per_cum NUMERIC(12,2)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS royalty_per_mt NUMERIC(12,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS royalty_cum NUMERIC(12,3)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS royalty_unit VARCHAR(8)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS royalty_rate NUMERIC(12,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS royalty_amount NUMERIC(14,2) DEFAULT 0",

        # ── Tokens backfill: the `tokens` table is created by SQLAlchemy
        # create_all (NOT a runtime CREATE TABLE), so a tenant whose tokens table
        # was built by an OLDER model version permanently lacks any column added
        # since that had no ALTER here — create_all skips existing tables. That
        # makes GET/POST /tokens 500 on those tenants. These IF-NOT-EXISTS ALTERs
        # are the idempotent safety net for every two-stage / type / weighment
        # column. Harmless (no-op) where the column already exists.
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS token_type VARCHAR(20) NOT NULL DEFAULT 'sale'",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS direction VARCHAR(10)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'OPEN'",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS driver_id UUID REFERENCES drivers(id)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS transporter_id UUID REFERENCES transporters(id)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS gross_weight NUMERIC(10,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS tare_weight NUMERIC(10,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS net_weight NUMERIC(10,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS first_weight NUMERIC(10,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS second_weight NUMERIC(10,2)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS first_weight_type VARCHAR(5)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS first_weight_at TIMESTAMPTZ",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS second_weight_at TIMESTAMPTZ",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS first_weight_by UUID REFERENCES users(id)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS second_weight_by UUID REFERENCES users(id)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS is_manual_weight BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
        # volume_cft is otherwise only added inside the guarded m³→CFT DO block,
        # so a tenant whose marker was set without the column getting added would
        # be left without it → SELECT over the Token model 500s. Plain net here.
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS volume_cft NUMERIC(10,3)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS weight_method VARCHAR(20) NOT NULL DEFAULT 'weighbridge'",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS tyre_count SMALLINT",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS vehicle_type VARCHAR(50)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS gate_pass_no VARCHAR(40)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS anpr_entry_at TIMESTAMPTZ",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS anpr_exit_at TIMESTAMPTZ",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'manual'",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS transit_pass_id UUID REFERENCES royalty_passes(id)",
        "ALTER TABLE tokens ADD COLUMN IF NOT EXISTS vehicle_rent NUMERIC(14,2) DEFAULT 0",
        "ALTER TABLE royalty_pass_consumptions ADD COLUMN IF NOT EXISTS authorized_mt NUMERIC(14,3)",
        "ALTER TABLE royalty_pass_consumptions ADD COLUMN IF NOT EXISTS actual_mt NUMERIC(14,3)",
        "ALTER TABLE royalty_pass_consumptions ADD COLUMN IF NOT EXISTS variance_mt NUMERIC(14,3)",
        "ALTER TABLE royalty_pass_consumptions ADD COLUMN IF NOT EXISTS vehicle_no VARCHAR(30)",

        # ── Horizon-2: Customer portal login (separate identity from staff) ──
        """
        CREATE TABLE IF NOT EXISTS customer_users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            party_id      UUID NOT NULL REFERENCES parties(id),
            email         VARCHAR(200) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            last_login_at TIMESTAMPTZ,
            created_by    UUID REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_users_email ON customer_users(company_id, lower(email))",
        "CREATE INDEX IF NOT EXISTS ix_customer_users_party ON customer_users(party_id)",

        # ── Horizon-3: Full multi-branch ────────────────────────────────────
        # Backward-compatible: branch_id is NULLABLE everywhere → existing rows
        # (NULL) are the implicit single "default branch", so current numbering
        # and queries are untouched. Only explicitly-created branches get an id.
        """
        CREATE TABLE IF NOT EXISTS branches (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            name          VARCHAR(150) NOT NULL,
            code          VARCHAR(12) NOT NULL,
            gstin         VARCHAR(15),
            address_line1 VARCHAR(255),
            city          VARCHAR(100),
            state         VARCHAR(100),
            state_code    VARCHAR(2),
            pincode       VARCHAR(10),
            phone         VARCHAR(20),
            is_default    BOOLEAN NOT NULL DEFAULT FALSE,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_branches_company ON branches(company_id, is_active)",
        "ALTER TABLE tokens             ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE invoices           ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE payment_receipts   ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE payment_vouchers   ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE product_stock      ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE production_cycles   ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE users              ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "ALTER TABLE number_sequences   ADD COLUMN IF NOT EXISTS branch_id UUID REFERENCES branches(id)",
        "CREATE INDEX IF NOT EXISTS ix_tokens_branch ON tokens(branch_id)",
        "CREATE INDEX IF NOT EXISTS ix_invoices_branch ON invoices(branch_id)",

        # ── Gate Management (CP Plus camera + guard-managed gate passes) ───────
        # Completely separate from ANPR.  Guard-managed: guard fills vehicle/driver/
        # material; cameras capture entry + exit photos on manual trigger or CP Plus
        # vehicle-detection webhook.  Token link is mandatory for weighbridge purpose.
        """
        CREATE TABLE IF NOT EXISTS gate_passes (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id          UUID REFERENCES companies(id),
            gate_pass_no        VARCHAR(30)  NOT NULL,  -- GP/2025-06-19/001
            pass_date           DATE         NOT NULL,
            seq_no              INTEGER      NOT NULL,
            vehicle_no          VARCHAR(30),
            vehicle_name        VARCHAR(100),
            vehicle_id          UUID REFERENCES vehicles(id),
            driver_name         VARCHAR(100),
            driver_phone        VARCHAR(15),
            driver_id           UUID REFERENCES drivers(id),
            material            VARCHAR(200),
            product_id          UUID REFERENCES products(id),
            purpose             VARCHAR(20)  NOT NULL DEFAULT 'weighbridge',
            token_id            UUID REFERENCES tokens(id),
            entry_time          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            exit_time           TIMESTAMPTZ,
            entry_photo_path    TEXT,
            exit_photo_path     TEXT,
            status              VARCHAR(15)  NOT NULL DEFAULT 'inside',
            notes               TEXT,
            created_by          UUID REFERENCES users(id),
            updated_by          UUID REFERENCES users(id),
            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_gate_passes_company_date ON gate_passes(company_id, pass_date DESC)",
        "CREATE INDEX IF NOT EXISTS ix_gate_passes_vehicle ON gate_passes(company_id, vehicle_no, pass_date DESC)",
        "CREATE INDEX IF NOT EXISTS ix_gate_passes_token ON gate_passes(token_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_gate_passes_no ON gate_passes(company_id, gate_pass_no)",
        "CREATE INDEX IF NOT EXISTS ix_gate_passes_status ON gate_passes(company_id, status, pass_date DESC)",
        "ALTER TABLE gate_passes ADD COLUMN IF NOT EXISTS vehicle_type VARCHAR(50)",

        # Daily sequence counter — one row per (company, date); INSERT … ON CONFLICT
        # DO UPDATE is atomic so no separate FOR UPDATE lock needed.
        """
        CREATE TABLE IF NOT EXISTS gate_pass_daily_seq (
            company_id  UUID  NOT NULL REFERENCES companies(id),
            pass_date   DATE  NOT NULL,
            last_no     INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (company_id, pass_date)
        )
        """,

        # Append-only log of every camera event (webhook or manual trigger).
        # Guard links an event to a gate_pass after the fact for audit purposes.
        """
        CREATE TABLE IF NOT EXISTS gate_camera_events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id      UUID REFERENCES companies(id),
            camera_position VARCHAR(10)  NOT NULL,  -- 'entry' | 'exit'
            camera_id       VARCHAR(50),
            gate_pass_id    UUID REFERENCES gate_passes(id),
            snapshot_path   TEXT,
            source          VARCHAR(20)  NOT NULL DEFAULT 'manual',  -- manual | webhook
            webhook_payload JSONB,
            detected_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            linked_at       TIMESTAMPTZ
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_gate_cam_events_company ON gate_camera_events(company_id, detected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_gate_cam_events_pass ON gate_camera_events(gate_pass_id)",

        # ── Device health (scale + camera heartbeat monitoring) ───────────────
        # A local watchdog agent (backend/agents/watchdog_agent.py) reads the
        # existing scale/camera agents' /status endpoints + probes the cameras and
        # POSTs a heartbeat per device here. The server-side _device_health_loop
        # fires a Telegram alert when a device is down / silent past the configured
        # threshold. One row per (company, device_key), upserted on each heartbeat.
        """
        CREATE TABLE IF NOT EXISTS device_health (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id   UUID REFERENCES companies(id),
            device_key   VARCHAR(80)  NOT NULL,   -- stable id, e.g. 'pc1:scale', 'pc2:cam:entry'
            device_type  VARCHAR(20)  NOT NULL,   -- scale | camera
            label        VARCHAR(120),            -- 'Weighing Scale', 'Gate Entry Camera'
            site         VARCHAR(80),             -- 'PC1 Weighbridge' / 'PC2 Gate'
            status       VARCHAR(10)  NOT NULL DEFAULT 'ok',  -- last reported: ok | down
            last_seen_at TIMESTAMPTZ,             -- last heartbeat received (any result)
            last_ok_at   TIMESTAMPTZ,             -- last time this device was healthy
            last_error   VARCHAR(300),
            alerted      BOOLEAN      NOT NULL DEFAULT FALSE,  -- down alert already sent this outage
            updated_at   TIMESTAMPTZ  DEFAULT NOW()
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_device_health_key ON device_health(company_id, device_key)",

        # ── Device uptime HISTORY (append-only) ───────────────────────────────
        # device_health is an UPSERT (one live row per device) so it answers "is it
        # down NOW?" but keeps no history — you cannot ask "how many times did the
        # scale drop today, for how long, at what hour". This table records every
        # status TRANSITION (online <-> offline/stale) detected by the 60 s
        # _device_health_loop, independent of the (5 min) alert threshold, so short
        # intermittent blips — the signature of a loose cable / electrical noise —
        # are captured too. Powers GET /api/v1/monitor/history.
        """
        CREATE TABLE IF NOT EXISTS device_events (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id   UUID REFERENCES companies(id),
            device_key   VARCHAR(80)  NOT NULL,
            device_type  VARCHAR(20),
            label        VARCHAR(120),
            site         VARCHAR(80),
            status       VARCHAR(10)  NOT NULL,   -- online | offline | stale
            reason       VARCHAR(300),            -- last_error / 'no heartbeat'
            down_seconds INTEGER,                 -- set on the transition BACK to online
            detected_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_device_events_co_dev ON device_events(company_id, device_key, detected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_device_events_co_time ON device_events(company_id, detected_at DESC)",

        # ── Autonomous gate vehicle counting (truck/car/motorcycle/bus) ───────
        # The on-site camera agent runs a lightweight vehicle-detection model on
        # the frames it already captures and POSTs one row per counted vehicle
        # (with an optional snapshot). Direction = which physical camera fired.
        # Purely additive: reconciles against the guard's gate passes; gated by
        # the `vehicle_count` feature module (default OFF). See routers/gate_count.py.
        """
        CREATE TABLE IF NOT EXISTS gate_vehicle_events (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            position      VARCHAR(10) NOT NULL,        -- 'entry' | 'exit'
            vehicle_class VARCHAR(20) NOT NULL,        -- truck | car | motorcycle | bus | ...
            confidence    NUMERIC(5,3),
            snapshot_path VARCHAR(300),                -- relative to /uploads
            source        VARCHAR(30) NOT NULL DEFAULT 'edge_yolo',
            camera_id     VARCHAR(20),
            detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_gate_veh_company_detected ON gate_vehicle_events(company_id, detected_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_gate_veh_company_pos_detected ON gate_vehicle_events(company_id, position, detected_at DESC)",

        # ── Document-number uniqueness (offline-ops prerequisite) ─────────────
        # Until now NOTHING enforced these at the DB level: invoice numbers relied
        # on the row-locked NumberSequence, and token_no on a read-then-write
        # collision probe (tokens.py::_next_token_no) which is inherently racy.
        # That is tolerable while the server is the only writer, but it is the
        # only atomic dedupe available once an offline terminal can replay a
        # queued operation, so it lands ahead of that work.
        #
        # These are guarded: _apply_all_ddl runs each statement in its own
        # transaction, so if a tenant already holds legacy duplicates the index
        # is skipped and logged rather than aborting the whole DDL pass.
        # Pre-flight before deploying (per tenant DB):
        #   SELECT company_id, branch_id, invoice_no, COUNT(*) FROM invoices
        #    WHERE invoice_no IS NOT NULL
        #    GROUP BY 1,2,3 HAVING COUNT(*) > 1;
        #   SELECT company_id, token_date, token_no, COUNT(*) FROM tokens
        #    WHERE token_no IS NOT NULL
        #    GROUP BY 1,2,3 HAVING COUNT(*) > 1;
        #
        # NOTE (scoped to branch deliberately): _next_invoice_no keeps a SEPARATE
        # sequence per branch_id but does NOT vary the prefix, so two branches
        # legitimately both mint 'INV/25-26/0001' today. A company-wide unique
        # index would therefore break finalisation on the second branch. Scoping
        # to branch still gives full replay-dedupe (a replay targets one branch)
        # without changing existing behaviour. The cross-branch duplicate is a
        # separate pre-existing concern — GST Rule 46(b) wants a unique series —
        # and is fixed by giving each branch its own prefix, the same mechanism
        # used for offline terminal prefixes.
        # COALESCE because Postgres treats NULLs as distinct in a unique index,
        # so the very common default branch (branch_id IS NULL) would otherwise
        # not be constrained at all.
        # Retire the older index (it did not exclude voided rows, so a superseded
        # revision original sharing a number with its /Rv child would block it).
        "DROP INDEX IF EXISTS ux_invoices_no_per_branch",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_no_active
            ON invoices (
                company_id,
                COALESCE(branch_id, '00000000-0000-0000-0000-000000000000'::uuid),
                invoice_no
            )
            WHERE invoice_no IS NOT NULL AND status NOT IN ('cancelled', 'superseded')
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_tokens_no_per_day
            ON tokens (company_id, token_date, token_no)
            WHERE token_no IS NOT NULL
        """,

        # ── Offline replay: idempotency ledger + client_op_id (P1 #171) ───────
        # Every mutation the edge captures carries a client-generated op id.
        # sync_operations is the ledger; the partial unique indexes on the
        # business tables are the correctness backstop so a racing replay can
        # never create a second row.
        "ALTER TABLE tokens   ADD COLUMN IF NOT EXISTS client_op_id UUID",
        "ALTER TABLE tokens   ADD COLUMN IF NOT EXISTS origin VARCHAR(10) NOT NULL DEFAULT 'online'",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS client_op_id UUID",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS origin VARCHAR(10) NOT NULL DEFAULT 'online'",
        # Offline approve-then-number (P1 #175)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approved BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id)",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
        """
        CREATE TABLE IF NOT EXISTS sync_operations (
            op_id         UUID PRIMARY KEY,
            company_id    UUID NOT NULL REFERENCES companies(id),
            user_id       UUID REFERENCES users(id),
            op_type       VARCHAR(40) NOT NULL,
            entity_type   VARCHAR(20),
            entity_id     UUID,
            assigned_json JSONB,
            origin        VARCHAR(10) NOT NULL DEFAULT 'online',
            status        VARCHAR(16) NOT NULL DEFAULT 'applied',
            error         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_sync_ops_company ON sync_operations(company_id, created_at DESC)",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_tokens_client_op
            ON tokens (company_id, client_op_id) WHERE client_op_id IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_client_op
            ON invoices (company_id, client_op_id) WHERE client_op_id IS NOT NULL
        """,
    ]


def get_supplier_ddl() -> str:
    """Return the inventory_item_suppliers CREATE TABLE statement."""
    return """
        CREATE TABLE IF NOT EXISTS inventory_item_suppliers (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            item_id            UUID NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
            supplier_name      VARCHAR(200) NOT NULL,
            is_preferred       BOOLEAN NOT NULL DEFAULT FALSE,
            lead_time_days     INTEGER,
            agreed_unit_price  NUMERIC(14,2),
            moq                NUMERIC(14,3),
            notes              TEXT,
            is_active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """


def get_supplier_master_ddl() -> str:
    """Return the inventory_suppliers CREATE TABLE statement."""
    return """
        CREATE TABLE IF NOT EXISTS inventory_suppliers (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_id    UUID REFERENCES companies(id),
            name          VARCHAR(200) NOT NULL,
            contact_person VARCHAR(200),
            phone         VARCHAR(30),
            email         VARCHAR(200),
            notes         TEXT,
            is_active     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """
