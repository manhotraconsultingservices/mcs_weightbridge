"""
NIC E-Way Bill API client (standalone, for challan / B2C / non-IRN movements).

Mirrors the eInvoice client: same NIC auth pattern, 6-hour token cache, retry
with backoff, demo_mode for offline UI exercise. For B2B invoices that already
get an IRN, the EWB number is captured from the IRN response instead (see
invoices._try_generate_irn) — this standalone path covers delivery challans,
B2C, and manual/late EWB generation.

NIC endpoints:
  Sandbox:    https://ewb-apisandbox.nic.in
  Production: https://ewaybillapi.nic.in
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger("eway")

SANDBOX_URL = "https://ewb-apisandbox.nic.in"
PRODUCTION_URL = "https://ewaybillapi.nic.in"


@dataclass
class EWayConfig:
    """E-Way Bill configuration — stored in app_settings as JSON key 'eway_config'."""
    provider: str = "nic"
    base_url: str = SANDBOX_URL
    client_id: str = ""
    client_secret: str = ""
    gstin: str = ""
    username: str = ""
    password: str = ""
    is_sandbox: bool = True
    is_enabled: bool = False
    auto_generate_on_finalize: bool = False   # piggyback on IRN flow when possible
    default_distance_km: int = 0              # 0 => NIC auto-computes by PIN-to-PIN
    demo_mode: bool = False                   # fabricate an EWB no. for UI/PDF preview

    @classmethod
    def from_dict(cls, d: dict) -> "EWayConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class EWayResult:
    success: bool
    ewb_no: str | None = None
    ewb_date: datetime | None = None
    valid_until: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class _AuthToken:
    token: str = ""
    expires_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        return bool(self.token) and time.time() < self.expires_at


_token_cache: dict[str, _AuthToken] = {}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


class EWayClient:
    MAX_RETRIES = 3
    RETRY_BACKOFF = [1, 3, 5]
    TIMEOUT = 30

    def __init__(self, config: EWayConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self._cache_key = hashlib.md5(
            f"ewb:{config.gstin}:{config.username}:{config.base_url}".encode()
        ).hexdigest()

    # ── Auth ──────────────────────────────────────────────────────────────────
    async def authenticate(self) -> str:
        cached = _token_cache.get(self._cache_key)
        if cached and cached.is_valid:
            return cached.token

        url = f"{self.base_url}/ewayapi/v1.03/auth"
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
            raise Exception(f"NIC EWB auth failed: {self._extract_error(data)}")
        token = data.get("Data", {}).get("AuthToken", "")
        _token_cache[self._cache_key] = _AuthToken(token=token, expires_at=time.time() + 5.5 * 3600)
        logger.info("NIC EWB authentication successful for GSTIN %s", self.config.gstin)
        return token

    def _headers(self, token: str) -> dict:
        return {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "gstin": self.config.gstin,
            "authtoken": token,
            "Content-Type": "application/json",
        }

    # ── Generate ──────────────────────────────────────────────────────────────
    async def generate_ewb(self, payload: dict) -> EWayResult:
        """Generate an E-Way Bill (POST .../ewayapi/v1.03/ewayapi)."""
        if self.config.demo_mode:
            now = datetime.now()
            from datetime import timedelta
            return EWayResult(
                success=True,
                ewb_no=f"DEMO{int(time.time()) % 1_000_000_0000:010d}"[:12],
                ewb_date=now,
                valid_until=now + timedelta(days=1),
            )
        token = await self.authenticate()
        url = f"{self.base_url}/ewayapi/v1.03/ewayapi"
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT, verify=True) as client:
                    resp = await client.post(url, json=payload, headers=self._headers(token))
                data = resp.json()
                if resp.status_code == 200 and data.get("Status") == 1:
                    d = data.get("Data", {})
                    return EWayResult(
                        success=True,
                        ewb_no=str(d.get("ewayBillNo") or d.get("EwbNo") or ""),
                        ewb_date=_parse_dt(d.get("ewayBillDate") or d.get("EwbDt")),
                        valid_until=_parse_dt(d.get("validUpto") or d.get("EwbValidTill")),
                    )
                if 400 <= resp.status_code < 500:
                    return EWayResult(success=False, error_code=str(resp.status_code),
                                      error_message=self._extract_error(data))
                last_error = f"HTTP {resp.status_code}: {self._extract_error(data)}"
            except httpx.TimeoutException:
                last_error = f"Request timeout after {self.TIMEOUT}s"
            except Exception as e:
                last_error = str(e)
            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.RETRY_BACKOFF[attempt])
        return EWayResult(success=False, error_code="RETRY_EXHAUSTED",
                          error_message=f"Failed after {self.MAX_RETRIES} attempts: {last_error}")

    # ── Cancel ────────────────────────────────────────────────────────────────
    async def cancel_ewb(self, ewb_no: str, reason: str = "2", remark: str = "") -> EWayResult:
        """Cancel an EWB within 24h. reason: 1=Duplicate, 2=Order Cancelled, 3=Data Entry mistake, 4=Others."""
        if self.config.demo_mode:
            return EWayResult(success=True, ewb_no=ewb_no)
        token = await self.authenticate()
        url = f"{self.base_url}/ewayapi/v1.03/ewayapi/canewb"
        body = {"ewbNo": int(ewb_no) if str(ewb_no).isdigit() else ewb_no,
                "cancelRsnCode": int(reason), "cancelRmrk": remark or "Cancelled"}
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, verify=True) as client:
                resp = await client.post(url, json=body, headers=self._headers(token))
            data = resp.json()
            if resp.status_code == 200 and data.get("Status") == 1:
                return EWayResult(success=True, ewb_no=ewb_no)
            return EWayResult(success=False, error_code=str(resp.status_code),
                              error_message=self._extract_error(data))
        except Exception as e:
            return EWayResult(success=False, error_code="EXCEPTION", error_message=str(e)[:500])

    # ── Update Part-B (vehicle) ───────────────────────────────────────────────
    async def update_vehicle(self, ewb_no: str, vehicle_no: str, *, from_place: str = "",
                             from_state_code: int = 0, reason: str = "2", remark: str = "",
                             trans_mode: str = "1") -> EWayResult:
        """Update Part-B (vehicle) of an existing EWB. reason 2 = 'Due to Transhipment'."""
        if self.config.demo_mode:
            return EWayResult(success=True, ewb_no=ewb_no)
        token = await self.authenticate()
        url = f"{self.base_url}/ewayapi/v1.03/ewayapi/vehewb"
        body = {
            "ewbNo": int(ewb_no) if str(ewb_no).isdigit() else ewb_no,
            "vehicleNo": vehicle_no.replace(" ", "").upper(),
            "fromPlace": from_place, "fromState": from_state_code,
            "reasonCode": reason, "reasonRem": remark or "Vehicle update",
            "transMode": trans_mode, "transDocNo": "", "transDocDate": "",
        }
        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT, verify=True) as client:
                resp = await client.post(url, json=body, headers=self._headers(token))
            data = resp.json()
            if resp.status_code == 200 and data.get("Status") == 1:
                d = data.get("Data", {})
                return EWayResult(success=True, ewb_no=ewb_no, valid_until=_parse_dt(d.get("validUpto")))
            return EWayResult(success=False, error_code=str(resp.status_code),
                              error_message=self._extract_error(data))
        except Exception as e:
            return EWayResult(success=False, error_code="EXCEPTION", error_message=str(e)[:500])

    async def test_connection(self) -> dict:
        try:
            if self.config.demo_mode:
                return {"success": True, "message": "Demo mode — no live NIC call made."}
            token = await self.authenticate()
            return {"success": True, "message": f"Authenticated (token {token[:8]}…)"}
        except Exception as e:
            return {"success": False, "message": str(e)[:500]}

    @staticmethod
    def _extract_error(data: dict) -> str:
        errors = data.get("error") or data.get("ErrorDetails") or data.get("errors")
        if isinstance(errors, list) and errors:
            parts = []
            for err in errors[:3]:
                if isinstance(err, dict):
                    parts.append(f"[{err.get('errorCodes') or err.get('ErrorCode','')}] "
                                 f"{err.get('message') or err.get('ErrorMessage','')}")
                else:
                    parts.append(str(err))
            return "; ".join(parts)
        if isinstance(errors, dict):
            return str(errors.get("message") or errors)[:500]
        return str(data)[:500]
