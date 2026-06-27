"""
Tally Prime HTTP client.

Tally Prime exposes a local XML-over-HTTP API. To enable it:
  Gateway of Tally → F12 Configuration → Advanced Configuration → Enable ODBC / TDL server
  Default port: 9000 (but configurable — avoid clash with our Vite dev server on 9000)

Usage:
  client = TallyClient(host="localhost", port=9002, company="My Company")
  ok, msg = await client.test_connection()
  ok, msg = await client.push_xml(xml_string)
"""
from __future__ import annotations
import httpx
from xml.etree import ElementTree as ET


class TallyClient:
    def __init__(self, host: str = "localhost", port: int = 9002, company: str = ""):
        self.base_url = f"http://{host}:{port}"
        self.company = company
        self.timeout = 10.0

    async def test_connection(self) -> tuple[bool, str]:
        """Send a simple company-list request to verify Tally is reachable."""
        xml = """<ENVELOPE>
  <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>List of Companies</REPORTNAME>
      </REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.base_url, content=xml,
                                         headers={"Content-Type": "text/xml"})
                if resp.status_code == 200:
                    return True, "Connected to Tally successfully"
                return False, f"Tally responded with HTTP {resp.status_code}"
        except httpx.ConnectError:
            return False, f"Cannot connect to Tally at {self.base_url}. Is Tally running?"
        except httpx.TimeoutException:
            return False, f"Connection timed out — Tally at {self.base_url} is not responding"
        except Exception as e:
            return False, f"Error: {e}"

    async def get_companies(self) -> tuple[bool, list[str]]:
        """Fetch list of companies open in Tally."""
        xml = """<ENVELOPE>
  <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>List of Companies</REPORTNAME>
      </REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.base_url, content=xml,
                                         headers={"Content-Type": "text/xml"})
                if resp.status_code != 200:
                    return False, []
                # Parse company names from response
                companies = _extract_companies(resp.text)
                return True, companies
        except Exception:
            return False, []

    async def push_xml(self, xml: str) -> tuple[bool, str]:
        """
        POST XML to Tally. Returns (success, message).
        Tally returns XML with LINEERROR or CREATED tags to indicate result.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.base_url,
                    content=xml.encode("utf-8"),
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                )
                if resp.status_code != 200:
                    return False, f"Tally returned HTTP {resp.status_code}"
                return _parse_tally_response(resp.text)
        except httpx.ConnectError:
            return False, f"Cannot connect to Tally at {self.base_url}"
        except httpx.TimeoutException:
            return False, "Tally connection timed out"
        except Exception as e:
            return False, f"Unexpected error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Response parsers
# ─────────────────────────────────────────────────────────────────────────────

def _count_tag(root, tag: str):
    """Return the int value of a Tally response count tag, or None if absent/blank."""
    el = root.find(f".//{tag}")
    if el is None or el.text is None:
        return None
    try:
        return int(el.text.strip())
    except ValueError:
        return None


# Shared message so the on-prem client and the relay connector report the same
# actionable hint when Tally accepts the request but imports nothing. The exact
# reason is only in Tally's own import-exceptions log; we surface the likely
# causes — GST/inventory validation FIRST because it's the most common one for
# full-mode invoices on a company that isn't GST-configured.
ZERO_IMPORT_HINT = (
    "Tally accepted the request but imported 0 records. The exact reason is in "
    "Tally's import-exceptions log; the usual causes are: (1) the voucher failed "
    "Tally's GST/inventory validation — the company isn't GST-enabled (F11 > GST "
    "+ GSTIN) or the stock item has no GST rate (common for full GST/inventory "
    "invoices; switch to No-GST / accounting-only mode if you don't want GST in "
    "Tally); (2) a referenced master (ledger / stock item / party) doesn't exist "
    'yet; (3) a same-GUID voucher was skipped because Import Config "Overwrite '
    'voucher when same GUID exists" = No (set it to Yes).'
)


def response_summary(xml_text: str) -> str:
    """Compact one-line digest of Tally's import counts for logging/diagnostics.

    Turns the verbose ``<RESPONSE>`` envelope into e.g.
    ``created=0 altered=0 ignored=0 errors=0 exceptions=1`` so the actual counts
    (and any LINEERROR) land in the log instead of being thrown away.
    """
    try:
        root = ET.fromstring(xml_text or "")
    except ET.ParseError:
        return (xml_text or "").strip().replace("\n", " ")[:300]
    parts = []
    for tag in ("CREATED", "ALTERED", "IGNORED", "ERRORS", "EXCEPTIONS", "CANCELLED"):
        v = _count_tag(root, tag)
        if v is not None:
            parts.append(f"{tag.lower()}={v}")
    le = [e.text for e in root.findall(".//LINEERROR") if e.text]
    if le:
        parts.append("lineerror=" + " | ".join(le)[:200])
    return " ".join(parts) or (xml_text or "").strip()[:200]


def _parse_tally_response(xml_text: str) -> tuple[bool, str]:
    """Parse Tally's XML response to determine success/failure.

    Tally's import envelope reports counts: ``<CREATED>``/``<ALTERED>`` on a real
    import, and ``<EXCEPTIONS>``/``<ERRORS>`` when vouchers were skipped. A skipped
    duplicate (Import Config "Overwrite voucher when same GUID exists" = No) returns
    ``CREATED=0 ALTERED=0 EXCEPTIONS=1`` with NO ``<LINEERROR>`` — so we MUST inspect
    the counts, otherwise a silent no-op masquerades as a successful sync and we'd
    wrongly flip ``tally_synced``. We only treat "zero imported" as a failure when
    Tally actually returned count tags; a count-less envelope (older builds) stays
    leniently successful so we don't false-fail those.
    """
    try:
        root = ET.fromstring(xml_text)
        # Hard per-line errors (malformed voucher, missing ledger, etc.)
        errors = root.findall(".//LINEERROR")
        if errors:
            msgs = [e.text or "" for e in errors if e.text]
            return False, "; ".join(msgs) or "Tally reported an error"

        created = _count_tag(root, "CREATED")
        altered = _count_tag(root, "ALTERED")
        exceptions = _count_tag(root, "EXCEPTIONS")
        errs = _count_tag(root, "ERRORS")

        # Something actually landed.
        if (created or 0) > 0:
            return True, f"Voucher created in Tally ({created} record(s))"
        if (altered or 0) > 0:
            return True, f"Voucher updated in Tally ({altered} record(s))"

        # Nothing landed but Tally flagged exceptions/errors — surface it with the
        # actual counts embedded so the stored error message is self-explanatory.
        if (exceptions or 0) > 0 or (errs or 0) > 0:
            return False, f"{ZERO_IMPORT_HINT} [Tally: {response_summary(xml_text)}]"

        # Tally returned count tags and they all show zero imported.
        if any(v is not None for v in (created, altered, exceptions, errs)):
            return False, f"{ZERO_IMPORT_HINT} [Tally: {response_summary(xml_text)}]"

        # No count tags at all — older Tally returns a bare envelope on success.
        return True, "Sent to Tally successfully"
    except ET.ParseError:
        # Tally sometimes returns non-XML on success (older versions)
        # Use tag form to avoid matching error messages that mention "created"
        if "<CREATED>" in xml_text:
            return True, "Voucher created in Tally"
        return True, "Sent to Tally (response: OK)"


def _extract_companies(xml_text: str) -> list[str]:
    """Extract company names from Tally's company list response."""
    try:
        root = ET.fromstring(xml_text)
        return [el.text for el in root.findall(".//BASICCOMPANYNAME") if el.text]
    except Exception:
        return []
