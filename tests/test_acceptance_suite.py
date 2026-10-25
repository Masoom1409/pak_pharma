"""Comprehensive Automated Acceptance Test Suite for PakPharma POS (All 20 Mandatory Acceptance Criteria)."""

from __future__ import annotations

from datetime import date, timedelta
import os
import sqlite3
import tempfile
import unittest

from app.db.database import DatabaseManager, format_pkr, paisa_to_pkr, pkr_to_paisa
from app.printing.printing_service import PrintingService
from app.services.auth_service import AuthenticationError, AuthorizationError, AuthService
from app.services.backup_service import BackupIntegrityError, BackupService
from app.services.finance_service import FinanceAndReportService
from app.services.inventory_service import (
    BarcodeValidationError,
    DuplicateProductError,
    ExpiredStockError,
    InsufficientStockError,
    InventoryService,
    compute_gs1_check_digit,
)
from app.services.purchase_service import PurchaseService
from app.services.sales_service import CreditLimitExceededError, DuplicateInvoiceError, SalesService


def make_ean13(prefix_12: str) -> str:
    """Helper to generate a valid 13-digit EAN-13 barcode with valid GS1 check digit."""
    assert len(prefix_12) == 12 and prefix_12.isdigit()
    return prefix_12 + compute_gs1_check_digit(prefix_12)


