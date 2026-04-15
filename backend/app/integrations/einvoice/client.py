"""
NIC eInvoice API client.

Handles authentication, IRN generation, and IRN cancellation against
the NIC eInvoice portal (sandbox + production).

Endpoints:
  Sandbox:    https://einv-apisandbox.nic.in
  Production: https://einvoice1.gst.gov.in

Authentication tokens are cached for 6 hours (NIC session lifetime).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("einvoice")


# ── Configuration ────────────────────────────────────────────────────────────

SANDBOX_URL = "https://einv-apisandbox.nic.in"
PRODUCTION_URL = "https://einvoice1.gst.gov.in"


@dataclass
class EInvoiceConfig:
    """eInvoice configuration — stored in app_settings table as JSON."""
    provider: str = "nic"                    # "nic" (only supported provider for now)
    base_url: str = SANDBOX_URL
    client_id: str = ""
    client_secret: str = ""
    gstin: str = ""
    username: str = ""
    password: str = ""
    is_sandbox: bool = True
    is_enabled: bool = False
    auto_generate_on_finalize: bool = True
    demo_mode: bool = False                  # Generate fake IRN+QR for PDF preview (no NIC API call)

    @classmethod
    def from_dict(cls, d: dict) -> "EInvoiceConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "gstin": self.gstin,
            "username": self.username,
            "password": self.password,
            "is_sandbox": self.is_sandbox,
            "is_enabled": self.is_enabled,
            "auto_generate_on_finalize": self.auto_generate_on_finalize,
            "demo_mode": self.demo_mode,
        }


@dataclass
class EInvoiceResult:
    """Result of an IRN generation or cancellation request."""
    success: bool
    irn: str | None = None
    ack_no: str | None = None
    ack_date: datetime | None = None
    signed_qr_code: str | None = None
    signed_invoice: str | None = None
    error_code: str | None = None
    error_message: str | None = None


# ── Auth token cache ─────────────────────────────────────────────────────────

@dataclass
class _AuthToken:
    token: str = ""
    sek: str = ""  # Session Encryption Key (base64)
    expires_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self.token and time.time() < self.expires_at


_token_cache: dict[str, _AuthToken] = {}


# ── Client ───────────────────────────────────────────────────────────────────

class EInvoiceClient:
    """
    Async HTTP client for the NIC eInvoice API.

    Usage::

        config = EInvoiceConfig(...)
        client = EInvoiceClient(config)
        result = await client.generate_irn(payload)
    """

    MAX_RETRIES = 3
    RETRY_BACKOFF = [1, 3, 5]  # seconds
    TIMEOUT = 30  # seconds

    def __init__(self, config: EInvoiceConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._cache_key = hashlib.md5(
            f"{config.gstin}:{config.username}:{config.base_url}".encode()
        ).hexdigest()

    # ── Authentication ───────────────────────────────────────────────────────

    async def authenticate(self) -> str:
        """
        Authenticate with NIC and return the auth token.
        Caches the token for ~5.5 hours (NIC tokens last 6 hours).
        """
        cached = _token_cache.get(self._cache_key)
        if cached and cached.is_valid:
            return cached.token

        url = f"{self.base_url}/eivital/v1.04/auth"
        headers = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "gstin": self.config.gstin,
        }
        body = {
            "UserName": self.config.username,
            "Password": self.config.password,
            "Gstin": self.config.gstin,
            "ForceRefreshAccessToken": "true",
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT, verify=True) as client:
            resp = await client.post(url, json=body, headers=headers)

        data = resp.json()
        if resp.status_code != 200 or data.get("Status") == 0:
            error_msg = data.get("ErrorDetails", [{}])
            if isinstance(error_msg, list) and error_msg:
                error_msg = error_msg[0].get("ErrorMessage", str(data))
            raise Exception(f"NIC auth failed: {error_msg}")

        result = data.get("Data", {})
        token = result.get("AuthToken", "")
        sek = result.get("Sek", "")

        # Cache for 5.5 hours (NIC tokens expire in 6 hours)
        _token_cache[self._cache_key] = _AuthToken(
            token=token,
            sek=sek,
            expires_at=time.time() + 5.5 * 3600,
        )

        logger.info("NIC eInvoice authentication successful for GSTIN %s", self.config.gstin)
        return token

    # ── IRN Generation ───────────────────────────────────────────────────────

    async def generate_irn(self, payload: dict) -> EInvoiceResult:
        """
        Generate an IRN by posting the eInvoice payload to NIC.

        Retries up to MAX_RETRIES times on 5xx errors with exponential backoff.
        """
        token = await self.authenticate()

        url = f"{self.base_url}/eicore/v1.03/Invoice"
        headers = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "gstin": self.config.gstin,
            "authtoken": token,
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT, verify=True) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                data = resp.json()

                # Success
                if resp.status_code == 200 and data.get("Status") == 1:
                    result_data = data.get("Data", {})
                    ack_date = None
                    if result_data.get("AckDt"):
                        try:
                            ack_date = datetime.strptime(result_data["AckDt"], "%d/%m/%Y %I:%M:%S %p")
                        except (ValueError, TypeError):
                            try:
                                ack_date = datetime.fromisoformat(result_data["AckDt"])
                            except (ValueError, TypeError):
                                pass

                    return EInvoiceResult(
                        success=True,
                        irn=result_data.get("Irn"),
                        ack_no=str(result_data.get("AckNo", "")),
                        ack_date=ack_date,
                        signed_qr_code=result_data.get("SignedQRCode"),
                        signed_invoice=result_data.get("SignedInvoice"),
                    )

                # Duplicate IRN — treat as success (IRN already exists for this invoice)
                error_details = data.get("ErrorDetails", [])
                if isinstance(error_details, list):
                    for err in error_details:
                        err_code = err.get("ErrorCode", "")
                        if str(err_code) == "2150":
                            # IRN already generated — extract from error info
                            info = err.get("ErrorMessage", "")
                            logger.warning("IRN already exists: %s", info)
                            # Try to extract IRN from InfoDtls
                            info_dtls = data.get("InfoDtls", [{}])
                            if isinstance(info_dtls, list) and info_dtls:
                                info_data = info_dtls[0].get("InfCd", {})
                                if isinstance(info_data, dict):
                                    return EInvoiceResult(
                                        success=True,
                                        irn=info_data.get("Irn"),
                                        ack_no=str(info_data.get("AckNo", "")),
                                        ack_date=None,
                                        signed_qr_code=info_data.get("SignedQRCode"),
                                    )
                            return EInvoiceResult(
                                success=False,
                                error_code="2150",
                                error_message=f"IRN already exists: {info}",
                            )

                # Client error (4xx) — don't retry
                if 400 <= resp.status_code < 500:
                    error_msg = self._extract_error(data)
                    return EInvoiceResult(
                        success=False,
                        error_code=str(resp.status_code),
                        error_message=error_msg,
                    )

                # Server error (5xx) — retry
                last_error = f"HTTP {resp.status_code}: {self._extract_error(data)}"
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_BACKOFF[attempt])
                    continue

            except httpx.TimeoutException:
                last_error = f"Request timeout after {self.TIMEOUT}s"
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_BACKOFF[attempt])
                    continue
            except Exception as e:
                last_error = str(e)
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_BACKOFF[attempt])
                    continue

        return EInvoiceResult(
            success=False,
            error_code="RETRY_EXHAUSTED",
            error_message=f"Failed after {self.MAX_RETRIES} attempts: {last_error}",
        )

    # ── IRN Cancellation ─────────────────────────────────────────────────────

    async def cancel_irn(self, irn: str, reason: str = "1", remark: str = "") -> EInvoiceResult:
        """
        Cancel an IRN within 24 hours of generation.

        reason codes: "1" = Duplicate, "2" = Data Entry Mistake
        """
        token = await self.authenticate()

        url = f"{self.base_url}/eicore/v1.03/Invoice/Cancel"
        headers = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "gstin": self.config.gstin,
            "authtoken": token,
            "Content-Type": "application/json",
        }
        body = {
            "Irn": irn,
            "CnlRsn": reason,
            "CnlRem": remark or "Cancelled",
        }

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, verify=True) as client:
                resp = await client.post(url, json=body, headers=headers)

            data = resp.json()
            if resp.status_code == 200 and data.get("Status") == 1:
                return EInvoiceResult(success=True, irn=irn)
            else:
                return EInvoiceResult(
                    success=False,
                    error_code=str(resp.status_code),
                    error_message=self._extract_error(data),
                )
        except Exception as e:
            return EInvoiceResult(
                success=False,
                error_code="EXCEPTION",
                error_message=str(e)[:500],
            )

    # ── Test connection ──────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Test authentication only. Returns {"success": True/False, "message": "..."}."""
        try:
            token = await self.authenticate()
            return {"success": True, "message": f"Authenticated successfully (token: {token[:8]}...)"}
        except Exception as e:
            return {"success": False, "message": str(e)[:500]}

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_error(data: dict) -> str:
        """Extract human-readable error message from NIC response."""
        errors = data.get("ErrorDetails", [])
        if isinstance(errors, list) and errors:
            parts = []
            for err in errors[:3]:  # max 3 errors
                code = err.get("ErrorCode", "")
                msg = err.get("ErrorMessage", "")
                parts.append(f"[{code}] {msg}" if code else msg)
            return "; ".join(parts)
        return data.get("error", str(data))[:500]
