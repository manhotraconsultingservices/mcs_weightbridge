-- ===========================================================================
-- Convert a MAIZE tenant's products from MT billing → QUINTAL billing.
--   1 MT = 10 Quintal (1 Quintal = 100 kg).
--
-- WHY: the on-screen weighbridge UI already shows Quintal for a maize_trader
-- tenant (industry-driven). But the slip PDF + auto-invoice billing read the
-- *product* unit, and product_stock.current_stock / party_rates / default_rate
-- are all stored in the product unit (MT). So to bill + print in Quintal we
-- flip products.unit → QUINTAL and rescale the dependent numbers so existing
-- balances stay numerically correct:
--     party_rates.rate            ÷ 10   (₹/MT  → ₹/Qtl)
--     products.default_rate       ÷ 10   (₹/MT  → ₹/Qtl)
--     product_stock.current_stock × 10   (MT qty → Qtl qty)
--     product_stock.min_stock_level × 10
--     product_stock_movements.{quantity, stock_before, stock_after} × 10
--     products.unit               'MT' → 'QUINTAL'
--
-- NOT touched: tokens.net_weight (always kg), historical invoices/invoice_items
-- (their amounts are already correct; only the unit *label* is historical).
--
-- HOW TO RUN (on the VPS, inside the Postgres container):
--   1) Open psql against the tenant DB (note the hyphen needs quoting):
--        docker exec -it <pg_container> psql -U weighbridge -d "wb_megna-trading"
--   2) Run the PREVIEW block first (read-only) and sanity-check the numbers.
--   3) Run the TRANSACTION block. It ends with COMMIT. To test without saving,
--      change the final COMMIT to ROLLBACK, run, inspect, then re-run with COMMIT.
--
-- Targets ONLY products currently in MT — already-QUINTAL products are skipped,
-- so this is safe to re-run (idempotent: a 2nd run finds 0 MT products).
-- ===========================================================================

-- ----------------------------------------------------------------------------
-- PREVIEW (read-only) — what will change
-- ----------------------------------------------------------------------------
SELECT p.name,
       p.unit                       AS unit_now,
       p.default_rate               AS rate_per_mt_now,
       (p.default_rate / 10)        AS rate_per_qtl_after,
       ps.current_stock             AS stock_mt_now,
       (ps.current_stock * 10)      AS stock_qtl_after
FROM products p
LEFT JOIN product_stock ps ON ps.product_id = p.id
WHERE upper(p.unit) = 'MT'
ORDER BY p.name;

-- Count of party_rate rows that will be divided by 10:
SELECT count(*) AS party_rate_rows_to_rescale
FROM party_rates pr
JOIN products p ON p.id = pr.product_id
WHERE upper(p.unit) = 'MT';


-- ----------------------------------------------------------------------------
-- TRANSACTION — apply the conversion (dependent rescales BEFORE the unit flip)
-- ----------------------------------------------------------------------------
BEGIN;

UPDATE party_rates pr
   SET rate = pr.rate / 10
  FROM products p
 WHERE pr.product_id = p.id
   AND upper(p.unit) = 'MT';

UPDATE product_stock ps
   SET current_stock   = ps.current_stock   * 10,
       min_stock_level = ps.min_stock_level * 10
  FROM products p
 WHERE ps.product_id = p.id
   AND upper(p.unit) = 'MT';

UPDATE product_stock_movements pm
   SET quantity     = pm.quantity     * 10,
       stock_before = pm.stock_before * 10,
       stock_after  = pm.stock_after  * 10
  FROM products p
 WHERE pm.product_id = p.id
   AND upper(p.unit) = 'MT';

UPDATE products
   SET default_rate = default_rate / 10
 WHERE upper(unit) = 'MT';

-- Flip the unit LAST (the filters above key off unit = 'MT').
UPDATE products
   SET unit = 'QUINTAL'
 WHERE upper(unit) = 'MT';

-- Change to ROLLBACK to dry-run the transaction without saving.
COMMIT;
