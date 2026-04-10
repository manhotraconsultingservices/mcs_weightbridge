import urllib.request, urllib.parse, json, urllib.error, pickle, os

BASE = 'http://localhost:9001'
RESULTS = []

def api(method, path, data=None, token=None, form=False):
    url = BASE + path
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = None
    if data:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except:
            return e.code, {}
    except Exception as ex:
        return 0, str(ex)

def check(tc, name, cond, status, detail=''):
    result = 'PASS' if cond else 'FAIL'
    RESULTS.append({'tc': tc, 'name': name, 'result': result, 'status': status, 'detail': str(detail)[:150]})
    print(f'  [{result}] {name} | HTTP {status} | {str(detail)[:80]}')

# ── Setup ──────────────────────────────────────────────────────────────────
s, r = api('POST', '/api/v1/auth/login', {'username': 'admin', 'password': 'admin123'}, form=True)
token = r.get('access_token', '')
print(f'Login: {s}, token={bool(token)}')

s, fys = api('GET', '/api/v1/company/financial-years', token=token)
fy_id = None
if isinstance(fys, list) and fys:
    active = [f for f in fys if f.get('is_active')]
    fy_id = active[0]['id'] if active else fys[0]['id']

s, parties_r = api('GET', '/api/v1/parties/?page=1&page_size=5', token=token)
parties = parties_r if isinstance(parties_r, list) else parties_r.get('items', [])
party_id = parties[0]['id'] if parties else None

s, prods_r = api('GET', '/api/v1/products?page=1&page_size=5', token=token)
prods = prods_r if isinstance(prods_r, list) else prods_r.get('items', [])
prod_id = prods[0]['id'] if prods else None
prod_rate = float(prods[0].get('default_rate', 500)) if prods else 500.0

print(f'Context: party={party_id}, prod={prod_id}, fy={fy_id}')

# ── TC-10: QUOTATIONS ──────────────────────────────────────────────────────
print('\n=== TC-10: QUOTATIONS ===')
s, r = api('POST', '/api/v1/quotations/', {
    'party_id': party_id, 'fy_id': fy_id,
    'quotation_date': '2026-03-28', 'valid_until': '2026-04-28',
    'notes': 'Test quotation for Gitti 10mm supply',
    'items': [{'product_id': prod_id, 'quantity': 10, 'rate': prod_rate, 'unit': 'MT'}]
}, token=token)
quot_id = r.get('id') if s in (200, 201) else None
check('TC-10', 'Create quotation', s in (200, 201), s, r.get('quotation_no', '') or r.get('detail', ''))

s, r = api('GET', '/api/v1/quotations/?page=1&page_size=10', token=token)
check('TC-10', 'List quotations', s == 200, s, f'count={len(r.get("items", []))}')

if quot_id:
    s, r = api('GET', f'/api/v1/quotations/{quot_id}', token=token)
    check('TC-10', 'Get quotation by ID', s == 200, s, r.get('quotation_no', ''))

if quot_id:
    url = f'{BASE}/api/v1/quotations/{quot_id}/pdf'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ct = resp.getheader('Content-Type', '')
            check('TC-10', 'Quotation PDF download', resp.status == 200, resp.status, ct)
    except urllib.error.HTTPError as e:
        check('TC-10', 'Quotation PDF download', False, e.code, str(e))

if quot_id:
    s, r = api('POST', f'/api/v1/quotations/{quot_id}/send', token=token)
    check('TC-10', 'Mark quotation as sent', s in (200, 201), s, r.get('status', '') or str(r)[:80])

if quot_id:
    s, r = api('POST', f'/api/v1/quotations/{quot_id}/convert',
               {'invoice_date': '2026-03-28', 'tax_type': 'gst'}, token=token)
    conv_inv_id = r.get('id') if s in (200, 201) else None
    check('TC-10', 'Convert quotation to invoice', s in (200, 201), s, r.get('invoice_no', '') or r.get('detail', '')[:80])

# ── TC-11: PAYMENTS ────────────────────────────────────────────────────────
print('\n=== TC-11: PAYMENTS ===')
# Create a sale invoice and finalise it
s, inv_r = api('POST', '/api/v1/invoices/', {
    'invoice_type': 'sale', 'tax_type': 'gst', 'party_id': party_id,
    'fy_id': fy_id, 'invoice_date': '2026-03-28',
    'items': [{'product_id': prod_id, 'quantity': 50, 'rate': prod_rate, 'unit': 'MT', 'gst_rate': 5.0}]
}, token=token)
inv_id2 = inv_r.get('id') if s in (200, 201) else None
if inv_id2:
    s2, r2 = api('POST', f'/api/v1/invoices/{inv_id2}/finalise', token=token)
    print(f'  Created+finalised invoice: {r2.get("invoice_no", inv_id2)}, status={s2}')

