"""
Accounting-calculation audit test suite.

Standalone (no DB, no pytest required):
    cd backend && python tests/test_accounting_audit.py

Validates the GST/invoice calculation engine (app.services.gst_service) plus the
weight↔volume (MT / kg / CFT / CBM) conversions against Indian GST + accounting
rules. Designed to be run repeatedly (idempotent, pure functions).

Exit code 0 = all pass, 1 = at least one failure.
"""
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.gst_service import (  # noqa: E402
    calculate_invoice_totals,
    calculate_item_gst,
    is_intra_state,
)

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} :: {detail}")
        print(f"  FAIL  {name}  -> {detail}")


def D(x) -> Decimal:
    return Decimal(str(x))


# Canonical unit constants
CFT_PER_M3 = Decimal("35.3147")          # 1 m³ = 35.3147 ft³
KG_PER_CFT_FROM_T_PER_M3 = Decimal("1000") / CFT_PER_M3   # t/m³ → kg/CFT


def footing_invariant(t: dict) -> bool:
    """taxable + cgst + sgst + igst + freight + tcs + round_off == grand_total"""
    lhs = (t["taxable_amount"] + t["cgst_amount"] + t["sgst_amount"] + t["igst_amount"]
           + t["freight"] + t["tcs_amount"] + t["round_off"])
    return lhs == t["grand_total"]


def is_whole_rupee(v: Decimal) -> bool:
    return v == v.quantize(Decimal("1"))


# ─────────────────────────────────────────────────────────────────────────────
def test_intra_state_basic():
    print("\n[1] Intra-state GST 5% — 100 MT @ ₹400")
    t = calculate_invoice_totals(
        items=[{"quantity": 100, "rate": 400, "gst_rate": 5}],
        discount_type=None, discount_value=D(0), freight=D(0), tcs_rate=D(0),
        intra_state=True, tax_type="gst",
    )
    check("taxable == 40000", t["taxable_amount"] == D("40000.00"), str(t["taxable_amount"]))
    check("cgst == 1000", t["cgst_amount"] == D("1000.00"), str(t["cgst_amount"]))
    check("sgst == 1000", t["sgst_amount"] == D("1000.00"), str(t["sgst_amount"]))
    check("igst == 0", t["igst_amount"] == D("0"), str(t["igst_amount"]))
    check("grand_total == 42000", t["grand_total"] == D("42000.00"), str(t["grand_total"]))
    check("amount_due == grand_total", t["amount_due"] == t["grand_total"], str(t["amount_due"]))
    check("footing invariant", footing_invariant(t))
    check("grand_total whole rupee", is_whole_rupee(t["grand_total"]))


def test_inter_state_rounding():
    print("\n[2] Inter-state IGST 18% — 10 @ ₹999.99 (round-off exercised)")
    t = calculate_invoice_totals(
        items=[{"quantity": 10, "rate": 999.99, "gst_rate": 18}],
        discount_type=None, discount_value=D(0), freight=D(0), tcs_rate=D(0),
        intra_state=False, tax_type="gst",
    )
    # taxable 9999.90, igst round2(1799.982)=1799.98, total 11799.88 -> grand 11800, round_off 0.12
    check("taxable == 9999.90", t["taxable_amount"] == D("9999.90"), str(t["taxable_amount"]))
    check("igst == 1799.98", t["igst_amount"] == D("1799.98"), str(t["igst_amount"]))
    check("cgst==sgst==0 (inter-state)", t["cgst_amount"] == 0 and t["sgst_amount"] == 0)
    check("grand_total == 11800 (nearest rupee)", t["grand_total"] == D("11800.00"), str(t["grand_total"]))
    check("round_off == 0.12", t["round_off"] == D("0.12"), str(t["round_off"]))
    check("footing invariant", footing_invariant(t))
    check("grand_total whole rupee", is_whole_rupee(t["grand_total"]))


def test_non_gst_bill_of_supply():
    print("\n[3] Non-GST (Bill of Supply) — 50 MT @ ₹350")
    t = calculate_invoice_totals(
        items=[{"quantity": 50, "rate": 350, "gst_rate": 5}],   # gst_rate ignored
        discount_type=None, discount_value=D(0), freight=D(0), tcs_rate=D(0),
        intra_state=True, tax_type="non_gst",
    )
    check("cgst == 0", t["cgst_amount"] == 0)
    check("sgst == 0", t["sgst_amount"] == 0)
    check("igst == 0", t["igst_amount"] == 0)
    check("taxable == 17500", t["taxable_amount"] == D("17500.00"), str(t["taxable_amount"]))
    check("grand_total == 17500", t["grand_total"] == D("17500.00"), str(t["grand_total"]))
    check("footing invariant", footing_invariant(t))


