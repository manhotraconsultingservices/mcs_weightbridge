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

export interface Token {
  id: string;
  token_no: number | null;
  token_date: string;
  status: 'OPEN' | 'FIRST_WEIGHT' | 'LOADING' | 'SECOND_WEIGHT' | 'COMPLETED' | 'CANCELLED';
  direction: 'inbound' | 'outbound';
  token_type: 'sale' | 'purchase' | 'general';
  vehicle_no: string;
  vehicle_type: string | null;
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
  remarks: string | null;
  created_at: string;
  first_weight_at: string | null;
  second_weight_at: string | null;
  completed_at: string | null;
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
  total_amount: number;
  round_off: number;
  grand_total: number;
  payment_mode: string | null;
  payment_status: 'unpaid' | 'partial' | 'paid';
  amount_paid: number;
  amount_due: number;
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
  weight_stage: 'first_weight' | 'second_weight';
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
  weight_stage: 'first_weight' | 'second_weight';
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