s, r = api('POST', '/api/v1/payments/receipts', {
    'party_id': party_id, 'fy_id': fy_id,
    'receipt_date': '2026-03-28', 'amount': 5000.0,
    'payment_mode': 'cash', 'narration': 'Advance payment for stone supply'
}, token=token)
receipt_id = r.get('id') if s in (200, 201) else None
check('TC-11', 'Create payment receipt', s in (200, 201), s, r.get('receipt_no', '') or r.get('detail', '')[:80])

s, r = api('GET', '/api/v1/payments/receipts?page=1&page_size=10', token=token)
check('TC-11', 'List receipts', s == 200, s, f'count={len(r.get("items", []))}')

s, r = api('POST', '/api/v1/payments/vouchers', {
    'party_id': party_id, 'fy_id': fy_id,
    'voucher_date': '2026-03-28', 'amount': 3000.0,
    'payment_mode': 'bank', 'narration': 'Payment for raw material purchase'
}, token=token)
voucher_id = r.get('id') if s in (200, 201) else None
check('TC-11', 'Create payment voucher', s in (200, 201), s, r.get('voucher_no', '') or r.get('detail', '')[:80])

s, r = api('GET', '/api/v1/payments/vouchers?page=1&page_size=10', token=token)
check('TC-11', 'List vouchers', s == 200, s, f'count={len(r.get("items", []))}')

# ── TC-12: LEDGER & OUTSTANDING ───────────────────────────────────────────
print('\n=== TC-12: LEDGER & OUTSTANDING ===')
s, r = api('GET', f'/api/v1/payments/party-ledger/{party_id}', token=token)
check('TC-12', 'Party ledger (running balance)', s == 200, s,
      f'entries={len(r) if isinstance(r, list) else str(r)[:60]}')

s, r = api('GET', '/api/v1/payments/outstanding', token=token)
check('TC-12', 'Outstanding with ageing', s == 200, s,
      f'keys={list(r.keys())[:4] if isinstance(r, dict) else len(r) if isinstance(r, list) else type(r).__name__}')

# ── TC-13: REPORTS ────────────────────────────────────────────────────────
print('\n=== TC-13: REPORTS ===')
s, r = api('GET', '/api/v1/reports/sales-register?from_date=2026-01-01&to_date=2026-03-28', token=token)
check('TC-13', 'Sales register', s == 200, s,
      f'len={len(r) if isinstance(r, list) else r.get("total", "?")}')

s, r = api('GET', '/api/v1/reports/weight-register?from_date=2026-01-01&to_date=2026-03-28', token=token)
check('TC-13', 'Weight register', s == 200, s,
      f'len={len(r) if isinstance(r, list) else r.get("total", "?")}')

s, r = api('GET', '/api/v1/reports/profit-loss?year=2026', token=token)
check('TC-13', 'Profit & Loss report', s == 200, s,
      f'keys={list(r.keys())[:4] if isinstance(r, dict) else type(r).__name__}')

s, r = api('GET', '/api/v1/reports/stock-summary', token=token)
check('TC-13', 'Stock summary', s == 200, s,
      f'len={len(r) if isinstance(r, list) else r.get("total", "?")}')

# ── TC-14: GST REPORTS ────────────────────────────────────────────────────
print('\n=== TC-14: GST REPORTS ===')
s, r = api('GET', '/api/v1/reports/gstr1?month=3&year=2026', token=token)
check('TC-14', 'GSTR-1 report', s == 200, s,
      f'keys={list(r.keys())[:4] if isinstance(r, dict) else type(r).__name__}')

s, r = api('GET', '/api/v1/reports/gstr1-json?month=3&year=2026', token=token)
check('TC-14', 'GSTR-1 JSON export', s == 200, s,
      f'keys={list(r.keys())[:3] if isinstance(r, dict) else type(r).__name__}')

s, r = api('GET', '/api/v1/reports/gstr3b?month=3&year=2026', token=token)
check('TC-14', 'GSTR-3B report', s == 200, s,
      f'keys={list(r.keys())[:4] if isinstance(r, dict) else type(r).__name__}')

# ── TC-15: NOTIFICATIONS ─────────────────────────────────────────────────
print('\n=== TC-15: NOTIFICATIONS ===')
s, r = api('GET', '/api/v1/notifications/config', token=token)
check('TC-15', 'Get notification config', s == 200, s,
      f'channels={len(r) if isinstance(r, list) else r.get("channel", "?")}')

s, r = api('GET', '/api/v1/notifications/templates', token=token)
check('TC-15', 'List notification templates', s == 200, s,
      f'count={len(r) if isinstance(r, list) else r.get("total", "?")}')

s, r = api('GET', '/api/v1/notifications/log?page=1&page_size=10', token=token)
check('TC-15', 'Notification delivery log', s == 200, s,
      f'total={r.get("total", "?")}')

