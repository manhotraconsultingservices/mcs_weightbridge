"""
Industry accelerator — per-tenant vertical presets.

An "industry" maps to:
  (a) module-flag OVERRIDES — which hubs/features are shown (gated by the
      existing tenant-modules mechanism), and
  (b) a TERMINOLOGY overlay key — the frontend swaps in an i18n label bundle
      (e.g. Customer→Farmer, Token→Weighment) for that vertical.

Everything is additive. The default `generic` industry applies NO overrides and
NO terminology overlay, so a tenant with no industry set behaves exactly as it
does today.

Module precedence at login (see routers/auth.py):
    DEFAULT_MODULES  <  industry preset.modules  <  tenant config.modules
The preset is applied dynamically at login (NOT baked into config.modules), so
switching a tenant's industry takes effect immediately and a super-admin can
still pin any single module per tenant via config.modules.
"""
from __future__ import annotations

DEFAULT_INDUSTRY = "generic"

# value → { label, modules (overrides), terminology (overlay key | None) }
INDUSTRY_PRESETS: dict[str, dict] = {
    "generic": {
        "label": "Generic Weighbridge",
        "modules": {},          # no overrides → full DEFAULT_MODULES set
        "terminology": None,
    },
    "stone_crusher": {
        "label": "Stone Crusher",
        "modules": {},          # the original product = the default feature set
        "terminology": None,    # current English labels are the crusher baseline
    },
    "maize_trader": {
        "label": "Maize / Grain Trader",
        # Hide crusher-only areas; keep the trading + weighbridge core on.
        "modules": {
            "production": False,   # no crushing/yield workflow
            "cameras": False,      # no gate-camera snapshots
            "anpr": False,         # no plate-recognition gate
            "royalty": False,      # no mineral royalty/transit passes
            "gate": False,         # no controlled-access gate register
        },
        "terminology": "maize",
    },
}


def normalize_industry(value: str | None) -> str:
    """Coerce any input to a known industry value (falls back to generic)."""
    v = (value or "").strip().lower()
    return v if v in INDUSTRY_PRESETS else DEFAULT_INDUSTRY


def industry_modules(value: str | None) -> dict:
    """Module-flag overrides for an industry (empty dict for generic/unknown)."""
    return dict(INDUSTRY_PRESETS[normalize_industry(value)].get("modules") or {})


def industry_terminology(value: str | None) -> str | None:
    """Terminology overlay key for an industry (None = no overlay)."""
    return INDUSTRY_PRESETS[normalize_industry(value)].get("terminology")


def industry_list() -> list[dict]:
    """All selectable industries — for the platform-admin picker."""
    return [{"value": k, "label": v["label"]} for k, v in INDUSTRY_PRESETS.items()]
