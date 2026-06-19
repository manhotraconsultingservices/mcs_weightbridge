"""
Bilingual label helper for PDF templates.
All labels render as "English / हिंदी" side-by-side.
"""

BILINGUAL: dict[str, tuple[str, str]] = {
    # Document headers
    "tax_invoice":       ("Tax Invoice",              "कर चालान"),
    "bill_of_supply":    ("Bill of Supply",           "आपूर्ति बिल"),
    "purchase_invoice":  ("Purchase Invoice",         "क्रय चालान"),
    "quotation":         ("Quotation",                "कोटेशन"),
    "delivery_challan":  ("Delivery Challan",         "डिलीवरी चालान"),
    "weighment_slip":    ("Weighment Slip",           "वजन पर्ची"),
    "gate_pass":         ("Gate Pass",                "गेट पास"),
    "credit_note":       ("Credit Note",              "क्रेडिट नोट"),
    "debit_note":        ("Debit Note",               "डेबिट नोट"),

    # Identifiers
    "invoice_no":        ("Invoice No.",              "चालान नंबर"),
    "date":              ("Date",                     "दिनांक"),
    "due_date":          ("Due Date",                 "देय तिथि"),
    "token_no":          ("Token No.",                "टोकन नंबर"),
    "gate_pass_no":      ("Gate Pass No.",            "गेट पास नंबर"),
    "place_of_supply":   ("Place of Supply",          "आपूर्ति स्थान"),
    "reference_no":      ("Reference No.",            "संदर्भ नंबर"),

    # Party details
    "buyer":             ("Buyer",                    "खरीदार"),
    "supplier":          ("Supplier",                 "आपूर्तिकर्ता"),
    "consignee":         ("Consignee",                "प्राप्तकर्ता"),
    "party_name":        ("Party Name",               "पार्टी नाम"),
    "gstin":             ("GSTIN",                    "GSTIN"),
    "pan":               ("PAN",                      "PAN"),
    "address":           ("Address",                  "पता"),
    "phone":             ("Phone",                    "फोन"),
    "state":             ("State",                    "राज्य"),
    "state_code":        ("State Code",               "राज्य कोड"),

    # Item table columns
    "sr_no":             ("Sr.",                      "क्र."),
    "description":       ("Description of Goods",    "माल विवरण"),
    "hsn_sac":           ("HSN/SAC",                 "HSN/SAC"),
    "quantity":          ("Quantity",                 "मात्रा"),
    "unit":              ("Unit",                     "इकाई"),
    "rate":              ("Rate",                     "दर"),
    "per":               ("Per",                      "प्रति"),
    "amount":            ("Amount",                   "राशि"),
    "discount":          ("Discount",                 "छूट"),
    "taxable_value":     ("Taxable Value",            "कर योग्य राशि"),

    # Weight / measurement
    "gross_weight":      ("Gross Weight",             "सकल वजन"),
    "tare_weight":       ("Tare Weight",              "टेयर वजन"),
    "net_weight":        ("Net Weight",               "शुद्ध वजन"),
    "vehicle_no":        ("Vehicle No.",              "वाहन नंबर"),
    "vehicle_type":      ("Vehicle Type",             "वाहन प्रकार"),
    "tyre_count":        ("Tyre Count",               "टायर संख्या"),
    "driver":            ("Driver",                   "ड्राइवर"),
    "transporter":       ("Transporter",              "ट्रांसपोर्टर"),
    "material":          ("Material",                 "सामग्री"),
    "measurement_method":("Method",                  "विधि"),
    "weighbridge":       ("Weighbridge",              "वेब्रिज"),
    "volume":            ("Volume",                   "मात्रा"),
    "bulk_density":      ("Bulk Density",             "बल्क घनत्व"),

    # Tax summary
    "subtotal":          ("Sub Total",                "उप कुल"),
    "cgst":              ("CGST",                     "CGST"),
    "sgst":              ("SGST",                     "SGST"),
    "igst":              ("IGST",                     "IGST"),
    "total_tax":         ("Total Tax",                "कुल कर"),
    "grand_total":       ("Grand Total",              "कुल योग"),
    "total_in_words":    ("Total Amount (in words)",  "कुल राशि (शब्दों में)"),
    "rupees_only":       ("Rupees Only",              "रुपये मात्र"),

    # Payment
    "payment_receipt":   ("Payment Receipt",          "भुगतान रसीद"),
    "payment_voucher":   ("Payment Voucher",          "भुगतान वाउचर"),
    "payment_status":    ("Payment Status",           "भुगतान स्थिति"),
    "payment_mode":      ("Payment Mode",             "भुगतान माध्यम"),
    "received_from":     ("Received From",            "प्राप्तकर्ता से"),
    "paid_to":           ("Paid To",                  "भुगतान किया"),
    "received_by":       ("Received By",              "प्राप्तकर्ता"),
    "bank_details":      ("Bank Details",             "बैंक विवरण"),
    "bank_name":         ("Bank Name",                "बैंक नाम"),
    "account_no":        ("Account No.",              "खाता नंबर"),
    "ifsc":              ("IFSC Code",                "IFSC कोड"),
    "branch":            ("Branch",                   "शाखा"),

    # Footer / signature
    "declaration":       ("Declaration",              "घोषणा"),
    "authorised_signatory": ("Authorised Signatory", "अधिकृत हस्ताक्षरकर्ता"),
    "for_company":       ("For",                      "के लिए"),
    "computer_generated":("Computer Generated Invoice — No Signature Required",
                          "कंप्यूटर जनरेटेड चालान — हस्ताक्षर की आवश्यकता नहीं"),

    # e-Invoice
    "irn":               ("IRN",                     "IRN"),
    "ack_no":            ("Ack No.",                 "Ack नंबर"),
    "ack_date":          ("Ack Date",                "Ack दिनांक"),

    # Misc
    "notes":             ("Notes",                   "नोट्स"),
    "total_qty":         ("Total Qty",               "कुल मात्रा"),
    "closing_balance":   ("Closing Balance",         "शेष बकाया"),
    "hsn_summary":       ("HSN/SAC Summary",         "HSN/SAC सारांश"),
    "taxable":           ("Taxable",                 "कर योग्य"),
    "tax_rate":          ("Tax Rate",                "कर दर"),
    "integrated_tax":    ("Integrated Tax",          "एकीकृत कर"),
    "central_tax":       ("Central Tax",             "केंद्रीय कर"),
    "state_ut_tax":      ("State/UT Tax",            "राज्य/संघ कर"),
}


def bl(key: str) -> str:
    """Return 'English / हिंदी' label for a given key.
    Falls back to the key itself if not found.
    """
    pair = BILINGUAL.get(key)
    if pair is None:
        return key
    en, hi = pair
    return f"{en} / {hi}"
