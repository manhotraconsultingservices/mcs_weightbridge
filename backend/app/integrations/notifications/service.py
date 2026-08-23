"""Unified notification service — render template + dispatch via channel + log."""
from __future__ import annotations
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from jinja2 import Environment, BaseLoader, Undefined, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, update

from app.models.notification import (
    NotificationConfig,
    NotificationTemplate,
    NotificationLog,
    NotificationRecipient,
)

logger = logging.getLogger(__name__)

# Scrub bot tokens / bearer secrets from any error string before it is logged or
# persisted to notification_log.error_message (secret hygiene — a raw httpx error
# from Telegram would otherwise embed the full bot token in the request URL).
import re as _re
_BOT_TOKEN_RE = _re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}")
_BEARER_RE = _re.compile(r"(?i)(bearer|token|api[_-]?key)[=:\s]+[A-Za-z0-9._-]{12,}")


def _redact_secrets(msg: str | None) -> str:
    s = msg or ""
    s = _BOT_TOKEN_RE.sub("bot<redacted>", s)
    s = _BEARER_RE.sub(r"\1 <redacted>", s)
    return s


# ── Jinja2 sandbox ────────────────────────────────────────────────────────────
# Use Undefined (base class) — missing vars render as empty string in str context,
# which is fine for notification templates.

_jinja = Environment(
    loader=BaseLoader(),
    autoescape=select_autoescape(["html"]),
    undefined=Undefined,
)


def render_template(template_str: str, context: dict[str, Any]) -> str:
    try:
        tmpl = _jinja.from_string(template_str)
        return tmpl.render(**context)
    except Exception as e:
        logger.warning("Template render error: %s", e)
        return template_str


# ── Default seed templates ─────────────────────────────────────────────────────

