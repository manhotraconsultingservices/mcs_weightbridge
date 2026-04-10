"""
Mock Tally Prime HTTP server for integration testing.

Mimics Tally's XML import API so tests can verify:
  - Correct XML structure
  - Voucher ledger balance (all amounts sum to zero)
  - Master record structure (LEDGER with NAME + PARENT)
  - Error handling (malformed XML, unbalanced voucher)

Usage (in conftest.py):
    from tests.mock_tally_server import MockTallyServer
    server = MockTallyServer(port=9099)
    server.start()
    yield server
    server.stop()
"""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from xml.etree import ElementTree as ET
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Response templates
# ─────────────────────────────────────────────────────────────────────────────

_TALLY_SUCCESS = """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <STATUS>1</STATUS>
  </HEADER>
  <BODY>
    <DATA>
      <IMPORTRESULT>
        <CREATED>1</CREATED>
        <ALTERED>0</ALTERED>
        <DELETED>0</DELETED>
        <SKIPPED>0</SKIPPED>
        <ERRORS>0</ERRORS>
        <CANCELLED>0</CANCELLED>
      </IMPORTRESULT>
    </DATA>
  </BODY>
</ENVELOPE>"""

_TALLY_ERROR_TMPL = """<ENVELOPE>
  <HEADER>
    <VERSION>1</VERSION>
    <STATUS>0</STATUS>
  </HEADER>
  <BODY>
    <DATA>
      <IMPORTRESULT>
        <CREATED>0</CREATED>
        <ERRORS>1</ERRORS>
        <LINEERROR>{error}</LINEERROR>
      </IMPORTRESULT>
    </DATA>
  </BODY>
</ENVELOPE>"""


# ─────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _collect_amounts(element: ET.Element) -> list[float]:
    """Recursively collect all <AMOUNT> text values from an XML element."""
    amounts: list[float] = []
    for child in element.iter():
        if child.tag == "AMOUNT" and child.text:
            try:
                amounts.append(float(child.text.strip()))
            except ValueError:
                pass
    return amounts


def _voucher_is_balanced(voucher_el: ET.Element, tolerance: float = 0.02) -> tuple[bool, float]:
    """
    Check that a VOUCHER element's ledger amounts sum to zero.

    Tally's accounting rule: every voucher must balance (debits = credits).
    ALLLEDGERENTRIES.LIST amounts + ACCOUNTINGALLOCATIONS.LIST amounts
    in INVENTORYENTRIES.LIST must net to zero.

    Returns (balanced: bool, total: float).
    """
    amounts: list[float] = []

    # Party entry + other ALLLEDGERENTRIES
    for entry in voucher_el.findall("ALLLEDGERENTRIES.LIST"):
        amt_el = entry.find("AMOUNT")
        if amt_el is not None and amt_el.text:
            try:
                amounts.append(float(amt_el.text.strip()))
            except ValueError:
                pass

    # Accounting allocations inside inventory entries
    for inv in voucher_el.findall("INVENTORYENTRIES.LIST"):
        for acc in inv.findall("ACCOUNTINGALLOCATIONS.LIST"):
            amt_el = acc.find("AMOUNT")
            if amt_el is not None and amt_el.text:
                try:
                    amounts.append(float(amt_el.text.strip()))
                except ValueError:
                    pass

    total = sum(amounts)
    return abs(total) <= tolerance, total


def _validate_master(tallymessage_el: ET.Element) -> tuple[bool, str]:
    """
    Validate a master import (All Masters).
    Each LEDGER must have a NAME attribute and a PARENT child element.
    """
    for ledger in tallymessage_el.findall("LEDGER"):
        name = ledger.get("NAME") or ""
        if not name.strip():
            return False, "LEDGER missing NAME attribute"
        parent_el = ledger.find("PARENT")
        if parent_el is None or not (parent_el.text or "").strip():
            return False, f"LEDGER '{name}' missing PARENT element"
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# Request handler
# ─────────────────────────────────────────────────────────────────────────────

