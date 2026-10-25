"""Sales & POS Billing, Customers, Credit Sales, Split Payments, Voiding, and Customer Returns Service."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import sqlite3
from typing import Any

from app.db.database import DatabaseManager, pkr_to_paisa
from app.services.auth_service import AuthService
from app.services.inventory_service import InventoryService


class CreditLimitExceededError(ValueError):
    """Raised when a credit sale would push a customer's balance above their configured credit limit."""


class DuplicateInvoiceError(ValueError):
    """Raised when a duplicate idempotency_key is submitted to prevent double billing."""


class SalesService:
    """Manages POS billing, FEFO batch deduction, split payments, credit sales, returns, and customer ledgers."""

    def __init__(self, db: DatabaseManager, auth: AuthService, inventory: InventoryService) -> None:
        self.db = db
        self.auth = auth
        self.inventory = inventory

    def create_customer(
        self,
        user_id: int,
        name: str,
        phone: str = "",
        address: str = "",
        cnic: str = "",
        credit_limit_pkr: Decimal | int | float | str = 0,
        opening_balance_pkr: Decimal | int | float | str = 0,
        notes: str = "",
    ) -> dict[str, Any]:
        """Create a customer profile for credit sales and invoice history."""
        actor = self.auth.get_user(user_id)
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Customer name is required.")

        limit_paisa = pkr_to_paisa(credit_limit_pkr)
        open_paisa = pkr_to_paisa(opening_balance_pkr)
        if limit_paisa < 0:
            raise ValueError("Credit limit cannot be negative.")

        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            next_c = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM customers").fetchone()
            cust_code = f"CUS-{int(next_c['next_id']):04d}"
            cur = conn.execute(
                """
                INSERT INTO customers (
                    customer_code, name, phone, address, cnic,
                    credit_limit_paisa, opening_balance_paisa, current_balance_paisa,
                    is_active, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    cust_code,
                    clean_name,
                    phone.strip(),
                    address.strip(),
                    cnic.strip(),
                    limit_paisa,
                    open_paisa,
                    open_paisa,
                    notes.strip(),
                    now_iso,
                ),
            )
            cid = int(cur.lastrowid)
            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CREATE_CUSTOMER",
                entity_type="customers",
                entity_id=str(cid),
                reason=f"Created customer {clean_name} ({cust_code})",
            )
        return self.get_customer(cid)

    def get_customer(self, customer_id: int) -> dict[str, Any]:
        """Retrieve customer record by ID."""
        with self.db.read_only() as conn:
            row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
            if not row:
                raise ValueError(f"Customer ID {customer_id} not found.")
            return dict(row)

    def list_customers(self, query: str = "") -> list[dict[str, Any]]:
        """List customers optionally filtered by name, phone, or code."""
        with self.db.read_only() as conn:
            if query and query.strip():
                q = f"%{query.strip()}%"
                rows = conn.execute(
                    "SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? OR customer_code LIKE ? ORDER BY name",
                    (q, q, q),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    def create_sale_invoice(
        self,
        cashier_id: int,
        cart_items: list[dict[str, Any]],
        payment_method: str = "CASH",
        tendered_pkr: Decimal | int | float | str | None = None,
        split_payments: list[dict[str, Any]] | None = None,
        invoice_discount_pkr: Decimal | int | float | str = 0,
        tax_rate_bps: int | None = None,
        customer_id: int | None = None,
        customer_name_walkin: str = "Walk-in Customer",
        invoice_date: str | None = None,
        idempotency_key: str | None = None,
        allow_expired_override: bool = False,
        override_user_id: int | None = None,
        override_reason: str = "",
        doctor_name: str = "",
        prescription_ref: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Process a complete POS sale inside a single atomic ACID database transaction.

        - Supports unit sales (`sale_unit_type='UNIT'`) and full-pack sales (`sale_unit_type='PACK'`,
          which automatically multiplies quantity by `product.pack_size`).
        - Allocates batches using strict FEFO rules (`inventory.allocate_fefo_batches`).
        - Enforces role-based discount ceilings (`auth.check_discount_limit`).
        - Prevents duplicate submissions via `idempotency_key`.
        - Supports Cash, Card, EasyPaisa, JazzCash, Bank Transfer, Credit, and Split payments.
        - Calculates exact Cost of Goods Sold (`total_cogs_paisa`) from the specific batches deducted.
        """
        cashier = self.auth.require_permission(cashier_id, "POS_BILLING")
        if not cart_items:
            raise ValueError("Cannot complete sale: invoice cart is empty.")

        inv_date = invoice_date or date.today().isoformat()
        date.fromisoformat(inv_date)
        now_iso = datetime.now().isoformat(timespec="seconds")

        if tax_rate_bps is None:
            tax_rate_bps = int(self.db.get_setting("default_tax_rate_bps", "0"))
        if tax_rate_bps < 0:
            raise ValueError("Tax rate cannot be negative.")

        inv_discount_paisa = pkr_to_paisa(invoice_discount_pkr)
        if inv_discount_paisa < 0:
            raise ValueError("Discount cannot be negative.")

        if allow_expired_override:
            if self.db.get_setting("allow_admin_expired_override", "1") != "1":
                from app.services.inventory_service import ExpiredStockError
                raise ExpiredStockError("Expired stock override is disabled in store settings.")
            if not (override_reason or "").strip():
                from app.services.inventory_service import ExpiredStockError
                raise ExpiredStockError("A written reason is required to override expired stock restriction.")
            self.auth.require_permission(
                override_user_id or cashier_id,
                "EXPIRED_OVERRIDE",
                reason=f"Expired override requested on sale: {override_reason}",
            )

        with self.db.transaction() as conn:
            # 1. Check idempotency key to prevent duplicate invoice creation
            if idempotency_key and idempotency_key.strip():
                dup_sale = conn.execute(
                    "SELECT id, invoice_number FROM sales WHERE idempotency_key = ?",
                    (idempotency_key.strip(),),
                ).fetchone()
                if dup_sale:
                    raise DuplicateInvoiceError(
                        f"Duplicate invoice submission blocked (Idempotency Key '{idempotency_key}' "
                        f"already processed as {dup_sale['invoice_number']})."
                    )

            next_s = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM sales").fetchone()
            invoice_number = f"INV-{int(next_s['next_id']):06d}"

            # 2. Aggregate cart items and allocate FEFO batches
            allocated_sale_lines: list[dict[str, Any]] = []
            subtotal_paisa = 0
            total_line_discounts_paisa = 0
            total_cogs_paisa = 0

            for idx, item in enumerate(cart_items, start=1):
                product_id = int(item["product_id"])
                prod = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
                if not prod:
                    raise ValueError(f"Cart line {idx}: Product ID {product_id} does not exist.")
                if not prod["is_active"]:
                    raise ValueError(f"Cart line {idx}: Product '{prod['medicine_name']}' is deactivated.")

                sale_unit_type = (item.get("sale_unit_type") or "UNIT").upper()
                raw_qty = int(item.get("qty", 0))
                if raw_qty <= 0:
                    raise ValueError(f"Cart line {idx} ({prod['medicine_name']}): Quantity must be greater than zero.")

                pack_size = int(prod["pack_size"])
                qty_units = raw_qty * pack_size if sale_unit_type == "PACK" else raw_qty

                # Optional custom unit price (requires CHANGE_PRICES if different from default/batch price)
                custom_unit_price_pkr = item.get("unit_price_pkr")
                line_discount_paisa = pkr_to_paisa(item.get("line_discount_pkr", 0))
                if line_discount_paisa < 0:
                    raise ValueError(f"Cart line {idx}: Line discount cannot be negative.")

                specific_batch_id = item.get("batch_id")
                batch_allocations = self.inventory.allocate_fefo_batches(
                    conn=conn,
                    product_id=product_id,
                    required_qty=qty_units,
                    reference_date=inv_date,
                    allow_expired_override=allow_expired_override,
                    override_user_id=override_user_id or cashier_id,
                    override_reason=override_reason,
                    specific_batch_id=int(specific_batch_id) if specific_batch_id is not None else None,
                )

                # Distribute line_discount_paisa proportionally across split batch allocations if multiple batches used
                remaining_line_disc = line_discount_paisa
                for b_idx, alloc in enumerate(batch_allocations):
                    alloc_qty = int(alloc["qty_allocated"])
                    default_u_price = int(alloc["sale_price_paisa"]) or int(prod["default_sale_price_paisa"])
                    if custom_unit_price_pkr is not None:
                        u_price_paisa = pkr_to_paisa(custom_unit_price_pkr)
                        if u_price_paisa != default_u_price:
                            self.auth.require_permission(
                                cashier_id,
                                "CHANGE_PRICES",
                                reason=f"Changed sale price on {prod['medicine_name']}",
                            )
                    else:
                        u_price_paisa = default_u_price

                    if b_idx == len(batch_allocations) - 1:
                        alloc_disc = remaining_line_disc
                    else:
                        alloc_disc = (line_discount_paisa * alloc_qty) // qty_units
                        remaining_line_disc -= alloc_disc

                    gross_line = alloc_qty * u_price_paisa
                    if alloc_disc > gross_line:
                        raise ValueError(f"Cart line {idx}: Discount exceeds item price.")
                    net_line = gross_line - alloc_disc
                    u_cost_paisa = int(alloc["purchase_cost_paisa"])
                    line_cogs = alloc_qty * u_cost_paisa

                    subtotal_paisa += net_line
                    total_line_discounts_paisa += alloc_disc
                    total_cogs_paisa += line_cogs

                    # Deduct stock from batch immediately inside transaction
                    batch_row = conn.execute(
                        "SELECT qty_remaining FROM batches WHERE id = ?",
                        (alloc["batch_id"],),
                    ).fetchone()
                    qty_before = int(batch_row["qty_remaining"])
                    qty_after = qty_before - alloc_qty
                    if qty_after < 0:
                        raise ValueError(f"Batch {alloc['batch_number']} would become negative.")

                    conn.execute(
                        "UPDATE batches SET qty_remaining = ?, updated_at = ? WHERE id = ?",
                        (qty_after, now_iso, alloc["batch_id"]),
                    )

                    conn.execute(
                        """
                        INSERT INTO stock_movements (
                            timestamp, product_id, batch_id, movement_type, qty_change,
                            qty_before, qty_after, unit_cost_paisa, reference_type, reference_id,
                            user_id, notes
                        ) VALUES (?, ?, ?, 'SALE_DEDUCTION', ?, ?, ?, ?, 'SALE', ?, ?, ?)
                        """,
                        (
                            now_iso,
                            product_id,
                            alloc["batch_id"],
                            -alloc_qty,
                            qty_before,
                            qty_after,
                            u_cost_paisa,
                            invoice_number,
                            cashier_id,
                            f"POS Sale {invoice_number}",
                        ),
                    )

                    allocated_sale_lines.append(
                        {
                            "product_id": product_id,
                            "batch_id": alloc["batch_id"],
                            "batch_number": alloc["batch_number"],
                            "expiry_date": alloc["expiry_date"],
                            "sale_unit_type": sale_unit_type,
                            "qty_units": alloc_qty,
                            "unit_price_paisa": u_price_paisa,
                            "unit_cost_paisa": u_cost_paisa,
                            "line_discount_paisa": alloc_disc,
                            "line_total_paisa": net_line,
                            "expired_override_by": alloc["expired_override_by"],
                            "expired_override_reason": alloc["expired_override_reason"],
                        }
                    )

            # 3. Validate total discount against role limit
            gross_before_all_discounts = subtotal_paisa + total_line_discounts_paisa
            total_combined_discount = total_line_discounts_paisa + inv_discount_paisa
            if inv_discount_paisa > subtotal_paisa:
                raise ValueError("Invoice-level discount cannot exceed subtotal.")
            self.auth.check_discount_limit(cashier_id, gross_before_all_discounts, total_combined_discount)

            net_after_discount_paisa = subtotal_paisa - inv_discount_paisa
            tax_paisa = (net_after_discount_paisa * int(tax_rate_bps) + 5000) // 10_000
            grand_total_paisa = net_after_discount_paisa + tax_paisa

            # 4. Handle payment methods (Cash, Card, Mobile Wallet, Credit, or Split)
            clean_method = (payment_method or "CASH").upper()
            payment_records: list[tuple[str, int, str]] = []  # (method, amount_paisa, ref)

            if split_payments:
                clean_method = "SPLIT"
                total_split_paid = 0
                credit_portion = 0
                for sp in split_payments:
                    sp_m = (sp.get("method") or "CASH").upper()
                    sp_amt = pkr_to_paisa(sp["amount_pkr"])
                    if sp_amt < 0:
                        raise ValueError("Split payment amount cannot be negative.")
                    if sp_m == "CREDIT":
                        credit_portion += sp_amt
                    elif sp_amt > 0:
                        total_split_paid += sp_amt
                        payment_records.append((sp_m, sp_amt, sp.get("reference_no") or ""))
                if total_split_paid + credit_portion < grand_total_paisa:
                    raise ValueError(
                        f"Split payments total ({total_split_paid + credit_portion} paisa) is less than grand total ({grand_total_paisa} paisa)."
                    )
                paid_paisa = total_split_paid
                change_due_paisa = max(0, (total_split_paid + credit_portion) - grand_total_paisa)
                credit_due_paisa = credit_portion
            elif clean_method == "CREDIT":
                paid_paisa = pkr_to_paisa(tendered_pkr) if tendered_pkr is not None else 0
                if paid_paisa > grand_total_paisa:
                    raise ValueError("Initial payment on credit sale cannot exceed grand total.")
                change_due_paisa = 0
                credit_due_paisa = grand_total_paisa - paid_paisa
                if paid_paisa > 0:
                    payment_records.append(("CASH", paid_paisa, "Down payment on credit sale"))
            else:
                if tendered_pkr is not None:
                    tendered_paisa = pkr_to_paisa(tendered_pkr)
                else:
                    tendered_paisa = grand_total_paisa
                if tendered_paisa < grand_total_paisa:
                    raise ValueError(
                        f"Tendered amount ({tendered_paisa/100:.2f}) is less than grand total ({grand_total_paisa/100:.2f})."
                    )
                paid_paisa = grand_total_paisa
                change_due_paisa = tendered_paisa - grand_total_paisa
                credit_due_paisa = 0
                if grand_total_paisa > 0:
                    payment_records.append((clean_method, grand_total_paisa, ""))

            # 5. Enforce customer credit rules if credit_due_paisa > 0
            if credit_due_paisa > 0:
                if not customer_id:
                    raise ValueError("A registered customer must be selected for credit sales.")
                cust = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
                if not cust:
                    raise ValueError(f"Customer ID {customer_id} not found.")
                new_cust_balance = int(cust["current_balance_paisa"]) + credit_due_paisa
                credit_limit = int(cust["credit_limit_paisa"])
                if credit_limit > 0 and new_cust_balance > credit_limit:
                    raise CreditLimitExceededError(
                        f"Credit limit exceeded for '{cust['name']}': "
                        f"New balance (Rs {new_cust_balance/100:,.2f}) would exceed limit (Rs {credit_limit/100:,.2f})."
                    )
                conn.execute(
                    "UPDATE customers SET current_balance_paisa = ? WHERE id = ?",
                    (new_cust_balance, customer_id),
                )

            # 6. Insert sales header and line items
            active_shift = conn.execute(
                "SELECT id FROM cashier_shifts WHERE user_id = ? AND status = 'OPEN' ORDER BY id DESC LIMIT 1",
                (cashier_id,),
            ).fetchone()
            shift_id = int(active_shift["id"]) if active_shift else None

            cur = conn.execute(
                """
                INSERT INTO sales (
                    invoice_number, idempotency_key, invoice_date, invoice_timestamp,
                    customer_id, customer_name_walkin, subtotal_paisa, discount_paisa,
                    tax_rate_bps, tax_paisa, grand_total_paisa, total_cogs_paisa,
                    paid_paisa, change_due_paisa, credit_due_paisa, payment_method,
                    status, cashier_id, shift_id, doctor_name, prescription_ref, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?)
                """,
                (
                    invoice_number,
                    idempotency_key.strip() if idempotency_key else None,
                    inv_date,
                    now_iso,
                    customer_id,
                    customer_name_walkin.strip(),
                    subtotal_paisa,
                    inv_discount_paisa,
                    int(tax_rate_bps),
                    tax_paisa,
                    grand_total_paisa,
                    total_cogs_paisa,
                    paid_paisa,
                    change_due_paisa,
                    credit_due_paisa,
                    clean_method,
                    cashier_id,
                    shift_id,
                    doctor_name.strip(),
                    prescription_ref.strip(),
                    notes.strip(),
                ),
            )
            sale_id = int(cur.lastrowid)

            for sl in allocated_sale_lines:
                conn.execute(
                    """
                    INSERT INTO sale_lines (
                        sale_id, product_id, batch_id, batch_number, expiry_date,
                        sale_unit_type, qty_units, qty_returned, unit_price_paisa,
                        unit_cost_paisa, line_discount_paisa, line_total_paisa,
                        expired_override_by, expired_override_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        sl["product_id"],
                        sl["batch_id"],
                        sl["batch_number"],
                        sl["expiry_date"],
                        sl["sale_unit_type"],
                        sl["qty_units"],
                        sl["unit_price_paisa"],
                        sl["unit_cost_paisa"],
                        sl["line_discount_paisa"],
                        sl["line_total_paisa"],
                        sl["expired_override_by"],
                        sl["expired_override_reason"],
                    ),
                )

            for p_method, p_amt, p_ref in payment_records:
                pay_next = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM payments").fetchone()
                pay_no = f"PAY-{int(pay_next['next_id']):05d}"
                conn.execute(
                    """
                    INSERT INTO payments (
                        payment_number, payment_date, timestamp, payment_type, method,
                        amount_paisa, sale_id, customer_id, reference_no, recorded_by, notes
                    ) VALUES (?, ?, ?, 'SALE_PAYMENT', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pay_no,
                        inv_date,
                        now_iso,
                        p_method,
                        p_amt,
                        sale_id,
                        customer_id,
                        p_ref or invoice_number,
                        cashier_id,
                        f"POS Sale {invoice_number}",
                    ),
                )

            self.auth._log_in_tx(
                conn,
                user_id=cashier["id"],
                username=cashier["username"],
                action="CREATE_SALE",
                entity_type="sales",
                entity_id=str(sale_id),
                reason=f"Completed POS invoice {invoice_number}",
                details={
                    "grand_total_paisa": grand_total_paisa,
                    "cogs_paisa": total_cogs_paisa,
                    "payment_method": clean_method,
                },
            )

        return self.get_sale_invoice(sale_id)

    def void_sale_invoice(self, user_id: int, sale_id: int, reason: str) -> dict[str, Any]:
        """Void a completed sale invoice, restore exact batch stock quantities, and reverse customer credit."""
        actor = self.auth.require_permission(user_id, "VOID_INVOICE", reason=f"Void sale {sale_id}")
        if not (reason or "").strip():
            raise ValueError("A reason is required to void an invoice.")

        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise ValueError(f"Sale ID {sale_id} not found.")
            if sale["status"] == "VOIDED":
                raise ValueError(f"Invoice {sale['invoice_number']} is already voided.")
            if sale["status"] in ("RETURNED", "PARTIALLY_RETURNED"):
                raise ValueError("Cannot void an invoice that already has processed returns.")

            lines = conn.execute("SELECT * FROM sale_lines WHERE sale_id = ?", (sale_id,)).fetchall()
            for sl in lines:
                unreturned_qty = int(sl["qty_units"]) - int(sl["qty_returned"])
                if unreturned_qty > 0:
                    b_row = conn.execute("SELECT qty_remaining FROM batches WHERE id = ?", (sl["batch_id"],)).fetchone()
                    qty_before = int(b_row["qty_remaining"])
                    qty_after = qty_before + unreturned_qty
                    conn.execute(
                        "UPDATE batches SET qty_remaining = ?, updated_at = ? WHERE id = ?",
                        (qty_after, now_iso, sl["batch_id"]),
                    )
                    conn.execute(
                        """
                        INSERT INTO stock_movements (
                            timestamp, product_id, batch_id, movement_type, qty_change,
                            qty_before, qty_after, unit_cost_paisa, reference_type, reference_id,
                            user_id, notes
                        ) VALUES (?, ?, ?, 'SALE_VOID_RESTORE', ?, ?, ?, ?, 'SALE_VOID', ?, ?, ?)
                        """,
                        (
                            now_iso,
                            sl["product_id"],
                            sl["batch_id"],
                            unreturned_qty,
                            qty_before,
                            qty_after,
                            sl["unit_cost_paisa"],
                            sale["invoice_number"],
                            user_id,
                            f"Voided invoice: {reason.strip()}",
                        ),
                    )

            if int(sale["credit_due_paisa"]) > 0 and sale["customer_id"]:
                conn.execute(
                    "UPDATE customers SET current_balance_paisa = current_balance_paisa - ? WHERE id = ?",
                    (int(sale["credit_due_paisa"]), int(sale["customer_id"])),
                )

            conn.execute(
                """
                UPDATE sales SET status = 'VOIDED', void_reason = ?, voided_by = ?, voided_at = ?
                WHERE id = ?
                """,
                (reason.strip(), user_id, now_iso, sale_id),
            )

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="VOID_SALE",
                entity_type="sales",
                entity_id=str(sale_id),
                reason=reason.strip(),
                details={"invoice_number": sale["invoice_number"]},
            )

        return self.get_sale_invoice(sale_id)

    def create_sales_return(
        self,
        user_id: int,
        sale_id: int,
        return_items: list[dict[str, Any]],
        reason: str,
        refund_method: str = "CASH",
        return_date: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Process a customer sales return linked to an original invoice.

        - Prevents duplicate returns beyond the original sold quantity (`qty_units - qty_returned`).
        - Restores good items to their original batch (`restock_condition='GOOD'`) or writes off damaged returns.
        - Reverses proportional invoice discount, tax, and COGS accurately.
        """
        actor = self.auth.require_permission(user_id, "PROCESS_RETURNS")
        if not (reason or "").strip():
            raise ValueError("Return reason is required.")
        if not return_items:
            raise ValueError("At least one return item is required.")

        ret_date = return_date or date.today().isoformat()
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
            if not sale:
                raise ValueError(f"Sale ID {sale_id} not found.")
            if sale["status"] == "VOIDED":
                raise ValueError("Cannot process return on a voided invoice.")

            next_ret = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM sales_returns").fetchone()
            return_number = f"SRET-{int(next_ret['next_id']):05d}"

            cur = conn.execute(
                """
                INSERT INTO sales_returns (
                    return_number, sale_id, return_date, timestamp, customer_id,
                    subtotal_refund_paisa, tax_refund_paisa, total_refund_paisa,
                    cogs_reversed_paisa, refund_method, reason, processed_by, notes
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, ?, ?)
                """,
                (
                    return_number,
                    sale_id,
                    ret_date,
                    now_iso,
                    sale["customer_id"],
                    refund_method,
                    reason.strip(),
                    user_id,
                    notes.strip(),
                ),
            )
            sret_id = int(cur.lastrowid)

            subtotal_refund_paisa = 0
            cogs_reversed_paisa = 0

            for item in return_items:
                sale_line_id = int(item["sale_line_id"])
                qty_ret = int(item["qty_returned"])
                condition = (item.get("restock_condition") or "GOOD").upper()

                if qty_ret <= 0:
                    raise ValueError("Return quantity must be greater than zero.")

                sline = conn.execute(
                    "SELECT * FROM sale_lines WHERE id = ? AND sale_id = ?",
                    (sale_line_id, sale_id),
                ).fetchone()
                if not sline:
                    raise ValueError(f"Sale line {sale_line_id} does not belong to invoice {sale['invoice_number']}.")

                avail_qty = int(sline["qty_units"]) - int(sline["qty_returned"])
                if qty_ret > avail_qty:
                    raise ValueError(
                        f"Duplicate/excess return blocked on line {sale_line_id}: "
                        f"attempted to return {qty_ret} units, but only {avail_qty} unreturned units remain."
                    )

                # Calculate proportional net line refund (accounting for both line discount and invoice-level discount)
                line_net = int(sline["line_total_paisa"])
                if int(sale["subtotal_paisa"]) > 0 and int(sale["discount_paisa"]) > 0:
                    line_after_inv_disc = line_net - (line_net * int(sale["discount_paisa"])) // int(sale["subtotal_paisa"])
                else:
                    line_after_inv_disc = line_net

                refund_for_line = (line_after_inv_disc * qty_ret) // int(sline["qty_units"])
                line_cogs_rev = qty_ret * int(sline["unit_cost_paisa"])

                subtotal_refund_paisa += refund_for_line
                cogs_reversed_paisa += line_cogs_rev

                conn.execute(
                    "UPDATE sale_lines SET qty_returned = qty_returned + ? WHERE id = ?",
                    (qty_ret, sale_line_id),
                )

                conn.execute(
                    """
                    INSERT INTO sales_return_lines (
                        sales_return_id, sale_line_id, product_id, batch_id,
                        qty_returned, refund_paisa, cogs_reversed_paisa, restock_condition
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sret_id,
                        sale_line_id,
                        int(sline["product_id"]),
                        int(sline["batch_id"]),
                        qty_ret,
                        refund_for_line,
                        line_cogs_rev,
                        condition,
                    ),
                )

                b_row = conn.execute("SELECT qty_remaining FROM batches WHERE id = ?", (sline["batch_id"],)).fetchone()
                qty_before = int(b_row["qty_remaining"])
                if condition == "GOOD":
                    qty_after = qty_before + qty_ret
                    conn.execute(
                        "UPDATE batches SET qty_remaining = ?, updated_at = ? WHERE id = ?",
                        (qty_after, now_iso, sline["batch_id"]),
                    )
                    conn.execute(
                        """
                        INSERT INTO stock_movements (
                            timestamp, product_id, batch_id, movement_type, qty_change,
                            qty_before, qty_after, unit_cost_paisa, reference_type, reference_id,
                            user_id, notes
                        ) VALUES (?, ?, ?, 'CUSTOMER_RETURN', ?, ?, ?, ?, 'SALES_RETURN', ?, ?, ?)
                        """,
                        (
                            now_iso,
                            sline["product_id"],
                            sline["batch_id"],
                            qty_ret,
                            qty_before,
                            qty_after,
                            sline["unit_cost_paisa"],
                            return_number,
                            user_id,
                            f"Customer return ({reason.strip()})",
                        ),
                    )

            tax_rate_bps = int(sale["tax_rate_bps"])
            tax_refund_paisa = (subtotal_refund_paisa * tax_rate_bps + 5000) // 10_000
            total_refund_paisa = subtotal_refund_paisa + tax_refund_paisa

            conn.execute(
                """
                UPDATE sales_returns SET
                    subtotal_refund_paisa = ?,
                    tax_refund_paisa = ?,
                    total_refund_paisa = ?,
                    cogs_reversed_paisa = ?
                WHERE id = ?
                """,
                (subtotal_refund_paisa, tax_refund_paisa, total_refund_paisa, cogs_reversed_paisa, sret_id),
            )

            # Check if all items on invoice are now returned
            rem_check = conn.execute(
                "SELECT SUM(qty_units - qty_returned) AS rem FROM sale_lines WHERE sale_id = ?",
                (sale_id,),
            ).fetchone()
            new_sale_status = "RETURNED" if int(rem_check["rem"] or 0) == 0 else "PARTIALLY_RETURNED"
            conn.execute("UPDATE sales SET status = ? WHERE id = ?", (new_sale_status, sale_id))

            if refund_method == "CREDIT_BALANCE" and sale["customer_id"]:
                conn.execute(
                    "UPDATE customers SET current_balance_paisa = current_balance_paisa - ? WHERE id = ?",
                    (total_refund_paisa, int(sale["customer_id"])),
                )
            elif total_refund_paisa > 0:
                pay_next = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM payments").fetchone()
                pay_no = f"PAY-{int(pay_next['next_id']):05d}"
                pay_m = refund_method if refund_method != "CREDIT_BALANCE" else "CASH"
                conn.execute(
                    """
                    INSERT INTO payments (
                        payment_number, payment_date, timestamp, payment_type, method,
                        amount_paisa, sale_id, customer_id, reference_no, recorded_by, notes
                    ) VALUES (?, ?, ?, 'CUSTOMER_REFUND', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pay_no,
                        ret_date,
                        now_iso,
                        pay_m,
                        total_refund_paisa,
                        sale_id,
                        sale["customer_id"],
                        return_number,
                        user_id,
                        f"Refund for {return_number}",
                    ),
                )

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CREATE_SALES_RETURN",
                entity_type="sales_returns",
                entity_id=str(sret_id),
                reason=reason.strip(),
                details={"return_number": return_number, "total_refund_paisa": total_refund_paisa},
            )

            return {
                "id": sret_id,
                "return_number": return_number,
                "sale_id": sale_id,
                "subtotal_refund_paisa": subtotal_refund_paisa,
                "tax_refund_paisa": tax_refund_paisa,
                "total_refund_paisa": total_refund_paisa,
                "cogs_reversed_paisa": cogs_reversed_paisa,
                "new_sale_status": new_sale_status,
            }

    def record_customer_payment(
        self,
        user_id: int,
        customer_id: int,
        amount_pkr: Decimal | int | float | str,
        method: str = "CASH",
        reference_no: str = "",
        payment_date: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Receive payment from a credit customer and reduce their outstanding balance."""
        actor = self.auth.get_user(user_id)
        amount_paisa = pkr_to_paisa(amount_pkr)
        if amount_paisa <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        pay_date = payment_date or date.today().isoformat()
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            cust = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
            if not cust:
                raise ValueError(f"Customer ID {customer_id} not found.")

            next_pay = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM payments").fetchone()
            pay_no = f"RCPT-{int(next_pay['next_id']):05d}"

            cur = conn.execute(
                """
                INSERT INTO payments (
                    payment_number, payment_date, timestamp, payment_type, method,
                    amount_paisa, customer_id, reference_no, recorded_by, notes
                ) VALUES (?, ?, ?, 'CUSTOMER_RECEIPT', ?, ?, ?, ?, ?, ?)
                """,
                (pay_no, pay_date, now_iso, method, amount_paisa, customer_id, reference_no.strip(), user_id, notes.strip()),
            )
            pay_id = int(cur.lastrowid)

            conn.execute(
                "UPDATE customers SET current_balance_paisa = current_balance_paisa - ? WHERE id = ?",
                (amount_paisa, customer_id),
            )
            updated_c = conn.execute("SELECT current_balance_paisa FROM customers WHERE id = ?", (customer_id,)).fetchone()

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CUSTOMER_PAYMENT",
                entity_type="payments",
                entity_id=str(pay_id),
                reason=f"Received {pay_no} from customer {cust['name']}",
                details={"amount_paisa": amount_paisa, "new_balance_paisa": updated_c["current_balance_paisa"]},
            )

            return {
                "payment_id": pay_id,
                "payment_number": pay_no,
                "customer_id": customer_id,
                "customer_name": cust["name"],
                "amount_paisa": amount_paisa,
                "new_balance_paisa": int(updated_c["current_balance_paisa"]),
                "payment_date": pay_date,
                "method": method,
            }

    def get_sale_invoice(self, sale_id: int) -> dict[str, Any]:
        """Retrieve complete sale invoice with line items, product details, and payment breakdown."""
        with self.db.read_only() as conn:
            row = conn.execute(
                """
                SELECT s.*, u.full_name AS cashier_name, c.name AS registered_customer_name, c.phone AS customer_phone
                FROM sales s
                JOIN users u ON u.id = s.cashier_id
                LEFT JOIN customers c ON c.id = s.customer_id
                WHERE s.id = ?
                """,
                (sale_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Sale ID {sale_id} not found.")
            inv = dict(row)
            lines = conn.execute(
                """
                SELECT sl.*, p.medicine_name, p.generic_name, p.product_code, p.strength, p.dosage_form, p.pack_size
                FROM sale_lines sl
                JOIN products p ON p.id = sl.product_id
                WHERE sl.sale_id = ?
                ORDER BY sl.id ASC
                """,
                (sale_id,),
            ).fetchall()
            inv["lines"] = [dict(l) for l in lines]
            payments = conn.execute(
                "SELECT * FROM payments WHERE sale_id = ? ORDER BY id ASC",
                (sale_id,),
            ).fetchall()
            inv["payments"] = [dict(p) for p in payments]
            return inv

    def search_sales(
        self,
        invoice_number: str = "",
        start_date: str = "",
        end_date: str = "",
        product_query: str = "",
        customer_query: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Search sales by invoice number, date range, product name/code, or customer name."""
        with self.db.read_only() as conn:
            sql = """
                SELECT s.*, u.full_name AS cashier_name,
                       COALESCE(c.name, s.customer_name_walkin) AS display_customer_name
                FROM sales s
                JOIN users u ON u.id = s.cashier_id
                LEFT JOIN customers c ON c.id = s.customer_id
                WHERE 1=1
            """
            params: list[Any] = []
            if invoice_number and invoice_number.strip():
                sql += " AND s.invoice_number LIKE ?"
                params.append(f"%{invoice_number.strip()}%")
            if start_date and start_date.strip():
                sql += " AND s.invoice_date >= ?"
                params.append(start_date.strip())
            if end_date and end_date.strip():
                sql += " AND s.invoice_date <= ?"
                params.append(end_date.strip())
            if customer_query and customer_query.strip():
                cq = f"%{customer_query.strip()}%"
                sql += " AND (c.name LIKE ? OR s.customer_name_walkin LIKE ? OR c.phone LIKE ?)"
                params.extend([cq, cq, cq])
            if product_query and product_query.strip():
                pq = f"%{product_query.strip()}%"
                sql += """
                    AND EXISTS (
                        SELECT 1 FROM sale_lines sl
                        JOIN products p ON p.id = sl.product_id
                        WHERE sl.sale_id = s.id AND (p.medicine_name LIKE ? OR p.product_code LIKE ?)
                    )
                """
                params.extend([pq, pq])

            sql += " ORDER BY s.id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_customer_ledger(self, customer_id: int) -> dict[str, Any]:
        """Generate chronological customer ledger and account statement."""
        cust = self.get_customer(customer_id)
        with self.db.read_only() as conn:
            credit_sales = conn.execute(
                """
                SELECT id, invoice_number AS ref, invoice_date AS date,
                       credit_due_paisa AS debit_paisa, 0 AS credit_paisa,
                       'CREDIT_SALE' AS type, notes
                FROM sales
                WHERE customer_id = ? AND status != 'VOIDED' AND credit_due_paisa > 0
                """,
                (customer_id,),
            ).fetchall()
            credit_returns = conn.execute(
                """
                SELECT id, return_number AS ref, return_date AS date,
                       0 AS debit_paisa, total_refund_paisa AS credit_paisa,
                       'SALES_RETURN_CREDIT' AS type, reason AS notes
                FROM sales_returns
                WHERE customer_id = ? AND refund_method = 'CREDIT_BALANCE'
                """,
                (customer_id,),
            ).fetchall()
            receipts = conn.execute(
                """
                SELECT id, payment_number AS ref, payment_date AS date,
                       0 AS debit_paisa, amount_paisa AS credit_paisa,
                       'PAYMENT_RECEIVED' AS type, notes
                FROM payments
                WHERE customer_id = ? AND payment_type = 'CUSTOMER_RECEIPT'
                """,
                (customer_id,),
            ).fetchall()

        entries = [dict(r) for r in (*credit_sales, *credit_returns, *receipts)]
        entries.sort(key=lambda x: (x["date"], x["ref"]))
        running = int(cust["opening_balance_paisa"])
        for e in entries:
            running += int(e["debit_paisa"]) - int(e["credit_paisa"])
            e["running_balance_paisa"] = running

        return {
            "customer": cust,
            "opening_balance_paisa": int(cust["opening_balance_paisa"]),
            "current_balance_paisa": int(cust["current_balance_paisa"]),
            "credit_limit_paisa": int(cust["credit_limit_paisa"]),
            "entries": entries,
        }
