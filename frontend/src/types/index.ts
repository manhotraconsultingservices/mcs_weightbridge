export interface User {
  id: string;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  role: string;
  is_active: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
  tenant_slug?: string;
  tenant_status?: string;         // active | readonly | suspended
  tenant_status_message?: string;
  tenant_modules?: Record<string, boolean>;
  tenant_industry?: string;
  tenant_admin_restrictions?: string[];   // pages the platform withheld from this tenant       // vertical profile → terminology overlay
}

// ── Platform types ──────────────────────────────────────────────────────────

export interface PlatformBranding {
  company_name: string;
  website: string | null;
  email: string | null;
  logo_url: string | null;
}

export interface PlatformUser {
  id: string;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  role: 'platform_admin' | 'sales_rep';
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TenantOverview {
  id: string;
  slug: string;
  display_name: string;
  db_name: string;
  is_active: boolean;
  status: string;
  amc_start_date: string | null;
  amc_expiry_date: string | null;
  logo_url: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  agent_api_key: string;
  config?: Record<string, any> | null;   // tenant config JSON (incl. industry, modules)
  sales_reps: { id: string; username: string; full_name: string | null; email: string | null }[];
  created_at: string;
  updated_at: string;
}

export interface Company {
  id: string;
  name: string;
  legal_name: string | null;
  gstin: string | null;
  pan: string | null;
  address_line1: string | null;
  city: string | null;
  state: string | null;
  state_code: string | null;
  pincode: string | null;
  phone: string | null;
  email: string | null;
  invoice_prefix: string;
  quotation_prefix: string;
  purchase_prefix: string;
}

export interface Product {
  id: string;
  category_id: string | null;
  name: string;
  code: string | null;
  hsn_code: string;
  unit: string;
  default_rate: number;
  gst_rate: number;
  bulk_density: number | null;   // kg/CFT — enables volume → weight conversion in tokens
  royalty_per_cum: number | null;   // ₹ royalty per cubic metre (CUM)
  royalty_per_mt: number | null;    // ₹ royalty per metric tonne (MT)
  is_raw_material: boolean;       // marks raw inputs to production (e.g., raw boulder)
  description: string | null;
  is_active: boolean;
}

export interface ProductCategory {
  id: string;
  name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface Party {
  id: string;
  party_type: string;
  name: string;
  legal_name: string | null;
  gstin: string | null;
  pan: string | null;
  phone: string | null;
  email: string | null;
  contact_person: string | null;
  billing_city: string | null;
  billing_state: string | null;
  billing_state_code: string | null;
  credit_limit: number;
  payment_terms_days: number;
  opening_balance: number;
  current_balance: number;
  default_payment_mode: 'online' | 'cash';   // drives tax_type + Tally eligibility
  tally_ledger_name: string | null;
  is_active: boolean;
}

export interface Vehicle {
  id: string;
  registration_no: string;
  vehicle_type: string | null;
  owner_name: string | null;
  owner_phone: string | null;
  default_tare_weight: number;
  benchmark_mileage_kmpl: number | null;
  tank_capacity_litres: number | null;
  current_odometer_km: number | null;
  rent_rate_per_km_per_mt: number | null;
  rent_rate_per_km_per_cum: number | null;
  is_active: boolean;
}

export interface FinancialYear {
  id: string;
  label: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
}

export interface TokenParty {
  id: string;
  name: string;
}

export interface TokenProduct {
  id: string;
  name: string;
  unit: string;
  bulk_density: number | null;   // kg/CFT — enables MT ↔ volume conversion in UI
  royalty_per_mt: number | null;    // ₹/MT master rate — prefills the token royalty field
  royalty_per_cum: number | null;   // ₹/CUM master rate — prefills the token royalty field
}

export interface TokenVehicle {
  id: string;
  registration_no: string;
  default_tare_weight: number | null;
}

export interface TokenDriver {
  id: string;
  name: string;
  phone: string | null;
  license_no: string | null;
}

export interface TokenTransporter {
  id: string;
  name: string;
  phone: string | null;
}

export interface TokenLinkedInvoice {
  id: string;
  invoice_no: string | null;
  grand_total: number | null;
  status: string | null;
  payment_status: string | null;
}

export interface CustomFieldDefinition {
  id: string;
  entity_type: 'token' | 'product' | 'party';
  field_key: string;
  label: string;
  field_type: 'text' | 'number' | 'select' | 'date' | 'boolean';
  unit: string | null;
  options: string[] | null;
  required: boolean;
  show_on_slip: boolean;
  sort_order: number;
  is_active: boolean;
}

export interface Token {
  // Who booked the weighment — resolved server-side from tokens.created_by
  // (full_name, else username). Blank when unknown.
  created_by?: string | null;
  created_by_name?: string | null;
  id: string;
  token_no: number | null;
  token_date: string;
  status: 'OPEN' | 'FIRST_WEIGHT' | 'LOADING' | 'SECOND_WEIGHT' | 'COMPLETED' | 'CANCELLED';
  direction: 'inbound' | 'outbound';
  token_type: 'sale' | 'purchase' | 'general';
  vehicle_no: string;
  vehicle_type: string | null;
  tyre_count: number | null;          // 4/6/8/10/12 — shown on printed slip
  party: TokenParty | null;
  product: TokenProduct | null;
  vehicle: TokenVehicle | null;
  driver: TokenDriver | null;
  transporter: TokenTransporter | null;
  linked_invoice: TokenLinkedInvoice | null;
  gross_weight: number | null;
  tare_weight: number | null;
  net_weight: number | null;
  first_weight: number | null;
  second_weight: number | null;
  first_weight_type: string | null;
  is_manual_weight: boolean;
  is_supplement: boolean;
  weight_method: 'weighbridge' | 'volume';   // measurement method
  volume_cft: number | null;                  // cubic feet — populated only when weight_method === 'volume'
  billing_unit: string | null;                // operator-chosen billing unit (MT/CFT/CBM/BRASS…)
  rate?: number | null;                        // operator-set ₹ per billing_unit (customer-wise/default, editable)
  payment_mode?: string | null;               // cash | credit | upi | bank_transfer — drives invoice tax type
  operator_name?: string | null;              // who created the token (cash accountability)
  gate_pass: string | null;                   // legacy free-text gate-pass note
  gate_pass_no: string | null;                // auto-allocated GP/25-26/0001
  source: 'manual' | 'anpr' | 'kiosk' | string;
  anpr_entry_at: string | null;
  anpr_exit_at: string | null;
  transit_pass_id: string | null;
  vehicle_rent: number | null;
  rent_km: number | null;
  destination: string | null;               // where the trip went (shown with the km)
  rent_rate_per_km_per_mt: number | null;   // rent rate used (₹/km/MT)
  rent_rate_per_km_per_cum: number | null;  // rent rate used (₹/km/CUM)
  royalty_cum: number | null;      // CUM the royalty was charged on
  royalty_unit: string | null;     // 'mt' | 'cum' — royalty basis
  royalty_rate: number | null;     // ₹/unit rate used (operator override or product master)
  royalty_amount: number | null;   // computed royalty charge (rate × qty)
  remarks: string | null;
  custom_fields: Record<string, unknown> | null;   // owner-defined attribute values
  created_at: string;
  first_weight_at: string | null;
  second_weight_at: string | null;
  completed_at: string | null;
  // Edge-only (offline, P1 #175): an estimated bill amount + whether an offline
  // approve intent is already queued. Absent on the cloud token detail (which
  // carries the real linked_invoice instead).
  bill_estimate?: string | null;
  approve_queued?: boolean;
}

export interface TokenListResponse {
  items: Token[];
  total: number;
  page: number;
  page_size: number;
}

export interface InvoiceItem {
  id: string;
  product_id: string;
  description: string | null;
  hsn_code: string | null;
  quantity: number;
  unit: string;
  rate: number;
  amount: number;
  gst_rate: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  sort_order: number;
  // Per-item adhoc-invoice charges (royalty ₹/MT|CUM · vehicle fare ₹/km/unit × km × qty)
  royalty_unit?: string | null;
  royalty_rate?: number | null;
  royalty_amount?: number | null;
  fare_unit?: string | null;
  fare_rate?: number | null;
  fare_km?: number | null;
  fare_amount?: number | null;
  fare_trips?: number[] | null;
}

export interface InvoiceParty {
  id: string;
  name: string;
  gstin: string | null;
  billing_city: string | null;
  billing_state: string | null;
  billing_state_code: string | null;
}

export interface Invoice {
  id: string;
  invoice_type: 'sale' | 'purchase';
  tax_type: 'gst' | 'non_gst';
  invoice_no: string | null;
  invoice_date: string;
  due_date: string | null;
  party: InvoiceParty | null;
  customer_name: string | null;
  token_id: string | null;
  token_no: number | null;
  token_date: string | null;
  vehicle_no: string | null;
  transporter_name: string | null;
  eway_bill_no: string | null;
  // Transport & dispatch metadata (Tally-compatible)
  royalty_no?: string | null;
  delivery_note?: string | null;
  supplier_ref?: string | null;
  buyer_order_no?: string | null;
  buyer_order_date?: string | null;
  dispatch_doc_no?: string | null;
  dispatch_through?: string | null;
  destination?: string | null;
  lr_rr_no?: string | null;
  terms_of_delivery?: string | null;
  driver_name?: string | null;
  gross_weight: number | null;
  tare_weight: number | null;
  net_weight: number | null;
  subtotal: number;
  discount_type: string | null;
  discount_value: number;
  discount_amount: number;
  taxable_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  tcs_rate: number;
  tcs_amount: number;
  freight: number;
  vehicle_rent?: number;
  royalty_amount?: number;
  total_amount: number;
  round_off: number;
  grand_total: number;
  payment_mode: string | null;
  payment_status: 'unpaid' | 'partial' | 'paid';
  amount_paid: number;
  amount_due: number;
  // Write-off tracking — admin/accountant closes uncollectable balance
  write_off_amount?: number;
  write_off_reason?: string | null;
  write_off_at?: string | null;
  status: 'draft' | 'final' | 'cancelled';
  notes: string | null;
  tally_synced: boolean;
  tally_sync_at: string | null;
  tally_needs_sync: boolean;
  // eInvoice (GST IRN)
  irn: string | null;
  irn_ack_no: string | null;
  irn_ack_date: string | null;
  einvoice_status: 'none' | 'success' | 'failed' | 'cancelled';
  einvoice_error: string | null;
  irn_cancelled_at: string | null;
  // Revision / amendment tracking
  revision_no: number;
  original_invoice_id: string | null;
  created_at: string;
  updated_at: string;
  created_by?: string | null;
  created_by_name?: string | null;
  items: InvoiceItem[];
}

// ── Invoice Revision types ────────────────────────────────────────────────────

export interface RevisionHistoryItem {
  id: string;
  original_invoice_id: string;
  from_revision_no: number;
  to_revision_no: number;
  from_invoice_id: string;
  to_invoice_id: string;
  change_summary: string | null;
  revised_by_name: string | null;
  created_at: string;
  finalized_at: string | null;
}

export interface InvoiceRevisionChain {
  original_invoice_id: string;
  current_revision_no: number;
  invoices: Invoice[];
  history: RevisionHistoryItem[];
}

export interface DiffChange {
  field: string;
  label: string;
  old: string | number | null;
  new: string | number | null;
  old_str?: string | null;
  new_str?: string | null;
}

export interface DiffItem {
  product_id: string;
  description: string;
  hsn_code?: string | null;
  quantity?: number;
  unit?: string;
  rate?: number;
  gst_rate?: number;
  total_amount?: number;
  changes?: DiffChange[];
}

export interface InvoiceDiff {
  header: DiffChange[];
  amounts: DiffChange[];
  items: {
    added: DiffItem[];
    removed: DiffItem[];
    modified: DiffItem[];
  };
  einvoice: DiffChange[];
  summary_text: string;
  has_changes: boolean;
}

export interface InvoiceCompare {
  invoice_a: Invoice;
  invoice_b: Invoice;
  diff: InvoiceDiff;
  revision_record: RevisionHistoryItem | null;
}

export interface InvoiceListResponse {
  items: Invoice[];
  total: number;
  page: number;
  page_size: number;
}

export interface QuotationItem {
  id: string;
  product_id: string;
  description: string | null;
  hsn_code: string | null;
  quantity: number;
  unit: string;
  rate: number;
  amount: number;
  gst_rate: number;
  total_amount: number;
  sort_order: number;
}

export interface Quotation {
  id: string;
  quotation_no: string;
  quotation_date: string;
  valid_to: string | null;
  party: { id: string; name: string; gstin: string | null } | null;
  status: 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired' | 'converted';
  subtotal: number;
  discount_amount: number;
  taxable_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  igst_amount: number;
  total_amount: number;
  round_off: number;
  grand_total: number;
  notes: string | null;
  terms_and_conditions: string | null;
  created_at: string;
  items: QuotationItem[];
}

export interface QuotationListResponse {
  items: Quotation[];
  total: number;
  page: number;
  page_size: number;
}

// ── Camera snapshots ──────────────────────────────────────────────────────────

export interface SnapshotResult {
  id: string;
  token_id: string;
  camera_id: string;
  camera_label: string | null;
  url: string | null;
  capture_status: 'pending' | 'captured' | 'failed';
  attempts: number;
  error_message: string | null;
  captured_at: string | null;
  weight_stage: 'first_weight' | 'second_weight' | 'volume';
}

export interface TokenSnapshotsResponse {
  snapshots: SnapshotResult[];
  all_done: boolean;
}

export interface SnapshotSearchItem {
  token_id: string;
  token_no: string | null;
  token_date: string | null;
  vehicle_no: string | null;
  party_name: string | null;
  weight_stage: 'first_weight' | 'second_weight' | 'volume';
  camera_id: string;
  camera_label: string | null;
  url: string | null;
  capture_status: string;
  captured_at: string | null;
}

export interface SnapshotSearchResponse {
  items: SnapshotSearchItem[];
  total: number;
}

// ── Inventory ─────────────────────────────────────────────────────────────────

export type StockStatus = 'ok' | 'low' | 'out';

export interface ItemSupplier {
  id: string;
  item_id: string;
  master_supplier_id: string | null;
  supplier_name: string;
  is_preferred: boolean;
  lead_time_days: number | null;       // ETA in days
  agreed_unit_price: number | null;
  moq: number | null;                  // Minimum Order Quantity
  notes: string | null;
  is_active: boolean;
}

export interface MasterSupplier {
  id: string;
  name: string;
  contact_person: string | null;
  phone: string | null;
  email: string | null;
  notes: string | null;
  is_active: boolean;
}

export interface InventoryItem {
  id: string;
  name: string;
  category: string;
  unit: string;
  current_stock: number;
  min_stock_level: number;
  reorder_quantity: number;
  auto_po_enabled: boolean;
  description: string | null;
  is_active: boolean;
  stock_status: StockStatus;
  suppliers: ItemSupplier[];
  created_at: string;
  updated_at: string;
}

export interface InventoryTransaction {
  id: string;
  item_id: string;
  item_name: string;
  transaction_type: 'receipt' | 'issue' | 'adjustment';
  quantity: number;
  stock_before: number;
  stock_after: number;
  reference_no: string | null;
  notes: string | null;
  created_by_name: string | null;
  used_by_name: string | null;
  used_on: string | null;       // ISO date YYYY-MM-DD
  created_at: string;
}

export interface POItem {
  id: string;
  item_id: string;
  item_name: string;
  unit: string;
  quantity_ordered: number;
  quantity_received: number;
  unit_price: number | null;
}

export type POStatus =
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'partially_received'
  | 'received';

export interface PurchaseOrder {
  id: string;
  po_no: string;
  status: POStatus;
  supplier_name: string | null;
  expected_date: string | null;
  notes: string | null;
  requested_by_name: string;
  approved_by_name: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  is_auto_generated: boolean;
  created_at: string;
  updated_at: string;
  items: POItem[];
}

export interface InventoryDashboard {
  items: InventoryItem[];
  pending_po_count: number;
  recent_transactions: InventoryTransaction[];
}

export interface TelegramSettings {
  bot_token: string;
  chat_id: string;
  report_time: string;
  enabled: boolean;
}

// ── Customer 360 view ─────────────────────────────────────────────────────────

export interface Party360Header {
  id: string;
  name: string;
  party_type: string;
  gstin: string | null;
  pan: string | null;
  phone: string | null;
  email: string | null;
  billing_city: string | null;
  billing_state: string | null;
  credit_limit: number;
  payment_terms_days: number;
  current_balance: number;
  opening_balance: number;
  is_active: boolean;
}

export interface Party360AgingBuckets {
  current: number;
  bucket_1_30: number;
  bucket_31_60: number;
  bucket_61_90: number;
  bucket_90_plus: number;
}

export interface Party360Stats {
  lifetime_sales: number;
  lifetime_paid: number;
  lifetime_written_off: number;
  write_off_count: number;
  invoice_count: number;
  avg_order_value: number;
  last_invoice_date: string | null;
  days_since_last_order: number | null;
  last_payment_date: string | null;
  days_since_last_payment: number | null;
  total_outstanding: number;
  total_overdue: number;
  advance_balance: number;
  aging: Party360AgingBuckets;
  token_count: number;
  lifetime_tonnage: number;
}

// ── Agents (brokers/dalals) + commission ──────────────────────────────────────
export type CommissionType = 'per_mt' | 'pct_of_taxable' | 'pct_of_grand_total' | 'flat_per_invoice';

export interface Agent {
  id: string;
  name: string;
  phone: string | null;
  gstin: string | null;
  pan: string | null;
  address: string | null;
  commission_type: CommissionType;
  commission_rate: number;
  notes: string | null;
  is_active: boolean;
}

export interface AgentPayout {
  id: string;
  agent_id: string;
  amount: number;
  paid_on: string;
  payment_mode: string | null;
  reference_no: string | null;
  notes: string | null;
  created_at: string;
}

export interface AgentReportInvoice {
  invoice_id: string;
  invoice_no: string | null;
  invoice_date: string;
  invoice_type: string;
  party_name: string | null;
  net_weight_mt: number;
  taxable_amount: number;
  grand_total: number;
  commission_amount: number;
}

export interface AgentReport {
  agent: Agent;
  earned: number;
  paid: number;
  due: number;
  invoice_count: number;
  total_sale_value: number;
  invoices: AgentReportInvoice[];
  payouts: AgentPayout[];
}

export interface AgentSummaryRow {
  agent_id: string;
  name: string;
  commission_type: CommissionType;
  commission_rate: number;
  invoice_count: number;
  earned: number;
  paid: number;
  due: number;
}

export interface AgentTrendPoint {
  period: string;
  label: string;
  earned: number;
  paid: number;
  invoice_count: number;
}
export interface AgentTrendResponse {
  granularity: 'day' | 'week' | 'month';
  date_from: string;
  date_to: string;
  series: AgentTrendPoint[];
  totals: { earned: number; paid: number; invoice_count: number };
}

export interface Party360Invoice {
  id: string;
  invoice_no: string | null;
  invoice_date: string;
  due_date: string | null;
  invoice_type: string;
  grand_total: number;
  amount_paid: number;
  amount_due: number;
  payment_status: string;
  status: string;
}

export interface Party360Payment {
  id: string;
  kind: 'receipt' | 'voucher';
  voucher_no: string;
  payment_date: string;
  amount: number;
  payment_mode: string;
  reference_no: string | null;
}

export interface Party360CustomRate {
  product_id: string;
  product_name: string;
  product_unit: string;
  default_rate: number;
  custom_rate: number;
  effective_from: string;
}

export interface Party360Response {
  party: Party360Header;
  stats: Party360Stats;
  recent_invoices: Party360Invoice[];
  recent_payments: Party360Payment[];
  custom_rates: Party360CustomRate[];
}

// ── ANPR (Automatic Number Plate Recognition) ─────────────────────────────────

export interface AnprOcrAlternate {
  plate: string;
  confidence: number;
}

export interface AnprVehicleBrief {
  id: string;
  registration_no: string;
}

export interface AnprTokenBrief {
  id: string;
  token_no: number | null;
  token_date: string;
  status: string;
  vehicle_no: string;
  gate_pass_no: string | null;
  party_name: string | null;
  product_name: string | null;
}

export interface AnprEvent {
  id: string;
  plate_raw: string;
  plate_normalized: string;
  direction: 'entry' | 'exit' | 'unmatched' | 'duplicate' | 'heartbeat';
  confidence: number | null;     // Pydantic serialises Decimal as string — coerce with Number() at point of use
  source: string;
  camera_id: string;
  snapshot_path: string | null;
  detected_at: string;
  needs_review: boolean;
  reviewed_at: string | null;
  notes: string | null;
  vehicle: AnprVehicleBrief | null;
  token: AnprTokenBrief | null;
  ocr_alternates: AnprOcrAlternate[] | null;
}

export interface AnprEventListResponse {
  items: AnprEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface AnprDayBucket {
  date: string;
  entries: number;
  exits: number;
}

export interface AnprStats {
  entries: number;
  exits: number;
  unmatched: number;
  unique_vehicles: number;
  currently_inside: number;
  avg_dwell_minutes: number;
  by_day: AnprDayBucket[];
}

export interface AnprConfig {
  enabled: boolean;
  engine: 'local_fastalpr' | 'hikvision_webhook' | 'dahua_webhook';
  gate_camera_id: string;
  cooldown_sec: number;
  min_confidence: number;
  fuzzy_match: boolean;
  auto_create_token: boolean;
  notify_owner: boolean;
  notify_unknown_plate: boolean;
  daily_summary: boolean;            // Telegram daily-list at owner-digest time
  webhook_secret: string | null;     // *** sentinel on GET
}

// One row per vehicle visit — for the daily trip report page
export interface AnprTrip {
  token_id: string;
  token_no: number | null;
  token_date: string;
  vehicle_no: string;
  gate_pass_no: string | null;
  entry_time: string | null;
  exit_time: string | null;
  dwell_minutes: number | null;
  party_name: string | null;
  product_name: string | null;
  net_weight_mt: number | null;      // Pydantic Decimal → JSON string; coerce with Number()
  invoice_id: string | null;
  invoice_no: string | null;
  invoice_status: 'draft' | 'final' | 'cancelled' | null;
  payment_status: 'unpaid' | 'partial' | 'paid' | null;
  grand_total: number | null;
  status: string;
  source: 'manual' | 'anpr' | 'kiosk' | string;
}

export interface AnprTripListResponse {
  items: AnprTrip[];
  total: number;
  page: number;
  page_size: number;
  entries: number;
  exits: number;
  currently_inside: number;
  total_tonnage_mt: number;        // material DISPATCHED (sale tokens)
  received_tonnage_mt?: number;    // material RECEIVED (purchase tokens)
  purchase_value?: number;         // purchase bills against these trips
  total_revenue: number;
  avg_dwell_minutes: number;
}

// ── Gate Management ───────────────────────────────────────────────────────────

export type GatePassStatus = 'inside' | 'exited' | 'cancelled';
export type GatePassPurpose = 'weighbridge' | 'delivery' | 'pickup' | 'own_use' | 'other';

export interface GatePass {
  id: string;
  gate_pass_no: string;
  pass_date: string;
  seq_no: number;
  vehicle_no: string | null;
  vehicle_name: string | null;
  vehicle_id: string | null;
  vehicle_type: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  material: string | null;
  product_id: string | null;
  purpose: GatePassPurpose;
  token_id: string | null;
  token_no: string | null;
  net_weight: number | null;
  entry_time: string;
  exit_time: string | null;
  entry_photo_path: string | null;
  exit_photo_path: string | null;
  status: GatePassStatus;
  notes: string | null;
  created_by: string | null;
  created_by_name: string | null;
  /** Who let the vehicle IN (the pass creator) and OUT (stamped at exit, never overwritten). */
  entered_by_name: string | null;
  exited_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface GatePassSummary {
  date: string;
  total_entered: number;
  total_exited: number;
  currently_inside: number;
  cancelled: number;
  unlinked_weighbridge: number;
  mismatch: boolean;
  inside_list: GatePass[];
}

export interface GateCameraEvent {
  id: string;
  company_id: string;
  camera_position: 'entry' | 'exit';
  camera_id: string | null;
  gate_pass_id: string | null;
  snapshot_path: string | null;
  source: 'manual' | 'webhook';
  detected_at: string;
  linked_at: string | null;
}


// ── Device Health (scale + camera watchdog) ──────────────────────────────────
export interface DeviceHealthItem {
  device_key: string;
  device_type: string;          // scale | camera | agent
  label: string;
  site: string | null;
  status: 'online' | 'offline' | 'stale';
  last_seen_at: string | null;
  last_seen_age_secs: number | null;
  last_ok_at: string | null;
  last_error: string | null;
}

export interface DeviceHealthConfig {
  enabled: boolean;
  down_threshold_min: number;
  stale_min: number;
}

export interface DeviceHealthResponse {
  devices: DeviceHealthItem[];
  summary: { total: number; online: number; down: number };
  config: DeviceHealthConfig;
}
