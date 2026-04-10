"""
PDF generation using Jinja2 + WeasyPrint (primary) or xhtml2pdf (fallback).
"""
import io
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "pdf"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


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


def invoice_context(invoice, company) -> dict:
    """Build Jinja2 context for invoice template."""
    return {
        "invoice": invoice,
        "party": invoice.party,
        "company": company,
    }


def quotation_context(quotation, company) -> dict:
    """Build Jinja2 context for quotation template."""
    return {
        "quotation": quotation,
        "party": quotation.party,
        "company": company,
    }
