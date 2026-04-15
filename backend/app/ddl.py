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
    ]


def get_column_migrations() -> list[str]:
    """Return column migration ALTER TABLE statements."""
    return [
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
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_vehicle BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_token BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE tally_config ADD COLUMN IF NOT EXISTS narration_weight BOOLEAN NOT NULL DEFAULT TRUE",
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
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS tally_synced BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE inventory_purchase_orders ADD COLUMN IF NOT EXISTS tally_sync_at TIMESTAMPTZ",
        # eInvoice (GST IRN) columns on invoices
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