class _TallyHandler(BaseHTTPRequestHandler):
    """Handles incoming POST requests to the mock Tally server."""

    # These are set by MockTallyServer after handler class creation
    server_state: "MockTallyServer" = None  # type: ignore[assignment]

    def log_message(self, format, *args):  # noqa: A002
        # Suppress default HTTP logging during tests
        pass

    def do_POST(self):
        state = self.__class__.server_state

        # Simulate timeout
        if state._timeout_mode:
            time.sleep(60)  # hang until test gives up
            return

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")

        # Simulate forced error
        if state._error_mode:
            error_msg = state._error_mode
            state._error_mode = None  # reset after one use
            self._send_xml(400, _TALLY_ERROR_TMPL.format(error=error_msg))
            return

        # Parse XML
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            self._send_xml(400, _TALLY_ERROR_TMPL.format(error=f"XML parse error: {exc}"))
            return

        # Identify request type from REPORTNAME
        reportname_el = root.find(".//REPORTNAME")
        reportname = (reportname_el.text or "").strip() if reportname_el is not None else ""

        tallymessage = root.find(".//TALLYMESSAGE")
        if tallymessage is None:
            self._send_xml(400, _TALLY_ERROR_TMPL.format(error="Missing TALLYMESSAGE element"))
            return

        if reportname == "Vouchers":
            # Validate + store vouchers
            for voucher in tallymessage.findall("VOUCHER"):
                balanced, total = _voucher_is_balanced(voucher)
                if not balanced:
                    self._send_xml(400, _TALLY_ERROR_TMPL.format(
                        error=f"Voucher amounts do not balance: sum={total:.4f}"
                    ))
                    return
                # Store parsed voucher info
                vch_data = {
                    "vchtype": voucher.get("VCHTYPE", ""),
                    "vouchernumber": (voucher.findtext("VOUCHERNUMBER") or "").strip(),
                    "date": (voucher.findtext("DATE") or "").strip(),
                    "party": (voucher.findtext("PARTYLEDGERNAME") or "").strip(),
                    "narration": (voucher.findtext("NARRATION") or "").strip(),
                    "raw_xml": body,
                    "element": voucher,
                }
                with state._lock:
                    state._received_vouchers.append(vch_data)
            self._send_xml(200, _TALLY_SUCCESS)

        elif reportname == "All Masters":
            # Validate + store masters
            ok, err = _validate_master(tallymessage)
            if not ok:
                self._send_xml(400, _TALLY_ERROR_TMPL.format(error=err))
                return
            for ledger in tallymessage.findall("LEDGER"):
                master_data = {
                    "name": ledger.get("NAME", "").strip(),
                    "parent": (ledger.findtext("PARENT") or "").strip(),
                    "gstin": (ledger.findtext("GSTIN") or "").strip(),
                    "gst_reg_type": (ledger.findtext("GSTREGISTRATIONTYPE") or "").strip(),
                    "raw_xml": body,
                    "element": ledger,
                }
                with state._lock:
                    state._received_masters.append(master_data)
            self._send_xml(200, _TALLY_SUCCESS)

        else:
            # Unknown report — still accept (for test connection checks)
            self._send_xml(200, _TALLY_SUCCESS)

    def _send_xml(self, status: int, body: str):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

class MockTallyServer:
    """
    Lightweight mock of Tally Prime's XML import HTTP server.

    Thread-safe in-memory storage for received data.
    Supports error injection and timeout simulation.
    """

    def __init__(self, port: int = 9099, host: str = "127.0.0.1"):
        self._port = port
        self._host = host
        self._lock = threading.Lock()
        self._received_vouchers: list[dict] = []
        self._received_masters: list[dict] = []
        self._error_mode: Optional[str] = None
        self._timeout_mode: bool = False
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the mock server in a daemon thread. Blocks until ready."""
        # Build a handler class that has access to this server state
        state = self

        class Handler(_TallyHandler):
            pass

        Handler.server_state = state  # type: ignore[assignment]

        self._server = HTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="MockTallyServer",
        )
        self._thread.start()
        # Give the server a moment to bind
        time.sleep(0.05)

    def stop(self) -> None:
        """Shut down the mock server."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)

    def reset(self) -> None:
        """Clear all received data between tests."""
        with self._lock:
            self._received_vouchers.clear()
            self._received_masters.clear()
        self._error_mode = None
        self._timeout_mode = False

    # ── Error injection ───────────────────────────────────────────────────────

    def set_error_mode(self, error: Optional[str]) -> None:
        """
        Force the next request to return a Tally error response.
        Pass None to clear. Automatically clears after one request.
        """
        self._error_mode = error

    def set_timeout_mode(self, enabled: bool) -> None:
        """Force the next request to hang (simulates Tally not responding)."""
        self._timeout_mode = enabled

    # ── Assertions / inspection ───────────────────────────────────────────────

    @property
    def received_vouchers(self) -> list[dict]:
        with self._lock:
            return list(self._received_vouchers)

    @property
    def received_masters(self) -> list[dict]:
        with self._lock:
            return list(self._received_masters)

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def __repr__(self) -> str:
        return f"<MockTallyServer {self.url}>"