def test_multiline_discount():
    print("\n[4] Multi-line + 10% invoice discount, GST on post-discount base")
    t = calculate_invoice_totals(
        items=[
            {"quantity": 100, "rate": 400, "gst_rate": 5},   # 40000
            {"quantity": 50, "rate": 300, "gst_rate": 5},    # 15000
        ],
        discount_type="percentage", discount_value=D(10), freight=D(0), tcs_rate=D(0),
        intra_state=True, tax_type="gst",
    )
    # subtotal 55000, discount 5500, taxable 49500
    check("discount == 5500", t["discount_amount"] == D("5500.00"), str(t["discount_amount"]))
    check("taxable == 49500", t["taxable_amount"] == D("49500.00"), str(t["taxable_amount"]))
    # GST 5% on 49500 = 2475 total -> 1237.50 each
    check("cgst+sgst == 2475 (5% of post-discount)",
          t["cgst_amount"] + t["sgst_amount"] == D("2475.00"),
          f'{t["cgst_amount"]}+{t["sgst_amount"]}')
    check("footing invariant", footing_invariant(t))
    check("grand_total whole rupee", is_whole_rupee(t["grand_total"]))


def test_freight_tcs():
    print("\n[5] Freight + TCS, footing must still hold")
    t = calculate_invoice_totals(
        items=[{"quantity": 30, "rate": 412.37, "gst_rate": 18}],
        discount_type=None, discount_value=D(0), freight=D("250.55"), tcs_rate=D("0.1"),
        intra_state=True, tax_type="gst",
    )
    check("footing invariant (freight+tcs)", footing_invariant(t),
          f'gt={t["grand_total"]} ro={t["round_off"]}')
    check("grand_total whole rupee", is_whole_rupee(t["grand_total"]))
    check("freight preserved 250.55", t["freight"] == D("250.55"), str(t["freight"]))


def test_cgst_sgst_no_penny_lost():
    print("\n[6] CGST+SGST always == total line tax (odd-paisa safety) across 0.01..0.99")
    ok = True
    for paise in range(0, 100):
        amount = D(f"100.{paise:02d}")
        g = calculate_item_gst(amount, D(5), intra_state=True)
        total = g["cgst"] + g["sgst"]
        # Engine uses ROUND_HALF_UP (Indian standard) — match it here.
        expect = (amount * D(5) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total != expect:
            ok = False
            FAILURES.append(f"cgst+sgst mismatch at {amount}: {total} != {expect}")
            break
    check("cgst+sgst == round2(amount*rate) for all paise", ok)


def test_gst_split_decision():
    print("\n[7] Intra/inter-state decision")
    check("same state -> intra", is_intra_state("27", "27") is True)
    check("diff state -> inter", is_intra_state("27", "29") is False)
    check("unknown -> intra default", is_intra_state(None, "29") is True)


def test_weight_volume_conversions():
    print("\n[8] Weight ↔ volume (MT / kg / CFT / CBM)")
    # Volume token: 100 CFT aggregate @ 42.5 kg/CFT
    volume_cft = D("100")
    density_kg_per_cft = D("42.5")
    net_kg = (volume_cft * density_kg_per_cft).quantize(Decimal("0.01"))
    check("100 CFT * 42.5 = 4250 kg", net_kg == D("4250.00"), str(net_kg))
    check("4250 kg = 4.25 MT", (net_kg / 1000) == D("4.25"), str(net_kg / 1000))
    # Inverse for display: CFT = kg / (kg/CFT)
    cft_back = net_kg / density_kg_per_cft
    check("4250 kg / 42.5 = 100 CFT", cft_back == D("100"), str(cft_back))
    # CBM (m³) = CFT / 35.3147
    cbm = cft_back / CFT_PER_M3
    check("100 CFT = 2.832 m³ (±0.001)", abs(cbm - D("2.832")) < D("0.001"), str(cbm))
    # Migration constant t/m³ -> kg/CFT
    check("1000/35.3147 = 28.3168 (±0.0001)",
          abs(KG_PER_CFT_FROM_T_PER_M3 - D("28.3168")) < D("0.0001"),
          str(KG_PER_CFT_FROM_T_PER_M3))
    # Round-trip: old 1.5 t/m³ -> kg/CFT -> same physical mass
    density_t_m3 = D("1.5")
    density_kgcft = density_t_m3 * KG_PER_CFT_FROM_T_PER_M3
    check("1.5 t/m³ ≈ 42.475 kg/CFT", abs(density_kgcft - D("42.475")) < D("0.01"), str(density_kgcft))


def test_density_entry_trap_guard():
    print("\n[9] Data-entry sanity: kg/m³ value would 35× over-bill (documents the fixed trap)")
    volume_cft = D("100")
    correct_density = D("42.5")     # kg/CFT  (correct)
    wrong_density = D("1500")       # kg/m³   (what the OLD hint told users to enter)
    correct_kg = volume_cft * correct_density
    wrong_kg = volume_cft * wrong_density
    ratio = wrong_kg / correct_kg
    # ~35.29x inflation — this is why the en/hi density labels were corrected to kg/CFT
    check("kg/m³ entry inflates ~35x", abs(ratio - D("35.294")) < D("0.01"), str(ratio))
    check("correct billing = 4.25 MT", (correct_kg / 1000) == D("4.25"))


def main() -> int:
    print("=" * 70)
    print("ACCOUNTING CALCULATION AUDIT — gst_service + weight/volume")
    print("=" * 70)
    for fn in (
        test_intra_state_basic,
        test_inter_state_rounding,
        test_non_gst_bill_of_supply,
        test_multiline_discount,
        test_freight_tcs,
        test_cgst_sgst_no_penny_lost,
        test_gst_split_decision,
        test_weight_volume_conversions,
        test_density_entry_trap_guard,
    ):
        fn()
    print("\n" + "=" * 70)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