# ── TC-16: AUDIT TRAIL ────────────────────────────────────────────────────
print('\n=== TC-16: AUDIT TRAIL ===')
s, r = api('GET', '/api/v1/audit/?page=1&page_size=10', token=token)
check('TC-16', 'Audit trail list', s == 200, s,
      f'total={r.get("total", "?")} items={len(r.get("items", []))}')

s, r = api('GET', '/api/v1/audit/stats', token=token)
check('TC-16', 'Audit trail stats', s == 200, s,
      f'keys={list(r.keys())[:4] if isinstance(r, dict) else type(r).__name__}')

s, r = api('GET', '/api/v1/audit/?action=login&page=1&page_size=5', token=token)
check('TC-16', 'Audit filter by action=login', s == 200, s,
      f'items={len(r.get("items", []))}')

# ── TC-17: BACKUP ─────────────────────────────────────────────────────────
print('\n=== TC-17: BACKUP ===')
s, r = api('GET', '/api/v1/backup/list', token=token)
check('TC-17', 'List backups', s == 200, s,
      f'count={len(r) if isinstance(r, list) else "?"}')

s, r = api('POST', '/api/v1/backup/create', token=token)
backup_file = r.get('filename') if s in (200, 201) else None
check('TC-17', 'Create backup (pg_dump)', s in (200, 201), s,
      r.get('filename', '') or r.get('detail', '')[:80])

if backup_file:
    url = f'{BASE}/api/v1/backup/download/{backup_file}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            size = len(resp.read())
            check('TC-17', 'Download backup file', resp.status == 200 and size > 100, resp.status,
                  f'size={size} bytes')
    except urllib.error.HTTPError as e:
        check('TC-17', 'Download backup file', False, e.code, str(e))

# ── TC-18: DATA IMPORT ────────────────────────────────────────────────────
print('\n=== TC-18: DATA IMPORT ===')
for entity in ['parties', 'products', 'vehicles']:
    url = f'{BASE}/api/v1/import/template/{entity}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ct = resp.getheader('Content-Type', '')
            check('TC-18', f'Download {entity} template', resp.status == 200, resp.status, ct)
    except urllib.error.HTTPError as e:
        check('TC-18', f'Download {entity} template', False, e.code, str(e))

# ── TC-19: SETTINGS ───────────────────────────────────────────────────────
print('\n=== TC-19: SETTINGS ===')
s, company = api('GET', '/api/v1/company/', token=token)
check('TC-19', 'Get company settings', s == 200, s, company.get('name', ''))

update_payload = {
    'name': company.get('name', 'Stone Crusher Enterprises'),
    'address': company.get('address') or 'NH-48, Industrial Area, Rajasthan - 302001',
    'state_code': company.get('state_code') or '08',
    'invoice_prefix_sale': company.get('invoice_prefix_sale') or 'INV',
    'invoice_prefix_purchase': company.get('invoice_prefix_purchase') or 'PINV',
}
if company.get('gstin'):
    update_payload['gstin'] = company['gstin']
s, r = api('PUT', '/api/v1/company/', update_payload, token=token)
check('TC-19', 'Update company settings', s == 200, s,
      r.get('name', '') or r.get('detail', '')[:80])

s, r = api('GET', '/api/v1/company/financial-years', token=token)
check('TC-19', 'List financial years', s == 200, s,
      f'count={len(r) if isinstance(r, list) else "?"}')

# ── TC-20: WEIGHT SCALE ───────────────────────────────────────────────────
print('\n=== TC-20: WEIGHT SCALE ===')
s, r = api('GET', '/api/v1/weight/status', token=token)
check('TC-20', 'Weight scale status', s == 200, s,
      f'connected={r.get("connected", r.get("is_connected", "?"))}')

s, r = api('GET', '/api/v1/weight/config', token=token)
check('TC-20', 'Weight scale config GET', s == 200, s,
      f'port={r.get("port_name", r.get("port", "?"))}')

# ── DASHBOARD ─────────────────────────────────────────────────────────────
print('\n=== TC-21: DASHBOARD ===')
s, r = api('GET', '/api/v1/dashboard/summary', token=token)
check('TC-21', 'Dashboard summary', s == 200, s,
      f'keys={list(r.keys())[:5] if isinstance(r, dict) else type(r).__name__}')

# ── SUMMARY ───────────────────────────────────────────────────────────────
print('\n' + '='*60)
passes = sum(1 for x in RESULTS if x['result'] == 'PASS')
fails = sum(1 for x in RESULTS if x['result'] == 'FAIL')
print(f'Phase 2 Results: {passes} PASS / {fails} FAIL / {len(RESULTS)} total')
print()
for x in RESULTS:
    if x['result'] == 'FAIL':
        print(f'  FAIL: [{x["tc"]}] {x["name"]} | HTTP {x["status"]} | {x["detail"]}')

# Save for Excel
with open(r'C:\Users\Admin\Documents\workspace_Weighbridge\test_results_phase2.pkl', 'wb') as f:
    pickle.dump(RESULTS, f)
print('\nSaved to test_results_phase2.pkl')
