"""
Seed script to initialize the database with:
- Default company
- Admin user
- Financial year
- Stone crusher product catalog
- Chart of accounts
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import *
from app.utils.auth import hash_password
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.DATABASE_URL_SYNC)


def seed():
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        # Check if already seeded
        existing = db.query(Company).first()
        if existing:
            print("Database already seeded. Skipping.")
            return

        # 1. Create Company
        company = Company(
            name="Stone Crusher Enterprises",
            legal_name="Stone Crusher Enterprises Pvt. Ltd.",
            gstin="09AAAAA0000A1Z5",
            pan="AAAAA0000A",
            address_line1="Industrial Area, Phase-1",
            city="Haridwar",
            state="Uttarakhand",
            state_code="05",
            pincode="249401",
            phone="9897039915",
            email="info@stonecrushers.com",
            invoice_prefix="INV",
            quotation_prefix="QTN",
            purchase_prefix="PUR",
            current_fy_start=date(2025, 4, 1),
            current_fy_end=date(2026, 3, 31),
        )
        db.add(company)
        db.flush()

        # 2. Create Financial Year
        fy = FinancialYear(
            company_id=company.id,
            label="2025-26",
            start_date=date(2025, 4, 1),
            end_date=date(2026, 3, 31),
            is_active=True,
        )
        db.add(fy)
        db.flush()

        # 3. Create Admin User
        admin = User(
            company_id=company.id,
            username="admin",
            password_hash=hash_password("admin123"),
            full_name="Administrator",
            role="admin",
        )
        db.add(admin)

        # 4. Create Product Categories
        categories = {
            "Crushed Stone": [],
            "Sand": [],
            "Aggregates": [],
            "Raw Material": [],
        }
        cat_objects = {}
        for i, cat_name in enumerate(categories.keys()):
            cat = ProductCategory(
                company_id=company.id,
                name=cat_name,
                sort_order=i,
            )
            db.add(cat)
            db.flush()
            cat_objects[cat_name] = cat

        # 5. Create Products (Stone Crusher defaults)
        products_data = [
            # Crushed Stone (Gitti)
            ("Gitti 10mm", "G10", "2517", "MT", Decimal("750"), Decimal("5"), "Crushed Stone"),
            ("Gitti 12mm", "G12", "2517", "MT", Decimal("750"), Decimal("5"), "Crushed Stone"),
            ("Gitti 20mm", "G20", "2517", "MT", Decimal("700"), Decimal("5"), "Crushed Stone"),
            ("Gitti 25mm", "G25", "2517", "MT", Decimal("680"), Decimal("5"), "Crushed Stone"),
            ("Gitti 40mm", "G40", "2517", "MT", Decimal("650"), Decimal("5"), "Crushed Stone"),
            ("Gitti 63mm", "G63", "2517", "MT", Decimal("600"), Decimal("5"), "Crushed Stone"),
            # Sand
            ("M-Sand (Manufactured Sand)", "MSND", "2517", "MT", Decimal("500"), Decimal("5"), "Sand"),
            ("P-Sand (Plaster Sand)", "PSND", "2517", "MT", Decimal("550"), Decimal("5"), "Sand"),
            ("Stone Dust", "SDST", "2517", "MT", Decimal("300"), Decimal("5"), "Sand"),
            ("River Sand", "RSND", "2505", "MT", Decimal("800"), Decimal("5"), "Sand"),
            # Aggregates
            ("GSB (Granular Sub Base)", "GSB", "2517", "MT", Decimal("450"), Decimal("5"), "Aggregates"),
            ("WMM (Wet Mix Macadam)", "WMM", "2517", "MT", Decimal("500"), Decimal("5"), "Aggregates"),
            ("WBM (Water Bound Macadam)", "WBM", "2517", "MT", Decimal("480"), Decimal("5"), "Aggregates"),
            ("DLC (Dry Lean Concrete)", "DLC", "2517", "MT", Decimal("600"), Decimal("5"), "Aggregates"),
            # Raw Material
            ("Boulders", "BLDR", "2516", "MT", Decimal("200"), Decimal("5"), "Raw Material"),
            ("River Gravel", "RGVL", "2517", "MT", Decimal("250"), Decimal("5"), "Raw Material"),
        ]

        for name, code, hsn, unit, rate, gst_rate, cat_name in products_data:
            product = Product(
                company_id=company.id,
                category_id=cat_objects[cat_name].id,
                name=name,
                code=code,
                hsn_code=hsn,
                unit=unit,
                default_rate=rate,
                gst_rate=gst_rate,
            )
            db.add(product)

        # 6. Create Chart of Accounts
        account_groups_data = [
            ("Capital Account", None, "liability", True),
            ("Current Liabilities", None, "liability", True),
            ("Loans (Liability)", None, "liability", True),
            ("Fixed Assets", None, "asset", True),
            ("Current Assets", None, "asset", True),
            ("Investments", None, "asset", True),
            ("Sales Accounts", None, "income", True),
            ("Purchase Accounts", None, "expense", True),
            ("Direct Expenses", None, "expense", True),
            ("Indirect Expenses", None, "expense", True),
            ("Direct Incomes", None, "income", True),
            ("Indirect Incomes", None, "income", True),
        ]

        group_map = {}
        for i, (name, parent, gtype, is_sys) in enumerate(account_groups_data):
            grp = AccountGroup(
                company_id=company.id,
                name=name,
                parent_id=group_map.get(parent),
                group_type=gtype,
                is_system=is_sys,
                sort_order=i,
            )
            db.add(grp)
            db.flush()
            group_map[name] = grp.id

        # Sub-groups
        sub_groups = [
            ("Sundry Debtors", "Current Assets", "asset"),
            ("Sundry Creditors", "Current Liabilities", "liability"),
            ("Cash-in-hand", "Current Assets", "asset"),
            ("Bank Accounts", "Current Assets", "asset"),
            ("Duties & Taxes", "Current Liabilities", "liability"),
        ]
        for name, parent, gtype in sub_groups:
            grp = AccountGroup(
                company_id=company.id,
                name=name,
                parent_id=group_map[parent],
                group_type=gtype,
                is_system=True,
            )
            db.add(grp)
            db.flush()
            group_map[name] = grp.id

        # 7. Create Default Accounts
        default_accounts = [
            ("Sales - Crushed Stone", "Sales Accounts"),
            ("Sales - Sand", "Sales Accounts"),
            ("Sales - Aggregates", "Sales Accounts"),
            ("Purchase - Raw Material", "Purchase Accounts"),
            ("Cash", "Cash-in-hand"),
            ("CGST Input", "Duties & Taxes"),
            ("SGST Input", "Duties & Taxes"),
            ("IGST Input", "Duties & Taxes"),
            ("CGST Output", "Duties & Taxes"),
            ("SGST Output", "Duties & Taxes"),
            ("IGST Output", "Duties & Taxes"),
            ("TCS Payable", "Duties & Taxes"),
            ("Freight Charges", "Direct Expenses"),
            ("Loading Charges", "Direct Expenses"),
            ("Royalty Charges", "Direct Expenses"),
            ("Round Off", "Indirect Expenses"),
            ("Discount Allowed", "Indirect Expenses"),
            ("Interest Received", "Indirect Incomes"),
        ]
        for acc_name, grp_name in default_accounts:
            acc = Account(
                company_id=company.id,
                group_id=group_map[grp_name],
                name=acc_name,
                is_system=True,
            )
            db.add(acc)

        # 8. Create Number Sequences
        sequences = [
            ("token", "", True),
            ("sale_invoice", "INV", False),
            ("purchase_invoice", "PUR", False),
            ("quotation", "QTN", False),
            ("receipt", "RCP", False),
            ("payment_voucher", "PAY", False),
        ]
        for seq_type, prefix, reset_daily in sequences:
            seq = NumberSequence(
                company_id=company.id,
                fy_id=fy.id,
                sequence_type=seq_type,
                prefix=prefix,
                reset_daily=reset_daily,
            )
            db.add(seq)

        # 9. Create Serial Port Config
        sp_config = SerialPortConfig(
            company_id=company.id,
            port_name="COM1",
            baud_rate=9600,
            protocol="generic",
        )
        db.add(sp_config)

        # 10. Create Tally Config
        tally_config = TallyConfig(
            company_id=company.id,
            host="localhost",
            port=9000,
            tally_company_name="Stone Crusher Enterprises",
        )
        db.add(tally_config)

        db.commit()
        print("Database seeded successfully!")
        print(f"  Company: {company.name}")
        print(f"  Admin user: admin / admin123")
        print(f"  Financial Year: {fy.label}")
        print(f"  Products: {len(products_data)} stone crusher products")
        print(f"  Account Groups: {len(account_groups_data) + len(sub_groups)}")
        print(f"  Accounts: {len(default_accounts)}")


if __name__ == "__main__":
    seed()
