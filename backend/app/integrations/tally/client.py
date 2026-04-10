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

def _parse_tally_response(xml_text: str) -> tuple[bool, str]:
    """Parse Tally's XML response to determine success/failure."""
    try:
        root = ET.fromstring(xml_text)
        # Check for LINEERROR
        errors = root.findall(".//LINEERROR")
        if errors:
            msgs = [e.text or "" for e in errors if e.text]
            return False, "; ".join(msgs) or "Tally reported an error"
        # Check for CREATED count
        created = root.find(".//CREATED")
        altered = root.find(".//ALTERED")
        if created is not None:
            count = int(created.text or "0")
            if count > 0:
                return True, f"Voucher created in Tally ({count} record(s))"
        if altered is not None:
            count = int(altered.text or "0")
            if count > 0:
                return True, f"Voucher updated in Tally ({count} record(s))"
        # If we got XML back without errors, assume success
        return True, "Sent to Tally successfully"
    except ET.ParseError:
        # Tally sometimes returns non-XML on success
        if "CREATED" in xml_text or "created" in xml_text.lower():
            return True, "Voucher created in Tally"
        return True, "Sent to Tally (response: OK)"


def _extract_companies(xml_text: str) -> list[str]:
    """Extract company names from Tally's company list response."""
    try:
        root = ET.fromstring(xml_text)
        return [el.text for el in root.findall(".//BASICCOMPANYNAME") if el.text]
    except Exception:
        return []