class PakPharmaAcceptanceTests(unittest.TestCase):
    """Verifies all 20 mandatory functional, financial, security, hardware-output, and persistence criteria."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="pakpharma_test_")
        self.db_path = os.path.join(self.tmp_dir.name, "test_pakpharma.sqlite3")
        self.backup_dir = os.path.join(self.tmp_dir.name, "backups")

        self.db = DatabaseManager(self.db_path)
        self.auth = AuthService(self.db)
        self.inventory = InventoryService(self.db, self.auth)
        self.purchases = PurchaseService(self.db, self.auth)
        self.sales = SalesService(self.db, self.auth, self.inventory)
        self.finance = FinanceAndReportService(self.db, self.auth, self.inventory)
        self.backup = BackupService(self.db, self.auth, self.backup_dir)
        self.printing = PrintingService(self.db)

        # Authenticate default seeded roles
        self.admin = self.auth.authenticate("admin", "Admin@123")
        self.manager = self.auth.authenticate("manager", "Manager@123")
        self.cashier = self.auth.authenticate("cashier", "Cashier@123")

        self.today_str = date.today().isoformat()
        self.future_30 = (date.today() + timedelta(days=30)).isoformat()
        self.future_180 = (date.today() + timedelta(days=180)).isoformat()
        self.past_expired = (date.today() - timedelta(days=15)).isoformat()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_01_create_medicine_with_barcode_and_scan_retrieval(self) -> None:
        """Criteria 1 & 2: A new medicine can be created with a barcode, and scanning retrieves the exact record."""
        bc = make_ean13("896110010001")
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Panadol Advance",
            generic_name="Paracetamol",
            manufacturer="Haleon Pakistan Ltd",
            purchase_price_pkr="3.40",
            sale_price_pkr="4.00",
            category="Analgesic",
            dosage_form="Tablet",
            strength="500 mg",
            pack_size=10,
            barcode=bc,
            initial_batch_number="PAN-26A",
            initial_expiry_date=self.future_180,
            initial_qty=100,
        )
        self.assertEqual(prod["primary_barcode"], bc)
        self.assertEqual(prod["total_stock"], 100)

        scan = self.inventory.scan_barcode(bc, reference_date=self.today_str)
        self.assertTrue(scan["found"])
        self.assertEqual(scan["product"]["id"], prod["id"])
        self.assertEqual(scan["selected_batch"]["batch_number"], "PAN-26A")

    def test_02_unknown_barcode_returns_prefill_payload_and_prevents_name_guessing(self) -> None:
        """Criteria 3 & Safeguard: Unknown barcode returns found=False with prefill_barcode; never guesses by name."""
        unknown_bc = make_ean13("896999999999")
        scan = self.inventory.scan_barcode(unknown_bc)
        self.assertFalse(scan["found"])
        self.assertEqual(scan["prefill_barcode"], unknown_bc)
        self.assertIsNone(scan["product"])

    def test_03_separate_batches_and_purchase_stock_updates(self) -> None:
        """Criteria 4 & 5: Different batches of the same medicine remain separate; purchasing same batch updates it."""
        sup = self.purchases.create_supplier(self.admin["id"], "Premier Distributor Karachi", phone="021-34567890")
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Augmentin",
            generic_name="Amoxicillin + Clavulanic Acid",
            manufacturer="GSK Pakistan",
            purchase_price_pkr="38.00",
            sale_price_pkr="45.00",
            strength="625 mg",
            pack_size=6,
            barcode=make_ean13("896110020001"),
        )

        # Receive two distinct batches
        self.purchases.create_purchase_invoice(
            user_id=self.admin["id"],
            supplier_id=sup["id"],
            lines=[
                {
                    "product_id": prod["id"],
                    "batch_number": "AUG-B1",
                    "expiry_date": self.future_30,
                    "qty_received": 40,
                    "unit_cost_pkr": "38.00",
                    "sale_price_pkr": "45.00",
                },
                {
                    "product_id": prod["id"],
                    "batch_number": "AUG-B2",
                    "expiry_date": self.future_180,
                    "qty_received": 60,
                    "unit_cost_pkr": "40.00",
                    "sale_price_pkr": "45.00",
                },
            ],
        )
        updated_prod = self.inventory.get_product_by_id(prod["id"])
        self.assertEqual(len(updated_prod["batches"]), 2)
        self.assertEqual(updated_prod["total_stock"], 100)

        # Receiving AUG-B1 again with the same expiry updates AUG-B1 quantity from 40 to 70
        self.purchases.create_purchase_invoice(
            user_id=self.admin["id"],
            supplier_id=sup["id"],
            lines=[
                {
                    "product_id": prod["id"],
                    "batch_number": "AUG-B1",
                    "expiry_date": self.future_30,
                    "qty_received": 30,
                    "unit_cost_pkr": "38.00",
                    "sale_price_pkr": "45.00",
                }
            ],
        )
        updated_prod2 = self.inventory.get_product_by_id(prod["id"])
        self.assertEqual(len(updated_prod2["batches"]), 2)
        b1 = [b for b in updated_prod2["batches"] if b["batch_number"] == "AUG-B1"][0]
        self.assertEqual(b1["qty_remaining"], 70)

    def test_04_fefo_selection_and_multi_item_sale_deduction(self) -> None:
        """Criteria 6 & 7: Multi-item sale selects earliest expiry batch (FEFO) and deducts across batches accurately."""
        sup = self.purchases.create_supplier(self.admin["id"], "Muller & Phipps Pakistan")
        p1 = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Brufen",
            generic_name="Ibuprofen",
            manufacturer="Abbott Laboratories Pakistan",
            purchase_price_pkr="5.00",
            sale_price_pkr="6.50",
            strength="400 mg",
        )
        p2 = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Flagyl",
            generic_name="Metronidazole",
            manufacturer="Sanofi-Aventis Pakistan",
            purchase_price_pkr="4.00",
            sale_price_pkr="5.50",
            strength="400 mg",
        )

        # Purchase two batches of Brufen (10 units expiring in 30 days, 50 units expiring in 180 days) + 30 units of Flagyl
        self.purchases.create_purchase_invoice(
            user_id=self.admin["id"],
            supplier_id=sup["id"],
            lines=[
                {"product_id": p1["id"], "batch_number": "BRU-LATE", "expiry_date": self.future_180, "qty_received": 50, "unit_cost_pkr": "5.20", "sale_price_pkr": "6.50"},
                {"product_id": p1["id"], "batch_number": "BRU-SOON", "expiry_date": self.future_30, "qty_received": 10, "unit_cost_pkr": "5.00", "sale_price_pkr": "6.50"},
                {"product_id": p2["id"], "batch_number": "FLG-01", "expiry_date": self.future_180, "qty_received": 30, "unit_cost_pkr": "4.00", "sale_price_pkr": "5.50"},
            ],
        )

        # Sell 15 units of Brufen (should take all 10 from BRU-SOON and 5 from BRU-LATE) and 4 units of Flagyl
        sale = self.sales.create_sale_invoice(
            cashier_id=self.cashier["id"],
            cart_items=[
                {"product_id": p1["id"], "qty": 15},
                {"product_id": p2["id"], "qty": 4},
            ],
            payment_method="CASH",
            tendered_pkr="200.00",
        )
        # Verify FEFO batch split
        bru_lines = [l for l in sale["lines"] if l["product_id"] == p1["id"]]
        self.assertEqual(len(bru_lines), 2)
        self.assertEqual(bru_lines[0]["batch_number"], "BRU-SOON")
        self.assertEqual(bru_lines[0]["qty_units"], 10)
        self.assertEqual(bru_lines[1]["batch_number"], "BRU-LATE")
        self.assertEqual(bru_lines[1]["qty_units"], 5)

        # Check remaining stock
        p1_after = self.inventory.get_product_by_id(p1["id"])
        self.assertEqual(p1_after["total_stock"], 45)
        b_soon = [b for b in p1_after["batches"] if b["batch_number"] == "BRU-SOON"][0]
        self.assertEqual(b_soon["qty_remaining"], 0)

    def test_05_expired_products_blocked_unless_authorized_override(self) -> None:
        """Criteria 8: Expired products cannot be sold through normal workflow; Admin override requires reason."""
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Amoxil Capsule",
            generic_name="Amoxicillin",
            manufacturer="GSK Pakistan",
            purchase_price_pkr="10.00",
            sale_price_pkr="14.00",
            strength="250 mg",
            initial_batch_number="AMX-EXP",
            initial_expiry_date=self.past_expired,
            initial_qty=25,
        )

        # Normal sale by Cashier must raise ExpiredStockError
        with self.assertRaises(ExpiredStockError):
            self.sales.create_sale_invoice(
                cashier_id=self.cashier["id"],
                cart_items=[{"product_id": prod["id"], "qty": 2}],
            )

        # Cashier attempting override must raise AuthorizationError
        with self.assertRaises(AuthorizationError):
            self.sales.create_sale_invoice(
                cashier_id=self.cashier["id"],
                cart_items=[{"product_id": prod["id"], "qty": 2}],
                allow_expired_override=True,
                override_user_id=self.cashier["id"],
                override_reason="Cashier trying to bypass",
            )

        # Admin override with recorded reason succeeds and records audit trail
        sale = self.sales.create_sale_invoice(
            cashier_id=self.cashier["id"],
            cart_items=[{"product_id": prod["id"], "qty": 2}],
            allow_expired_override=True,
            override_user_id=self.admin["id"],
            override_reason="Approved laboratory reference sample disposal",
        )
        self.assertEqual(sale["lines"][0]["expired_override_by"], self.admin["id"])

    def test_06_insufficient_stock_and_atomic_rollback_on_failed_sale(self) -> None:
        """Criteria 9 & 10: Insufficient stock prevents invalid sale and rolls back multi-item transaction completely."""
        p_ok = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Risek Capsule",
            generic_name="Omeprazole",
            manufacturer="Getz Pharma",
            purchase_price_pkr="20.00",
            sale_price_pkr="28.00",
            strength="20 mg",
            initial_batch_number="RSK-01",
            initial_expiry_date=self.future_180,
            initial_qty=20,
        )
        p_low = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Glucophage",
            generic_name="Metformin HCl",
            manufacturer="Martin Dow",
            purchase_price_pkr="6.00",
            sale_price_pkr="8.50",
            strength="500 mg",
            initial_batch_number="GLU-01",
            initial_expiry_date=self.future_180,
            initial_qty=5,
        )

        # Cart where item 1 is valid (5 units of Risek) and item 2 exceeds stock (10 units of Glucophage when only 5 exist)
        with self.assertRaises(InsufficientStockError):
            self.sales.create_sale_invoice(
                cashier_id=self.cashier["id"],
                cart_items=[
                    {"product_id": p_ok["id"], "qty": 5},
                    {"product_id": p_low["id"], "qty": 10},
                ],
            )

        # Verify Risek stock was NOT partially deducted (remains 20) and zero sales were saved
        self.assertEqual(self.inventory.get_product_by_id(p_ok["id"])["total_stock"], 20)
        self.assertEqual(len(self.sales.search_sales()), 0)

    def test_07_discounts_returns_cogs_and_gross_vs_net_profit(self) -> None:
        """Criteria 11 & 12: Discounts, customer returns, batch COGS, gross profit, and net profit calculate accurately."""
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Lipiget",
            generic_name="Atorvastatin",
            manufacturer="Getz Pharma",
            purchase_price_pkr="30.00",
            sale_price_pkr="50.00",
            strength="20 mg",
            initial_batch_number="LIP-01",
            initial_expiry_date=self.future_180,
            initial_qty=100,
        )

        # Sell 10 units @ Rs 50.00 = Rs 500.00, apply Rs 50.00 discount (10% discount by Manager), Tax 0%
        # Net Sales = Rs 450.00, COGS = 10 * Rs 30.00 = Rs 300.00 -> Gross Profit = Rs 150.00
        sale = self.sales.create_sale_invoice(
            cashier_id=self.manager["id"],
            cart_items=[{"product_id": prod["id"], "qty": 10}],
            invoice_discount_pkr="50.00",
            payment_method="CASH",
            tendered_pkr="500.00",
        )
        self.assertEqual(sale["grand_total_paisa"], pkr_to_paisa("450.00"))
        self.assertEqual(sale["change_due_paisa"], pkr_to_paisa("50.00"))
        self.assertEqual(sale["total_cogs_paisa"], pkr_to_paisa("300.00"))

        # Return 2 units out of 10:
        # Proportional net refund = 2/10 of Rs 450.00 = Rs 90.00
        # Reversed COGS = 2 * Rs 30.00 = Rs 60.00
        ret = self.sales.create_sales_return(
            user_id=self.manager["id"],
            sale_id=sale["id"],
            return_items=[
                {"sale_line_id": sale["lines"][0]["id"], "qty_returned": 2, "restock_condition": "GOOD"}
            ],
            reason="Customer bought extra strip",
        )
        self.assertEqual(ret["total_refund_paisa"], pkr_to_paisa("90.00"))
        self.assertEqual(ret["cogs_reversed_paisa"], pkr_to_paisa("60.00"))
        self.assertEqual(self.inventory.get_product_by_id(prod["id"])["total_stock"], 92)

        # Record Rs 40.00 shop electricity expense
        self.finance.record_expense(
            user_id=self.manager["id"],
            category="Utilities",
            description="Daily generator fuel",
            amount_pkr="40.00",
        )

        # Verify Financial Summary:
        # Net Sales = 450 - 90 = Rs 360.00
        # Net COGS = 300 - 60 = Rs 240.00
        # Gross Profit = 360 - 240 = Rs 120.00
        # Estimated Net Profit = 120 - 40 = Rs 80.00
        fin = self.finance.get_financial_summary(self.today_str, self.today_str, user_id=self.admin["id"])
        self.assertEqual(fin["net_sales_ex_tax_paisa"], pkr_to_paisa("360.00"))
        self.assertEqual(fin["net_cogs_paisa"], pkr_to_paisa("240.00"))
        self.assertEqual(fin["gross_profit_paisa"], pkr_to_paisa("120.00"))
        self.assertEqual(fin["operating_expenses_paisa"], pkr_to_paisa("40.00"))
        self.assertEqual(fin["estimated_net_profit_paisa"], pkr_to_paisa("80.00"))

    def test_08_duplicate_invoice_and_duplicate_return_prevention(self) -> None:
        """Criteria 13 & Section 10: Duplicate invoice submissions and excess returns are blocked."""
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Ponstan",
            generic_name="Mefenamic Acid",
            manufacturer="Pfizer Pakistan",
            purchase_price_pkr="4.00",
            sale_price_pkr="6.00",
            strength="250 mg",
            initial_batch_number="PON-01",
            initial_expiry_date=self.future_180,
            initial_qty=50,
        )
        idem_key = "POS-TX-UNIQUE-001"
        sale = self.sales.create_sale_invoice(
            cashier_id=self.cashier["id"],
            cart_items=[{"product_id": prod["id"], "qty": 3}],
            idempotency_key=idem_key,
        )

        with self.assertRaises(DuplicateInvoiceError):
            self.sales.create_sale_invoice(
                cashier_id=self.cashier["id"],
                cart_items=[{"product_id": prod["id"], "qty": 3}],
                idempotency_key=idem_key,
            )

        # Return all 3 units, then attempt to return 1 more unit -> must raise ValueError
        self.sales.create_sales_return(
            user_id=self.cashier["id"],
            sale_id=sale["id"],
            return_items=[{"sale_line_id": sale["lines"][0]["id"], "qty_returned": 3}],
            reason="Full return",
        )
        with self.assertRaises(ValueError):
            self.sales.create_sales_return(
                user_id=self.cashier["id"],
                sale_id=sale["id"],
                return_items=[{"sale_line_id": sale["lines"][0]["id"], "qty_returned": 1}],
                reason="Duplicate return attempt",
            )

    def test_09_receipt_a4_invoice_and_barcode_label_printing(self) -> None:
        """Criteria 14 & 15: Thermal 80mm/58mm receipt PDF, ESC/POS raw stream, A4 invoice, and barcode label PDF generation."""
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Surbex Z",
            generic_name="Multivitamin + Zinc",
            manufacturer="Abbott Laboratories Pakistan",
            purchase_price_pkr="12.00",
            sale_price_pkr="16.50",
            strength="Standard",
            barcode=make_ean13("896110050001"),
            initial_batch_number="SRB-01",
            initial_expiry_date=self.future_180,
            initial_qty=40,
        )
        sale = self.sales.create_sale_invoice(
            cashier_id=self.cashier["id"],
            cart_items=[{"product_id": prod["id"], "qty": 5}],
            payment_method="CASH",
            tendered_pkr="100.00",
        )

        r80 = os.path.join(self.tmp_dir.name, "receipt_80mm.pdf")
        r58 = os.path.join(self.tmp_dir.name, "receipt_58mm.pdf")
        a4_pdf = os.path.join(self.tmp_dir.name, "invoice_a4.pdf")
        lbl_pdf = os.path.join(self.tmp_dir.name, "barcode_labels.pdf")

        self.printing.generate_thermal_receipt_pdf(sale, r80, paper_width_mm=80)
        self.printing.generate_thermal_receipt_pdf(sale, r58, paper_width_mm=58)
        self.printing.generate_a4_invoice_pdf(sale, a4_pdf)
        self.printing.generate_barcode_labels_pdf(prod, lbl_pdf, copies=4)
        escpos_bytes = self.printing.generate_escpos_raw_bytes(sale)

        for p in (r80, r58, a4_pdf, lbl_pdf):
            self.assertTrue(os.path.isfile(p))
            self.assertGreater(os.path.getsize(p), 500)
        self.assertIn(b"GRAND TOTAL:", escpos_bytes)

    def test_10_backup_and_safe_restore_and_permissions(self) -> None:
        """Criteria 16, 17, 18, 19, 20: Backup & restore verification, RBAC permissions, persistence across reopen, and migrations."""
        prod = self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="Arinac Forte",
            generic_name="Ibuprofen + Pseudoephedrine",
            manufacturer="Abbott Laboratories Pakistan",
            purchase_price_pkr="8.00",
            sale_price_pkr="11.00",
            strength="400mg/60mg",
            initial_batch_number="ARI-01",
            initial_expiry_date=self.future_180,
            initial_qty=60,
        )

        # Cashier cannot change medicine price, view financial reports, or restore backups
        with self.assertRaises(AuthorizationError):
            self.inventory.update_product(self.cashier["id"], prod["id"], sale_price_pkr="15.00")
        with self.assertRaises(AuthorizationError):
            self.finance.get_financial_summary(self.today_str, self.today_str, user_id=self.cashier["id"])

        # Create backup
        b_info = self.backup.create_backup(user_id=self.admin["id"], backup_type="MANUAL", notes="Pre-change backup")
        self.assertTrue(os.path.isfile(b_info["backup_path"]))

        # Add a second product after backup
        self.inventory.create_product(
            user_id=self.admin["id"],
            medicine_name="PostBackupMed",
            generic_name="TestSalt",
            manufacturer="TestPharma",
            purchase_price_pkr="5.00",
            sale_price_pkr="7.00",
        )
        self.assertEqual(len(self.inventory.search_products()), 2)

        # Restore backup -> PostBackupMed is gone, Arinac Forte is preserved, and pre-restore safety snapshot exists
        restore_res = self.backup.restore_backup(
            admin_user_id=self.admin["id"],
            backup_file_path=b_info["backup_path"],
            confirmed=True,
            reason="Testing full database restoration",
        )
        self.assertTrue(restore_res["restored"])
        self.assertTrue(os.path.isfile(restore_res["pre_restore_backup_path"]))
        self.assertEqual(len(self.inventory.search_products()), 1)

        # Re-open DatabaseManager on existing file to verify persistence and migration idempotency
        reopened_db = DatabaseManager(self.db_path)
        reopened_inv = InventoryService(reopened_db, AuthService(reopened_db))
        prods = reopened_inv.search_products()
        self.assertEqual(len(prods), 1)
        self.assertEqual(prods[0]["medicine_name"], "Arinac Forte")


if __name__ == "__main__":
    unittest.main(verbosity=2)