DEFAULT_TEMPLATES = [
    {
        "event_type": "invoice_finalized",
        "channel": "email",
        "name": "Invoice Finalized (Email)",
        "subject": "Invoice {{ invoice_no }} from {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>Your invoice <strong>{{ invoice_no }}</strong> dated {{ invoice_date }} has been generated.</p>
<p><strong>Amount: ₹{{ grand_total }}</strong></p>
<p>Thank you for your business.</p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "invoice_finalized",
        "channel": "sms",
        "name": "Invoice Finalized (SMS)",
        "subject": None,
        "body": "Dear {{ party_name }}, Invoice {{ invoice_no }} of Rs.{{ grand_total }} generated on {{ invoice_date }}. Thank you. - {{ company_name }}",
    },
    {
        "event_type": "invoice_finalized",
        "channel": "whatsapp",
        "name": "Invoice Finalized (WhatsApp)",
        "subject": None,
        "body": "Dear {{ party_name }},\n\nInvoice *{{ invoice_no }}* dated {{ invoice_date }}\nAmount: *₹{{ grand_total }}*\n\nThank you! - {{ company_name }}",
    },
    {
        "event_type": "invoice_finalized",
        "channel": "telegram",
        "name": "Invoice Finalized (Telegram)",
        "subject": None,
        "body": "📄 <b>Invoice Finalized</b>\n\nParty: {{ party_name }}\nInvoice: <b>{{ invoice_no }}</b>\nDate: {{ invoice_date }}\nMaterial: {{ material }}\nQty: <b>{{ qty }}</b>\n{% if taxable_amount %}Taxable: ₹{{ taxable_amount }}\n{% endif %}{% if tax_amount and tax_amount != '0.00' %}GST: ₹{{ tax_amount }}\n{% endif %}{% if freight %}Freight: ₹{{ freight }}\n{% endif %}{% if royalty %}Royalty: ₹{{ royalty }}\n{% endif %}{% if vehicle_rent %}Vehicle Rent: ₹{{ vehicle_rent }}\n{% endif %}Amount: <b>₹{{ grand_total }}</b>\n{% if changes %}\n<b>Changed from draft:</b>\n{{ changes }}\n{% endif %}{% if finalized_by %}Finalized by: {{ finalized_by }}\n{% endif %}\n— {{ company_name }}",
    },
    {
        "event_type": "approval_requested",
        "channel": "telegram",
        "name": "Approval Requested (Telegram)",
        "subject": None,
        "body": "🔐 <b>Approval needed</b>\n\n{{ action }}\n{{ title }}\n{% if amount %}Amount: <b>₹{{ amount }}</b>\n{% endif %}Requested by: {{ requested_by }}\n\nA second admin must approve it in the app → Approvals.",
    },
    {
        "event_type": "approval_decided",
        "channel": "telegram",
        "name": "Approval Decided (Telegram)",
        "subject": None,
        "body": "🔐 <b>Approval {{ decision }}</b>\n\n{{ action }}\n{{ title }}\nBy: {{ decided_by }}",
    },
    {
        "event_type": "operator_cash_count_missing",
        "channel": "telegram",
        "name": "Operator Cash Count Missing (Telegram)",
        "subject": None,
        "body": "💰 <b>Cash count not recorded</b> ({{ date }})\n\n{{ missing_count }} operator(s) collected cash today but haven't counted their drawer:\n{{ operator_list }}\n\nUncounted cash: <b>₹{{ total_uncounted }}</b>\nAsk them to record the count in Reports → Operator Cash.",
    },
    {
        "event_type": "invoice_revised",
        "channel": "email",
        "name": "Invoice Revised (Email)",
        "subject": "Invoice {{ invoice_no }} (Revision {{ revision_no }}) - {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>Invoice <strong>{{ invoice_no }}</strong> has been revised (Revision {{ revision_no }}) on {{ invoice_date }}.</p>
<p><strong>Revised Amount: ₹{{ grand_total }}</strong></p>
<p>Please review the updated invoice.</p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "invoice_revised",
        "channel": "sms",
        "name": "Invoice Revised (SMS)",
        "subject": None,
        "body": "Dear {{ party_name }}, Invoice {{ invoice_no }} has been revised (Rv{{ revision_no }}). Updated amount: Rs.{{ grand_total }}. - {{ company_name }}",
    },
    {
        "event_type": "invoice_revised",
        "channel": "telegram",
        "name": "Invoice Revised (Telegram)",
        "subject": None,
        "body": "✏️ <b>Invoice Revised</b> (Rv{{ revision_no }})\n\nParty: {{ party_name }}\nInvoice: <b>{{ invoice_no }}</b>\nDate: {{ invoice_date }}\n{% if royalty %}Royalty: ₹{{ royalty }}\n{% endif %}{% if vehicle_rent %}Vehicle Rent: ₹{{ vehicle_rent }}\n{% endif %}Revised Amount: <b>₹{{ grand_total }}</b>\n{% if changes %}\n<b>What changed:</b>\n{{ changes }}\n{% endif %}{% if remark %}Remark: {{ remark }}\n{% endif %}{% if finalized_by %}Revised by: {{ finalized_by }}\n{% endif %}\n— {{ company_name }}",
    },
    {
        "event_type": "payment_received",
        "channel": "email",
        "name": "Payment Received (Email)",
        "subject": "Payment Receipt {{ receipt_no }} - {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>We have received your payment of <strong>₹{{ amount }}</strong> on {{ receipt_date }}.</p>
<p>Receipt No: {{ receipt_no }}</p>
<p>Thank you.</p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "payment_received",
        "channel": "sms",
        "name": "Payment Received (SMS)",
        "subject": None,
        "body": "Dear {{ party_name }}, payment of Rs.{{ amount }} received on {{ receipt_date }}. Receipt: {{ receipt_no }}. - {{ company_name }}",
    },
    {
        "event_type": "payment_received",
        "channel": "telegram",
        "name": "Payment Received (Telegram)",
        "subject": None,
        "body": "💰 <b>Payment Received</b>\n\nParty: {{ party_name }}\nReceipt: <b>{{ receipt_no }}</b>\nAmount: <b>₹{{ amount }}</b>\nDate: {{ receipt_date }}\n\n— {{ company_name }}",
    },
    {
        "event_type": "quotation_sent",
        "channel": "email",
        "name": "Quotation Sent (Email)",
        "subject": "Quotation {{ quotation_no }} from {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>Please find attached your quotation <strong>{{ quotation_no }}</strong> valid till {{ valid_to }}.</p>
<p>Total: <strong>₹{{ grand_total }}</strong></p>
<p>Regards,<br>{{ company_name }}</p>""",
    },
    {
        "event_type": "token_completed",
        "channel": "sms",
        "name": "Weighment Complete (SMS)",
        "subject": None,
        "body": "Token #{{ token_no }}: Vehicle {{ vehicle_no }}, Net Wt {{ net_weight }} MT completed at {{ completed_at }}. - {{ company_name }}",
    },
    {
        "event_type": "token_completed",
        "channel": "telegram",
        "name": "Weighment Complete (Telegram)",
        "subject": None,
        "body": "⚖️ <b>Weighment Completed</b>\n\nToken: <b>#{{ token_no }}</b>\n{% if token_type %}Type: <b>{{ token_type }}</b>\n{% endif %}Vehicle: {{ vehicle_no }}\nParty: {{ party_name }}\nMaterial: {{ material }}\nQty: <b>{{ qty }}</b>\n{% if rate %}Rate: ₹{{ rate }}\n{% endif %}{% if royalty %}Royalty: ₹{{ royalty }}\n{% endif %}{% if vehicle_rent %}Vehicle Rent: ₹{{ vehicle_rent }}\n{% endif %}Amount: <b>₹{{ amount }}</b>\nCompleted: {{ completed_at }}\n{% if created_by %}Created by: {{ created_by }}\n{% endif %}\n— {{ company_name }}",
    },
    {
        "event_type": "low_product_stock",
        "channel": "telegram",
        "name": "Low Product Stock Alert (Telegram)",
        "subject": None,
        "body": "⚠️ <b>Low Stock Alert</b>\n\n<b>{{ product_name }}</b> is at <b>{{ current_stock }} {{ unit }}</b> (min: {{ min_stock_level }} {{ unit }}).\n\nConsider replenishing — {{ status }}.\n\n— {{ company_name }}",
    },
    # ── Fleet fuel: possible diesel leakage (mileage below benchmark) ─────────
    {
        "event_type": "fuel_leakage_alert",
        "channel": "telegram",
        "name": "Diesel Leakage Alert (Telegram)",
        "subject": None,
        "body": "🛢️ <b>Possible Diesel Leakage</b>\n\nVehicle: <b>{{ vehicle_no }}</b>\nMileage: <b>{{ actual_kmpl }} km/l</b> (benchmark {{ benchmark_kmpl }} km/l)\nDeviation: <b>{{ deviation_pct }}% below</b>\nLast fill: {{ litres }} L over {{ distance_km }} km\n\nCheck the vehicle for leakage, theft, or servicing.",
    },
    {
        "event_type": "fuel_leakage_alert",
        "channel": "whatsapp",
        "name": "Diesel Leakage Alert (WhatsApp)",
        "subject": None,
        "body": "*Possible Diesel Leakage*\n\nVehicle {{ vehicle_no }} ran at {{ actual_kmpl }} km/l vs benchmark {{ benchmark_kmpl }} km/l ({{ deviation_pct }}% below) on the last fill ({{ litres }} L / {{ distance_km }} km).\n\nPlease check for leakage or theft.",
    },
    {
        "event_type": "fuel_leakage_alert",
        "channel": "sms",
        "name": "Diesel Leakage Alert (SMS)",
        "subject": None,
        "body": "ALERT: {{ vehicle_no }} mileage {{ actual_kmpl }} km/l vs benchmark {{ benchmark_kmpl }} ({{ deviation_pct }}% low). Possible diesel leakage - please check.",
    },
    {
        "event_type": "fuel_pump_outstanding_alert",
        "channel": "telegram",
        "name": "Petrol Pump Outstanding Alert (Telegram)",
        "subject": None,
        "body": "⛽ <b>Petrol pump dues crossed the limit</b>\n\nPump: <b>{{ station }}</b>\nOutstanding: <b>₹{{ outstanding }}</b> (limit ₹{{ threshold }})\n{% if po_no %}Latest PO: {{ po_no }} ({{ vehicle_no }})\n{% endif %}\nSettle the pump to keep credit open.\n\n— {{ company_name }}",
    },
    # ── Sprint 2: overdue payment reminders (one-tap from owner dashboard) ──
    {
        "event_type": "payment_overdue_reminder",
        "channel": "whatsapp",
        "name": "Payment Overdue Reminder (WhatsApp)",
        "subject": None,
        "body": "Dear {{ party_name }},\n\nThis is a gentle reminder that *₹{{ balance }}* is outstanding on your account ({{ oldest_overdue_days }} days past due).\n\nKindly arrange payment at your earliest convenience.\n\nThank you,\n{{ company_name }}",
    },
    {
        "event_type": "payment_overdue_reminder",
        "channel": "sms",
        "name": "Payment Overdue Reminder (SMS)",
        "subject": None,
        "body": "Dear {{ party_name }}, Rs.{{ balance }} is overdue on your account ({{ oldest_overdue_days }} days). Please arrange payment. - {{ company_name }}",
    },
    {
        "event_type": "payment_overdue_reminder",
        "channel": "email",
        "name": "Payment Overdue Reminder (Email)",
        "subject": "Payment Reminder - ₹{{ balance }} overdue - {{ company_name }}",
        "body": """<p>Dear {{ party_name }},</p>
<p>This is a gentle reminder that <strong>₹{{ balance }}</strong> is outstanding on your account ({{ oldest_overdue_days }} days past due).</p>
<p>Kindly arrange payment at your earliest convenience. If you have already paid, please share the payment details with us.</p>
<p>Thank you,<br>{{ company_name }}</p>""",
    },
    # ── Sprint 2: 8 PM owner Telegram digest ─────────────────────────────────
    {
        "event_type": "owner_digest",
        "channel": "telegram",
        "name": "Daily Owner Digest (Telegram)",
        "subject": None,
        "body": (
            "📊 <b>Daily Brief — {{ date }}</b>\n\n"
            "<b>Today:</b>\n"
            "• {{ tokens_today }} trucks · {{ tonnage_today }} MT\n"
            "• Sales: ₹{{ revenue_today }}\n"
            "• Collected: ₹{{ collected_today }}\n\n"
            "<b>Status:</b> {{ status_emoji }} {{ status_headline }}\n\n"
            "{% if overdue_count > 0 %}🔴 {{ overdue_count }} customer(s) overdue (₹{{ overdue_total }})\n{% endif %}"
            "{% if low_stock_count > 0 %}🟡 {{ low_stock_count }} product(s) low stock\n{% endif %}"
            "{% if compliance_count > 0 %}🟡 {{ compliance_count }} compliance expiring\n{% endif %}"
            "{% if yield_variance %}{{ yield_emoji }} Yield: {{ yield_pct }}% (target {{ target_yield_pct }}%)\n{% endif %}"
            "\n— {{ company_name }}"
        ),
    },
    # ── ANPR (gate-camera detections) ────────────────────────────────────────
    {
        "event_type": "anpr_entry",
        "channel": "telegram",
        "name": "Vehicle Entry (Telegram)",
        "subject": None,
        "body": (
            "🚛 <b>Vehicle Entered</b>\n\n"
            "Plate: <b>{{ vehicle_no }}</b>\n"
            "Gate Pass: <code>{{ gate_pass_no }}</code>\n"
            "Time: {{ entry_time }}\n"
            "{% if vehicle_known == 'no' %}⚠️ Unknown plate — awaiting review.\n{% endif %}"
        ),
    },
    {
        "event_type": "anpr_exit",
        "channel": "telegram",
        "name": "Vehicle Exit (Telegram)",
        "subject": None,
        "body": (
            "🏁 <b>Vehicle Left</b>\n\n"
            "Plate: <b>{{ vehicle_no }}</b>\n"
            "Gate Pass: <code>{{ gate_pass_no }}</code>\n"
            "Token: #{{ token_no }}\n"
            "Net: <b>{{ net_weight }} MT</b>\n"
            "Time: {{ exit_time }}\n"
            "Dwell: <b>{{ dwell_minutes }} min</b>"
        ),
    },
    {
        "event_type": "anpr_unknown_plate",
        "channel": "telegram",
        "name": "Unknown Plate Detected (Telegram)",
        "subject": None,
        "body": (
            "❓ <b>Unknown plate detected</b>\n\n"
            "Plate: <b>{{ plate }}</b>\n"
            "Time: {{ captured_at }}\n"
            "Awaiting review in /anpr/review."
        ),
    },
    {
        "event_type": "anpr_camera_down",
        "channel": "telegram",
        "name": "ANPR Camera Offline (Telegram)",
        "subject": None,
        "body": (
            "⚠️ <b>ANPR camera offline</b>\n\n"
            "Camera <b>{{ camera_id }}</b> has not delivered a frame for {{ down_minutes }} minutes.\n"
            "Please check the bridge/gate camera.\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "anpr_daily_summary",
        "channel": "telegram",
        "name": "Daily Gate Camera Report (Telegram)",
        "subject": None,
        "body": (
            "🚛 <b>Daily Weighment Summary — {{ date }}</b>\n\n"
            "{% if has_movement %}<b>Gate traffic:</b>\n"
            "• Entries: <b>{{ entries }}</b>\n"
            "• Exits: <b>{{ exits }}</b>\n"
            "• Currently inside: <b>{{ currently_inside }}</b>\n"
            "• Avg dwell: <b>{{ avg_dwell }} min</b>\n{% endif %}"
            "• Total tonnage: <b>{{ tonnage_mt }} MT</b>\n"
            "• Total revenue: <b>₹{{ revenue }}</b>\n\n"
            "{% if trip_count > 0 %}<b>Trips ({{ trip_count }}):</b>\n{{ trip_list }}\n{% else %}No trips recorded today.\n{% endif %}"
            "— {{ company_name }}"
        ),
    },
    # ── Device health (camera / scale watchdog) ───────────────────────────────
    {
        "event_type": "device_down",
        "channel": "telegram",
        "name": "Device Offline (Telegram)",
        "subject": None,
        "body": (
            "🔴 <b>{{ device_type|capitalize }} offline</b>\n\n"
            "Device: <b>{{ device_label }}</b>\n"
            "{% if site and site != '-' %}Site: {{ site }}\n{% endif %}"
            "Down for: <b>{{ down_minutes }} min</b>\n"
            "Reason: {{ reason }}\n\n"
            "Please check the device / its PC.\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "device_recovered",
        "channel": "telegram",
        "name": "Device Back Online (Telegram)",
        "subject": None,
        "body": (
            "🟢 <b>{{ device_type|capitalize }} back online</b>\n\n"
            "Device: <b>{{ device_label }}</b>\n"
            "{% if site and site != '-' %}Site: {{ site }}\n{% endif %}"
            "Recovered and reporting normally.\n— {{ company_name }}"
        ),
    },
    # ── Royalty / Transit-pass reconciliation alert ───────────────────────────
    {
        "event_type": "royalty_unaccounted_alert",
        "channel": "telegram",
        "name": "Royalty Unaccounted MT Alert (Telegram)",
        "subject": None,
        "body": (
            "⚠️ <b>Royalty Reconciliation Alert</b>\n\n"
            "Unaccounted material has exceeded the configured threshold.\n\n"
            "📅 Date: <b>{{ date }}</b>\n"
            "🚛 Inbound today (MT): <b>{{ inbound_mt }}</b>\n"
            "✅ Covered by passes (MT): <b>{{ consumed_mt }}</b>\n"
            "❌ Unaccounted (MT): <b>{{ unaccounted_mt }}</b>\n"
            "🎯 Alert threshold: <b>{{ threshold_mt }} MT</b>\n\n"
            "Please link transit passes to the inbound tokens or obtain additional passes from the portal.\n\n"
            "— {{ company_name }}"
        ),
    },
    # ── Government dues (royalty + GST owed) ─────────────────────────────────
    {
        "event_type": "statutory_dues_summary",
        "channel": "telegram",
        "name": "Government Dues Summary (Telegram)",
        "subject": None,
        "body": "🏛️ <b>Government Dues</b>\n\nAs on {{ as_of }}\n\nRoyalty due: <b>₹{{ royalty_due }}</b>\nGST due: <b>₹{{ gst_due }}</b>\n\nTotal owed: <b>₹{{ total_due }}</b>\n\nBased on finalised bills only, less payments already recorded.\n\n— {{ company_name }}",
    },
    # ── EOD Daily Business Summary (day book) ────────────────────────────────
    {
        "event_type": "eod_summary",
        "channel": "telegram",
        "name": "EOD Daily Summary (Telegram)",
        "subject": None,
        "body": (
            "📒 <b>Day Book — {{ date }}</b>\n\n"
            "<b>Sales (tokens today)</b>\n"
            "• {{ token_sales_count }} trucks · <b>₹{{ token_sales }}</b>\n\n"
            "<b>Purchases (tokens today)</b>\n"
            "• {{ token_purchase_count }} trucks · <b>₹{{ token_purchase }}</b>\n\n"
            "<b>Expenses Out</b>\n"
            "• Store / Inventory: ₹{{ store_inventory }}\n"
            "• Diesel: ₹{{ diesel }}\n"
            "• Salary / Wages: ₹{{ salary }}\n"
            "• Advances: ₹{{ advance }}\n"
            "• Commission: ₹{{ commission }}\n"
            "• <b>Total expenses: ₹{{ other_expenses }}</b>\n\n"
            "<b>Collected In (money received)</b>\n"
            "• Cash: ₹{{ cash_sales }}\n"
            "• Bank / Card / UPI: ₹{{ electronic_sales }}\n\n"
            "<b>Not yet finalized</b>\n"
            "• Sales: {{ draft_sales_count }} bills · ₹{{ draft_sales }}\n"
            "• Purchase: {{ draft_purchase_count }} bills · ₹{{ draft_purchase }}\n\n"
            "{{ net_business_emoji }} <b>Net (Sales − Purchases − Expenses): ₹{{ net_business }}</b>\n\n"
            "— {{ company_name }}"
        ),
    },
    {
        "event_type": "eod_summary",
        "channel": "email",
        "name": "EOD Daily Summary (Email)",
        "subject": "Day Book — {{ date }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Day Book — {{ date }}</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;min-width:320px;">
  <tr style="background:#f1f5f9;"><th colspan="2" align="left">Sales In</th></tr>
  <tr><td>Cash</td><td align="right">&#8377;{{ cash_sales }}</td></tr>
  <tr><td>Bank / Card / UPI</td><td align="right">&#8377;{{ electronic_sales }}</td></tr>
  <tr style="border-top:1px solid #cbd5e1;"><td><b>Total Sales</b></td><td align="right"><b>&#8377;{{ total_sales }}</b></td></tr>
  <tr style="background:#f1f5f9;"><th colspan="2" align="left">Expenses Out</th></tr>
  <tr><td>Purchases</td><td align="right">&#8377;{{ purchases }}</td></tr>
  <tr><td>Store / Inventory</td><td align="right">&#8377;{{ store_inventory }}</td></tr>
  <tr><td>Diesel</td><td align="right">&#8377;{{ diesel }}</td></tr>
  <tr><td>Salary / Wages</td><td align="right">&#8377;{{ salary }}</td></tr>
  <tr><td>Advances</td><td align="right">&#8377;{{ advance }}</td></tr>
  <tr><td>Commission</td><td align="right">&#8377;{{ commission }}</td></tr>
  <tr style="border-top:1px solid #cbd5e1;"><td><b>Total Expenses</b></td><td align="right"><b>&#8377;{{ total_expenses }}</b></td></tr>
  <tr style="border-top:2px solid #334155;background:#f8fafc;"><td><b>Net (Sales &minus; Expenses)</b></td><td align="right"><b>&#8377;{{ net }}</b></td></tr>
</table>
<p style="margin-top:10px;color:#888;font-size:12px;">Sales = money collected today (cash vs electronic). Expenses include advances paid out.</p>""",
    },

    # ── Email variants for the owner/operational alerts (Telegram-only before) ──
    {
        "event_type": "device_down",
        "channel": "email",
        "name": "Device Offline (Email)",
        "subject": "ALERT: {{ device_label }} offline — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;color:#b91c1c;">Device offline</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Device</b></td><td>{{ device_label }} ({{ device_type }})</td></tr>
  <tr><td><b>Site</b></td><td>{{ site }}</td></tr>
  <tr><td><b>Down for</b></td><td>{{ down_minutes }} min</td></tr>
  <tr><td><b>Reason</b></td><td>{{ reason }}</td></tr>
</table>
<p style="margin-top:10px;color:#555;">Please check the device or its PC.</p>""",
    },
    {
        "event_type": "device_recovered",
        "channel": "email",
        "name": "Device Back Online (Email)",
        "subject": "Resolved: {{ device_label }} back online — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;color:#15803d;">Device back online</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Device</b></td><td>{{ device_label }} ({{ device_type }})</td></tr>
  <tr><td><b>Site</b></td><td>{{ site }}</td></tr>
</table>
<p style="margin-top:10px;color:#555;">Recovered and reporting normally.</p>""",
    },
    {
        "event_type": "low_product_stock",
        "channel": "email",
        "name": "Low Product Stock (Email)",
        "subject": "Low stock: {{ product_name }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;color:#b45309;">Low product stock</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Product</b></td><td>{{ product_name }}</td></tr>
  <tr><td><b>Current stock</b></td><td>{{ current_stock }} {{ unit }}</td></tr>
  <tr><td><b>Minimum level</b></td><td>{{ min_stock_level }} {{ unit }}</td></tr>
  <tr><td><b>Status</b></td><td>{{ status }}</td></tr>
</table>""",
    },
    {
        "event_type": "fuel_leakage_alert",
        "channel": "email",
        "name": "Fuel Leakage Alert (Email)",
        "subject": "Fuel leakage / low mileage — {{ vehicle_no }}",
        "body": """<h2 style="margin:0 0 4px;color:#b91c1c;">Possible fuel leakage / low mileage</h2>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Vehicle</b></td><td>{{ vehicle_no }}</td></tr>
  <tr><td><b>Actual mileage</b></td><td>{{ actual_kmpl }} km/l</td></tr>
  <tr><td><b>Benchmark</b></td><td>{{ benchmark_kmpl }} km/l</td></tr>
  <tr><td><b>Deviation</b></td><td>{{ deviation_pct }}%</td></tr>
  <tr><td><b>Fuel filled</b></td><td>{{ litres }} L over {{ distance_km }} km</td></tr>
</table>""",
    },
    {
        "event_type": "owner_digest",
        "channel": "email",
        "name": "Daily Owner Digest (Email)",
        "subject": "Daily summary — {{ date }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Daily summary — {{ date }}</h2>
<p style="margin:0 0 8px;color:#555;">{{ company_name }}</p>
<p style="margin:0 0 12px;"><b>{{ status_headline }}</b></p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;min-width:320px;">
  <tr><td>Tokens today</td><td align="right">{{ tokens_today }}</td></tr>
  <tr><td>Tonnage</td><td align="right">{{ tonnage_today }} MT</td></tr>
  <tr><td>Revenue</td><td align="right">&#8377;{{ revenue_today }}</td></tr>
  <tr><td>Collected</td><td align="right">&#8377;{{ collected_today }}</td></tr>
  <tr><td>Overdue customers</td><td align="right">{{ overdue_count }} (&#8377;{{ overdue_total }})</td></tr>
  <tr><td>Low-stock products</td><td align="right">{{ low_stock_count }}</td></tr>
  <tr><td>Compliance due</td><td align="right">{{ compliance_count }}</td></tr>
  <tr><td>Yield</td><td align="right">{{ yield_pct }}% (target {{ target_yield_pct }}%)</td></tr>
</table>""",
    },
    {
        "event_type": "royalty_unaccounted_alert",
        "channel": "email",
        "name": "Royalty Unaccounted Alert (Email)",
        "subject": "Royalty unaccounted — {{ date }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;color:#b45309;">Royalty reconciliation alert</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td>Date</td><td align="right">{{ date }}</td></tr>
  <tr><td>Inbound (MT)</td><td align="right">{{ inbound_mt }}</td></tr>
  <tr><td>Consumed vs passes (MT)</td><td align="right">{{ consumed_mt }}</td></tr>
  <tr style="border-top:1px solid #cbd5e1;"><td><b>Unaccounted (MT)</b></td><td align="right"><b>{{ unaccounted_mt }}</b></td></tr>
  <tr><td>Threshold (MT)</td><td align="right">{{ threshold_mt }}</td></tr>
</table>""",
    },
    {
        "event_type": "anpr_camera_down",
        "channel": "email",
        "name": "ANPR Camera Offline (Email)",
        "subject": "ANPR camera offline — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;color:#b91c1c;">ANPR camera offline</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<p>Camera <b>{{ camera_id }}</b> has not delivered a frame for {{ down_minutes }} minutes. Please check the gate camera.</p>""",
    },
    {
        "event_type": "anpr_daily_summary",
        "channel": "email",
        "name": "Daily Weighment Summary (Email)",
        "subject": "Daily summary — {{ date }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Daily weighment summary — {{ date }}</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;min-width:300px;">
  {% if has_movement %}<tr><td>Entries</td><td align="right">{{ entries }}</td></tr>
  <tr><td>Exits</td><td align="right">{{ exits }}</td></tr>
  <tr><td>Currently inside</td><td align="right">{{ currently_inside }}</td></tr>
  <tr><td>Avg dwell</td><td align="right">{{ avg_dwell }} min</td></tr>{% endif %}
  <tr><td>Total tonnage</td><td align="right">{{ tonnage_mt }} MT</td></tr>
  <tr><td>Total revenue</td><td align="right">&#8377;{{ revenue }}</td></tr>
</table>
<p style="margin-top:10px;color:#888;font-size:12px;">{{ trip_count }} trip(s) recorded today.</p>""",
    },

    # ── Gate pass created (vehicle entry via the manual Gate Register) ─────────
    {
        "event_type": "gate_pass_created",
        "channel": "telegram",
        "name": "Gate Pass Created (Telegram)",
        "subject": None,
        "body": (
            "🚧 <b>Gate pass created</b>\n\n"
            "Pass: <b>{{ gate_pass_no }}</b>\n"
            "Vehicle: <b>{{ vehicle_no }}</b>\n"
            "{% if driver_name %}Driver: {{ driver_name }}\n{% endif %}"
            "{% if material %}Material: {{ material }}\n{% endif %}"
            "Purpose: {{ purpose }}\n"
            "Entry: {{ entry_time }}\n"
            "{% if entered_by %}Vehicle entered by: <b>{{ entered_by }}</b>\n{% endif %}"
            "\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "gate_pass_created",
        "channel": "email",
        "name": "Gate Pass Created (Email)",
        "subject": "Gate pass {{ gate_pass_no }} — {{ vehicle_no }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Gate pass created</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Pass no</b></td><td>{{ gate_pass_no }}</td></tr>
  <tr><td><b>Vehicle</b></td><td>{{ vehicle_no }}</td></tr>
  <tr><td><b>Driver</b></td><td>{{ driver_name }}</td></tr>
  <tr><td><b>Material</b></td><td>{{ material }}</td></tr>
  <tr><td><b>Purpose</b></td><td>{{ purpose }}</td></tr>
  <tr><td><b>Entry</b></td><td>{{ entry_time }}</td></tr>
  {% if entered_by %}<tr><td><b>Vehicle entered by</b></td><td>{{ entered_by }}</td></tr>{% endif %}
</table>""",
    },

    # ── Store inventory transaction (issue / adjustment / receipt) ────────────
    {
        "event_type": "inventory_transaction",
        "channel": "telegram",
        "name": "Store Inventory Transaction (Telegram)",
        "subject": None,
        "body": (
            "📦 <b>Store: {{ transaction_type }}</b>\n\n"
            "Item: <b>{{ item_name }}</b>\n"
            "Qty: <b>{{ quantity }} {{ unit }}</b>\n"
            "Balance: <b>{{ stock_after }} {{ unit }}</b>\n"
            "{% if reference_no %}Ref: {{ reference_no }}\n{% endif %}"
            "{% if notes %}Note: {{ notes }}\n{% endif %}"
            "By: {{ done_by }}\n\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "inventory_transaction",
        "channel": "email",
        "name": "Store Inventory Transaction (Email)",
        "subject": "Store {{ transaction_type }}: {{ item_name }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Store inventory — {{ transaction_type }}</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Item</b></td><td>{{ item_name }}</td></tr>
  <tr><td><b>Type</b></td><td>{{ transaction_type }}</td></tr>
  <tr><td><b>Quantity</b></td><td>{{ quantity }} {{ unit }}</td></tr>
  <tr><td><b>Balance after</b></td><td>{{ stock_after }} {{ unit }}</td></tr>
  <tr><td><b>Reference</b></td><td>{{ reference_no }}</td></tr>
  <tr><td><b>Note</b></td><td>{{ notes }}</td></tr>
  <tr><td><b>By</b></td><td>{{ done_by }}</td></tr>
</table>""",
    },

    # ── Gate pass exit ────────────────────────────────────────────────────────
    {
        "event_type": "gate_pass_exit",
        "channel": "telegram",
        "name": "Gate Pass Exit (Telegram)",
        "subject": None,
        "body": (
            "🚪 <b>Gate pass exit</b>\n\n"
            "Pass: <b>{{ gate_pass_no }}</b>\n"
            "Vehicle: <b>{{ vehicle_no }}</b>\n"
            "{% if entry_time %}Entry: {{ entry_time }}\n{% endif %}"
            "{% if entered_by %}Vehicle entered by: <b>{{ entered_by }}</b>\n{% endif %}"
            "Exit: {{ exit_time }}\n"
            "{% if exited_by %}Vehicle exit by: <b>{{ exited_by }}</b>\n{% endif %}"
            "\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "gate_pass_exit",
        "channel": "email",
        "name": "Gate Pass Exit (Email)",
        "subject": "Gate exit {{ gate_pass_no }} — {{ vehicle_no }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Gate pass exit</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Pass no</b></td><td>{{ gate_pass_no }}</td></tr>
  <tr><td><b>Vehicle</b></td><td>{{ vehicle_no }}</td></tr>
  <tr><td><b>Entry</b></td><td>{{ entry_time }}</td></tr>
  <tr><td><b>Vehicle entered by</b></td><td>{{ entered_by }}</td></tr>
  <tr><td><b>Exit</b></td><td>{{ exit_time }}</td></tr>
  <tr><td><b>Vehicle exit by</b></td><td>{{ exited_by }}</td></tr>
</table>""",
    },

    # ── Vehicle In / Out (weighbridge token movement — truck arrival + departure) ─
    {
        "event_type": "vehicle_in",
        "channel": "telegram",
        "name": "Vehicle In (Telegram)",
        "subject": None,
        "body": (
            "🚛 <b>Vehicle In</b>\n\n"
            "Vehicle: <b>{{ vehicle_no }}</b>\n"
            "{% if gate_pass_no %}Gate Pass: {{ gate_pass_no }}\n{% endif %}"
            "{% if token_type %}Type: {{ token_type }}\n{% endif %}"
            "Party: {{ party_name }}\n"
            "Material: {{ material }}\n"
            "In: {{ time }}\n"
            "{% if entered_by %}Vehicle entered by: <b>{{ entered_by }}</b>\n{% endif %}"
            "\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "vehicle_in",
        "channel": "email",
        "name": "Vehicle In (Email)",
        "subject": "Vehicle In: {{ vehicle_no }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Vehicle In</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Vehicle</b></td><td>{{ vehicle_no }}</td></tr>
  <tr><td><b>Gate Pass</b></td><td>{{ gate_pass_no }}</td></tr>
  <tr><td><b>Type</b></td><td>{{ token_type }}</td></tr>
  <tr><td><b>Party</b></td><td>{{ party_name }}</td></tr>
  <tr><td><b>Material</b></td><td>{{ material }}</td></tr>
  <tr><td><b>In</b></td><td>{{ time }}</td></tr>
  {% if entered_by %}<tr><td><b>Vehicle entered by</b></td><td>{{ entered_by }}</td></tr>{% endif %}
</table>""",
    },
    {
        "event_type": "vehicle_out",
        "channel": "telegram",
        "name": "Vehicle Out (Telegram)",
        "subject": None,
        "body": (
            "🚦 <b>Vehicle Out</b>\n\n"
            "Vehicle: <b>{{ vehicle_no }}</b>\n"
            "{% if token_no and token_no != 'PENDING' %}Token: {{ token_no }}\n{% endif %}"
            "{% if gate_pass_no %}Gate Pass: {{ gate_pass_no }}\n{% endif %}"
            "{% if token_type %}Type: {{ token_type }}\n{% endif %}"
            "Party: {{ party_name }}\n"
            "Material: {{ material }}\n"
            "{% if entry_time %}In: {{ entry_time }}\n{% endif %}"
            "{% if entered_by %}Vehicle entered by: <b>{{ entered_by }}</b>\n{% endif %}"
            "Out: {{ time }}\n"
            "{% if exited_by %}Vehicle exit by: <b>{{ exited_by }}</b>\n{% endif %}"
            "\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "vehicle_out",
        "channel": "email",
        "name": "Vehicle Out (Email)",
        "subject": "Vehicle Out: {{ vehicle_no }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Vehicle Out</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Vehicle</b></td><td>{{ vehicle_no }}</td></tr>
  <tr><td><b>Token</b></td><td>{{ token_no }}</td></tr>
  <tr><td><b>Gate Pass</b></td><td>{{ gate_pass_no }}</td></tr>
  <tr><td><b>Type</b></td><td>{{ token_type }}</td></tr>
  <tr><td><b>Party</b></td><td>{{ party_name }}</td></tr>
  <tr><td><b>Material</b></td><td>{{ material }}</td></tr>
  {% if entry_time %}<tr><td><b>In</b></td><td>{{ entry_time }}</td></tr>{% endif %}
  {% if entered_by %}<tr><td><b>Vehicle entered by</b></td><td>{{ entered_by }}</td></tr>{% endif %}
  <tr><td><b>Out</b></td><td>{{ time }}</td></tr>
  {% if exited_by %}<tr><td><b>Vehicle exit by</b></td><td>{{ exited_by }}</td></tr>{% endif %}
</table>""",
    },

    # ── Invoice write-off (bad debt) ──────────────────────────────────────────
    {
        "event_type": "invoice_write_off",
        "channel": "telegram",
        "name": "Invoice Write-off (Telegram)",
        "subject": None,
        "body": (
            "🧾 <b>Invoice written off</b>\n\n"
            "Invoice: <b>{{ invoice_no }}</b>\n"
            "{% if party_name %}Party: {{ party_name }}\n{% endif %}"
            "Amount: <b>₹{{ amount }}</b>\n"
            "Balance after: ₹{{ balance_after }}\n"
            "Reason: {{ reason }}\n\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "invoice_write_off",
        "channel": "email",
        "name": "Invoice Write-off (Email)",
        "subject": "Write-off {{ invoice_no }} — ₹{{ amount }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;color:#b45309;">Invoice written off</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Invoice</b></td><td>{{ invoice_no }}</td></tr>
  <tr><td><b>Party</b></td><td>{{ party_name }}</td></tr>
  <tr><td><b>Amount</b></td><td>&#8377;{{ amount }}</td></tr>
  <tr><td><b>Balance after</b></td><td>&#8377;{{ balance_after }}</td></tr>
  <tr><td><b>Reason</b></td><td>{{ reason }}</td></tr>
</table>""",
    },

    # ── Diesel / fuel transaction (every fill) ────────────────────────────────
    {
        "event_type": "diesel_transaction",
        "channel": "telegram",
        "name": "Diesel Transaction (Telegram)",
        "subject": None,
        "body": (
            "⛽ <b>Diesel fill</b>\n\n"
            "Vehicle: <b>{{ vehicle_no }}</b>\n"
            "Litres: <b>{{ litres }} L</b>\n"
            "{% if rate %}Rate: ₹{{ rate }}/L\n{% endif %}"
            "{% if amount %}Amount: <b>₹{{ amount }}</b>\n{% endif %}"
            "Odometer: {{ odometer_km }} km\n"
            "Source: {{ fuel_source }}\n\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "diesel_transaction",
        "channel": "email",
        "name": "Diesel Transaction (Email)",
        "subject": "Diesel fill: {{ vehicle_no }} — {{ litres }} L — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Diesel fill</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Vehicle</b></td><td>{{ vehicle_no }}</td></tr>
  <tr><td><b>Litres</b></td><td>{{ litres }} L</td></tr>
  <tr><td><b>Rate</b></td><td>&#8377;{{ rate }}/L</td></tr>
  <tr><td><b>Amount</b></td><td>&#8377;{{ amount }}</td></tr>
  <tr><td><b>Odometer</b></td><td>{{ odometer_km }} km</td></tr>
  <tr><td><b>Source</b></td><td>{{ fuel_source }}</td></tr>
</table>""",
    },

    # ── Payment made (money out — supplier / advance) ─────────────────────────
    {
        "event_type": "payment_made",
        "channel": "telegram",
        "name": "Payment Made (Telegram)",
        "subject": None,
        "body": (
            "💸 <b>Payment made</b>\n\n"
            "To: <b>{{ party_name }}</b>\n"
            "Amount: <b>₹{{ amount }}</b>\n"
            "Voucher: {{ voucher_no }}\n"
            "Mode: {{ payment_mode }}\n"
            "Date: {{ voucher_date }}\n\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "payment_made",
        "channel": "email",
        "name": "Payment Made (Email)",
        "subject": "Payment made: ₹{{ amount }} to {{ party_name }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Payment made</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>To</b></td><td>{{ party_name }}</td></tr>
  <tr><td><b>Amount</b></td><td>&#8377;{{ amount }}</td></tr>
  <tr><td><b>Voucher</b></td><td>{{ voucher_no }}</td></tr>
  <tr><td><b>Mode</b></td><td>{{ payment_mode }}</td></tr>
  <tr><td><b>Date</b></td><td>{{ voucher_date }}</td></tr>
</table>""",
    },

    # ── Worker payment (salary / wage / advance / bonus / deduction) ──────────
    {
        "event_type": "worker_payment",
        "channel": "telegram",
        "name": "Worker Payment (Telegram)",
        "subject": None,
        "body": (
            "👷 <b>Worker payment — {{ payment_type }}</b>\n\n"
            "Worker: <b>{{ worker_name }}</b>\n"
            "Amount: <b>₹{{ amount }}</b>\n"
            "{% if mode %}Mode: {{ mode }}\n{% endif %}"
            "Date: {{ pay_date }}\n\n— {{ company_name }}"
        ),
    },
    {
        "event_type": "worker_payment",
        "channel": "email",
        "name": "Worker Payment (Email)",
        "subject": "Worker {{ payment_type }}: {{ worker_name }} — ₹{{ amount }} — {{ company_name }}",
        "body": """<h2 style="margin:0 0 4px;">Worker payment — {{ payment_type }}</h2>
<p style="margin:0 0 12px;color:#555;">{{ company_name }}</p>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px;">
  <tr><td><b>Worker</b></td><td>{{ worker_name }}</td></tr>
  <tr><td><b>Type</b></td><td>{{ payment_type }}</td></tr>
  <tr><td><b>Amount</b></td><td>&#8377;{{ amount }}</td></tr>
  <tr><td><b>Mode</b></td><td>{{ mode }}</td></tr>
  <tr><td><b>Date</b></td><td>{{ pay_date }}</td></tr>
</table>""",
    },
]


async def seed_default_templates(db: AsyncSession, company_id: uuid.UUID) -> None:
    """Insert any missing default templates (upsert by event_type+channel)."""
    # Load existing (event_type, channel) pairs so we only insert missing ones
    existing_rows = (await db.execute(
        select(NotificationTemplate.event_type, NotificationTemplate.channel).where(
            NotificationTemplate.company_id == company_id
        )
    )).all()
    existing_keys = {(r.event_type, r.channel) for r in existing_rows}

    for t in DEFAULT_TEMPLATES:
        if (t["event_type"], t["channel"]) in existing_keys:
            continue  # already seeded
        db.add(NotificationTemplate(
            company_id=company_id,
            event_type=t["event_type"],
            channel=t["channel"],
            name=t["name"],
            subject=t.get("subject"),
            body=t["body"],
            is_enabled=True,
        ))
    await db.commit()


# Bump this when a DEFAULT_TEMPLATES body must reach ALREADY-seeded tenants (seed
# only inserts MISSING rows, so a changed body never propagates otherwise). Only the
# listed (event_type, channel) pairs are force-updated, ONCE per tenant per version
# — so a later admin customisation on the Notifications page survives future restarts.
_TEMPLATE_REFRESH_VERSION = 10  # v10: token_completed names the operator who created the weighment
_TEMPLATE_REFRESH_KEYS = {
    ("token_completed", "telegram"),
    ("invoice_finalized", "telegram"),
    ("invoice_revised", "telegram"),
    ("anpr_daily_summary", "telegram"),
    ("anpr_daily_summary", "email"),
    ("eod_summary", "telegram"),
    ("vehicle_in", "telegram"),
    ("vehicle_in", "email"),
    ("vehicle_out", "telegram"),
    ("vehicle_out", "email"),
    ("gate_pass_created", "telegram"),
    ("gate_pass_created", "email"),
    ("gate_pass_exit", "telegram"),
    ("gate_pass_exit", "email"),
}


async def refresh_default_templates(db: AsyncSession, company_id: uuid.UUID) -> None:
    """One-time (per version) overwrite of specific default template bodies for a
    tenant, so a shipped template change reaches tenants seeded before it. Guarded by
    an app_settings marker → runs once; admin edits made afterwards are not touched."""
    marker = f"notif_tpl_refresh_v{_TEMPLATE_REFRESH_VERSION}"
    seen = (await db.execute(
        text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": marker}
    )).first()
    if seen:
        return
    by_key = {(t["event_type"], t["channel"]): t for t in DEFAULT_TEMPLATES}
    for key in _TEMPLATE_REFRESH_KEYS:
        t = by_key.get(key)
        if not t:
            continue
        await db.execute(
            update(NotificationTemplate)
            .where(
                NotificationTemplate.company_id == company_id,
                NotificationTemplate.event_type == key[0],
                NotificationTemplate.channel == key[1],
            )
            .values(subject=t.get("subject"), body=t["body"])
        )
    await db.execute(
        text("INSERT INTO app_settings (key, value, updated_at) VALUES (:k, 'true', NOW()) "
             "ON CONFLICT (key) DO NOTHING"),
        {"k": marker},
    )
    await db.commit()


# ── Recipient helpers ──────────────────────────────────────────────────────────

async def _load_recipients(
    db: AsyncSession,
    company_id: uuid.UUID,
    channel: str,
    event_type: str,
) -> list[str]:
    """Return list of contact addresses for active recipients subscribed to event."""
    rows = (await db.execute(
        select(NotificationRecipient).where(
            NotificationRecipient.company_id == company_id,
            NotificationRecipient.channel == channel,
            NotificationRecipient.is_active == True,
        )
    )).scalars().all()

    contacts: list[str] = []
    for r in rows:
        try:
            event_list: list[str] = json.loads(r.event_types or '["*"]')
        except Exception:
            event_list = ["*"]
        if "*" in event_list or event_type in event_list:
            contacts.append(r.contact)
    return contacts


# ── Channel dispatch ───────────────────────────────────────────────────────────

async def _dispatch(channel: str, cfg: NotificationConfig, recipient: str, subject: str | None, body: str) -> None:
    """Send rendered message to a single recipient via the given channel."""
    if channel == "email":
        from app.integrations.notifications.email import send_email
        await send_email(
            smtp_host=cfg.smtp_host or "",
            smtp_port=cfg.smtp_port or 587,
            smtp_user=cfg.smtp_user or "",
            smtp_password=cfg.smtp_password or "",
            from_email=cfg.from_email or "",
            from_name=cfg.from_name or "",
            to_email=recipient,
            subject=subject or "",
            body_html=body,
            use_tls=cfg.use_tls,
        )
    elif channel == "sms":
        from app.integrations.notifications.sms import send_sms
        await send_sms(
            api_key=cfg.sms_api_key or "",
            sender_id=cfg.sms_sender_id or "",
            to_phone=recipient,
            message=body,
            route=cfg.sms_route or "4",
        )
    elif channel == "whatsapp":
        from app.integrations.notifications.whatsapp import send_whatsapp
        await send_whatsapp(
            api_url=cfg.wa_api_url or "",
            api_key=cfg.wa_api_key or "",
            to_phone=recipient,
            message=body,
        )
    elif channel == "telegram":
        from app.integrations.notifications.telegram_notify import send_telegram_notification
        await send_telegram_notification(
            bot_token=cfg.tg_bot_token or "",
            chat_id=recipient,
            text=body,
        )
    else:
        raise ValueError(f"Unknown channel: {channel}")


# ── Main dispatch ──────────────────────────────────────────────────────────────

async def send_notification(
    db: AsyncSession,
    company_id: uuid.UUID,
    event_type: str,
    context: dict[str, Any],
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict]:
    """
    Find enabled templates + configs for event_type, render, send to all recipients,
    and log each attempt. Returns list of log dicts with status.

    Recipients:
    1. Party contact from context (party_email / party_phone) — for email/sms/whatsapp
    2. All active notification_recipients subscribed to this event_type + channel
    """
    results = []

    # Load enabled templates for this event
    templates = (await db.execute(
        select(NotificationTemplate).where(
            NotificationTemplate.company_id == company_id,
            NotificationTemplate.event_type == event_type,
            NotificationTemplate.is_enabled == True,
        )
    )).scalars().all()

    if not templates:
        return results

    # Load configs (one per channel)
    configs_rows = (await db.execute(
        select(NotificationConfig).where(
            NotificationConfig.company_id == company_id,
            NotificationConfig.is_enabled == True,
        )
    )).scalars().all()
    configs = {c.channel: c for c in configs_rows}

    for tmpl in templates:
        cfg = configs.get(tmpl.channel)
        if not cfg:
            continue

        subject = render_template(tmpl.subject or "", context) if tmpl.subject else None
        body = render_template(tmpl.body, context)

        # Build list of recipients to notify
        recipients: list[str] = []

        # 1. Party contact from context (not for Telegram — parties don't have chat IDs)
        if tmpl.channel == "email":
            party_contact = context.get("party_email", "")
            if party_contact:
                recipients.append(party_contact)
        elif tmpl.channel in ("sms", "whatsapp"):
            party_contact = context.get("party_phone", "")
            if party_contact:
                recipients.append(party_contact)

        # 2. Named recipients subscribed to this event
        named = await _load_recipients(db, company_id, tmpl.channel, event_type)
        for c in named:
            if c not in recipients:
                recipients.append(c)

        if not recipients:
            continue

        for recipient in recipients:
            status = "pending"
            error_msg = None
            try:
                await _dispatch(tmpl.channel, cfg, recipient, subject, body)
                status = "sent"
            except Exception as e:
                status = "failed"
                error_msg = _redact_secrets(str(e))[:500]
                logger.warning(
                    "Notification send failed [%s/%s → %s]: %s",
                    tmpl.channel, event_type, recipient, error_msg,
                )

            log_entry = NotificationLog(
                company_id=company_id,
                channel=tmpl.channel,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                recipient=recipient,
                subject=subject,
                body_preview=body[:500],
                status=status,
                error_message=error_msg,
            )
            db.add(log_entry)
            results.append({"channel": tmpl.channel, "recipient": recipient, "status": status, "error": error_msg})

    await db.commit()
    return results
