"""
PDF generation using Jinja2 + WeasyPrint (primary) or xhtml2pdf (fallback).
"""
import io
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# ── Default Invoice Print Settings ────────────────────────────────────────── #

DEFAULT_INVOICE_PRINT_SETTINGS = {
    "page_size": "a4",  # "a4" or "a5"
    "copies": 3,
    "copy_labels": ["ORIGINAL FOR RECIPIENT", "DUPLICATE FOR TRANSPORTER", "TRIPLICATE FOR SUPPLIER"],
    "company": {
        "show_tagline": False,
        "tagline": "",
        "show_address": True,
        "show_gstin": True,
        "show_state": True,
        "show_phone": True,
        "show_email": True,
        "show_pan": False,
    },
    "party": {
        "show_consignee": False,
        "show_buyer": True,
        "show_gstin": True,
        "show_address": True,
        "show_state": True,
        "show_phone": False,
    },
    "metadata": {
        "show_delivery_note": True,
        "show_payment_mode": True,
        "show_suppliers_ref": True,
        "show_other_ref": True,
        "show_buyers_order": True,
        "show_royalty_no": True,
        "show_driver_name": True,
        "show_destination": True,
        "show_lr_no": True,
        "show_vehicle_no": True,
        "show_terms_delivery": True,
    },
    "items": {
        "show_hsn": True,
        "show_rate": True,
        "show_per": True,
        "show_tax_inline": True,
        "show_qty_total": True,
        "show_discount_col": False,
    },
    "sections": {
        "show_weight": True,
        "show_bank_details": True,
        "show_amount_words": True,
        "show_hsn_summary": True,
        "show_tax_words": True,
        "show_declaration": True,
        "show_signature": True,
        "show_notes": True,
        "show_place_of_supply": False,
        "show_computer_generated": True,
    },
}

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "pdf"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


# ── Amount in Words (Indian numbering system) ──────────────────────────────── #

def _amount_in_words(amount: float) -> str:
    """Convert a rupee amount to Indian English words. E.g. 32134.50 → 'Rupees Thirty Two Thousand One Hundred Thirty Four and Fifty Paise Only'"""
    ones = [
        '', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
        'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
        'Seventeen', 'Eighteen', 'Nineteen',
    ]
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def _below_hundred(n: int) -> str:
        if n < 20:
            return ones[n]
        return tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')

    def _below_thousand(n: int) -> str:
        if n < 100:
            return _below_hundred(n)
        h = ones[n // 100] + ' Hundred'
        rem = n % 100
        return h + (' ' + _below_hundred(rem) if rem else '')

    if amount < 0:
        return 'Negative ' + _amount_in_words(-amount)

    rupees = int(amount)
    paise = round((amount - rupees) * 100)

    parts = []
    crore = rupees // 10_000_000
    rupees %= 10_000_000
    lakh = rupees // 100_000
    rupees %= 100_000
    thousand = rupees // 1000
    rupees %= 1000

    if crore:
        parts.append(_below_hundred(crore) + ' Crore')
    if lakh:
        parts.append(_below_hundred(lakh) + ' Lakh')
    if thousand:
        parts.append(_below_thousand(thousand) + ' Thousand')
    if rupees:
        parts.append(_below_thousand(rupees))

    words = ' '.join(parts) if parts else 'Zero'
    result = 'Rupees ' + words
    if paise:
        result += ' and ' + _below_hundred(paise) + ' Paise'
    return result + ' Only'


# Register as a Jinja2 global so templates can call it directly
jinja_env.globals['amount_in_words'] = _amount_in_words


def render_html(template_name: str, context: dict) -> str:
    tpl = jinja_env.get_template(template_name)
    return tpl.render(**context)


def generate_pdf(template_name: str, context: dict) -> bytes:
    import logging
    log = logging.getLogger(__name__)

    html = render_html(template_name, context)

    # Try WeasyPrint first (best quality)
    try:
        from weasyprint import HTML
        pdf = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
        if pdf and pdf[:4] == b"%PDF":
            log.info("PDF generated via WeasyPrint (%d bytes)", len(pdf))
            return pdf
    except Exception as e:
        log.warning("WeasyPrint failed: %s: %s", type(e).__name__, e)

    # Fallback: xhtml2pdf (pure Python, no external libs needed)
    try:
        from xhtml2pdf import pisa
        import sys
        buf = io.BytesIO()
        pisa.CreatePDF(html, dest=buf, encoding="utf-8", err=sys.stderr)
        buf.seek(0)
        result = buf.read()
        if result and result[:4] == b"%PDF":
            log.info("PDF generated via xhtml2pdf (%d bytes)", len(result))
            return result
        log.warning("xhtml2pdf produced no valid PDF (got %d bytes, starts=%r)", len(result), result[:8])
    except Exception as e:
        log.error("xhtml2pdf failed: %s: %s", type(e).__name__, e)

    # Last resort: return HTML bytes (route detects via %PDF check)
    log.error("All PDF backends failed — returning HTML fallback")
    return html.encode("utf-8")


def _generate_qr_base64(data: str) -> str | None:
    """Generate QR code PNG as base64 string from eInvoice signed QR data."""
    try:
        import qrcode
        import base64
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=4, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")
    except ImportError:
        # qrcode package not installed — skip QR
        return None
    except Exception:
        return None


def invoice_context(invoice, company, token=None, print_settings: dict | None = None) -> dict:
    """Build Jinja2 context for invoice template."""
    # Generate QR code image if IRN exists
    qr_code_img = None
    irn_qr = getattr(invoice, "irn_qr_code", None)
    if irn_qr:
        qr_code_img = _generate_qr_base64(irn_qr)

    return {
        "invoice": invoice,
        "party": invoice.party,
        "company": company,
        "token": token,
        "qr_code_img": qr_code_img,
        "ps": print_settings or DEFAULT_INVOICE_PRINT_SETTINGS,
    }


def quotation_context(quotation, company) -> dict:
    """Build Jinja2 context for quotation template."""
    return {
        "quotation": quotation,
        "party": quotation.party,
        "company": company,
    }
