"""Supplier management, Purchase Invoices, Batch Stock Receipt, Purchase Returns, and Supplier Payments."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import sqlite3
from typing import Any

from app.db.database import DatabaseManager, pkr_to_paisa
from app.services.auth_service import AuthService
from app.services.inventory_service import InsufficientStockError


class PurchaseService:
    """Manages suppliers, stock purchases, batch receiving, supplier credit notes, and supplier ledgers."""

    def __init__(self, db: DatabaseManager, auth: AuthService) -> None:
        self.db = db
        self.auth = auth

    def create_supplier(
        self,
        user_id: int,
        name: str,
        contact_person: str = "",
        phone: str = "",
        email: str = "",
        address: str = "",
        ntn_strn: str = "",
        opening_balance_pkr: Decimal | int | float | str = 0,
        notes: str = "",
    ) -> dict[str, Any]:
        """Create a new pharmaceutical distributor or supplier."""
        actor = self.auth.get_user(user_id)
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Supplier name is required.")

        open_paisa = pkr_to_paisa(opening_balance_pkr)
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            next_row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM suppliers").fetchone()
            sup_code = f"SUP-{int(next_row['next_id']):04d}"
            cur = conn.execute(
                """
                INSERT INTO suppliers (
                    supplier_code, name, contact_person, phone, email, address,
                    ntn_strn, opening_balance_paisa, current_balance_paisa, is_active, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    sup_code,
                    clean_name,
                    contact_person.strip(),
                    phone.strip(),
                    email.strip(),
                    address.strip(),
                    ntn_strn.strip(),
                    open_paisa,
                    open_paisa,
                    notes.strip(),
                    now_iso,
                ),
            )
            sup_id = int(cur.lastrowid)
            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CREATE_SUPPLIER",
                entity_type="suppliers",
                entity_id=str(sup_id),
                reason=f"Created supplier {clean_name} ({sup_code})",
            )
        return self.get_supplier(sup_id)

    def update_supplier(
        self,
        user_id: int,
        supplier_id: int,
        name: str | None = None,
        contact_person: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
        ntn_strn: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Update supplier contact details."""
        actor = self.auth.get_user(user_id)
        existing = self.get_supplier(supplier_id)
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE suppliers SET
                    name = ?, contact_person = ?, phone = ?, email = ?,
                    address = ?, ntn_strn = ?, notes = ?
                WHERE id = ?
                """,
                (
                    (name if name is not None else existing["name"]).strip(),
                    (contact_person if contact_person is not None else (existing["contact_person"] or "")).strip(),
                    (phone if phone is not None else (existing["phone"] or "")).strip(),
                    (email if email is not None else (existing["email"] or "")).strip(),
                    (address if address is not None else (existing["address"] or "")).strip(),
                    (ntn_strn if ntn_strn is not None else (existing["ntn_strn"] or "")).strip(),
                    (notes if notes is not None else (existing["notes"] or "")).strip(),
                    supplier_id,
                ),
            )
            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="UPDATE_SUPPLIER",
                entity_type="suppliers",
                entity_id=str(supplier_id),
                reason=f"Updated supplier {existing['supplier_code']}",
            )
        return self.get_supplier(supplier_id)

    def get_supplier(self, supplier_id: int) -> dict[str, Any]:
        """Get supplier record by ID."""
        with self.db.read_only() as conn:
            row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
            if not row:
                raise ValueError(f"Supplier ID {supplier_id} not found.")
            return dict(row)

    def list_suppliers(self, query: str = "") -> list[dict[str, Any]]:
        """List all suppliers optionally filtered by name or code."""
        with self.db.read_only() as conn:
            if query and query.strip():
                q = f"%{query.strip()}%"
                rows = conn.execute(
                    "SELECT * FROM suppliers WHERE name LIKE ? OR supplier_code LIKE ? OR phone LIKE ? ORDER BY name",
                    (q, q, q),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    def create_purchase_invoice(
        self,
        user_id: int,
        supplier_id: int,
        lines: list[dict[str, Any]],
        supplier_invoice_no: str = "",
        invoice_date: str | None = None,
        invoice_discount_pkr: Decimal | int | float | str = 0,
        tax_rate_bps: int = 0,
        paid_amount_pkr: Decimal | int | float | str = 0,
        payment_method: str = "CASH",
        notes: str = "",
    ) -> dict[str, Any]:
        """Record a supplier purchase invoice, create or update stock batches, and update supplier balance.

        Rule: Receiving the same (product_id, batch_number, expiry_date) updates the existing batch's
        qty_received and qty_remaining (and calculates weighted average unit cost), while different
        batch_number or expiry_date creates a separate batch row.
        """
        actor = self.auth.require_permission(user_id, "PURCHASE_STOCK")
        if not lines:
            raise ValueError("Purchase invoice must contain at least one line item.")

        inv_date = invoice_date or date.today().isoformat()
        date.fromisoformat(inv_date)
        now_iso = datetime.now().isoformat(timespec="seconds")

        inv_discount_paisa = pkr_to_paisa(invoice_discount_pkr)
        paid_paisa = pkr_to_paisa(paid_amount_pkr)
        if inv_discount_paisa < 0 or paid_paisa < 0 or tax_rate_bps < 0:
            raise ValueError("Discount, tax rate, and paid amount must be non-negative.")

        with self.db.transaction() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
            if not sup:
                raise ValueError(f"Supplier ID {supplier_id} does not exist.")

            next_p = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM purchases").fetchone()
            purchase_number = f"PUR-{int(next_p['next_id']):05d}"

            subtotal_paisa = 0
            prepared_lines: list[dict[str, Any]] = []

            for idx, item in enumerate(lines, start=1):
                product_id = int(item["product_id"])
                batch_no = (item.get("batch_number") or "").strip()
                expiry_str = (item.get("expiry_date") or "").strip()
                qty = int(item.get("qty_received", 0))
                unit_cost_paisa = pkr_to_paisa(item["unit_cost_pkr"])
                sale_price_paisa = pkr_to_paisa(item.get("sale_price_pkr", item["unit_cost_pkr"]))
                line_disc_paisa = pkr_to_paisa(item.get("line_discount_pkr", 0))

                if not batch_no:
                    raise ValueError(f"Line {idx}: Batch number is required.")
                date.fromisoformat(expiry_str)
                if qty <= 0:
                    raise ValueError(f"Line {idx}: Quantity received must be positive.")
                if unit_cost_paisa < 0 or sale_price_paisa < 0 or line_disc_paisa < 0:
                    raise ValueError(f"Line {idx}: Prices and discounts cannot be negative.")

                gross_line = qty * unit_cost_paisa
                if line_disc_paisa > gross_line:
                    raise ValueError(f"Line {idx}: Line discount cannot exceed line gross cost.")
                line_total = gross_line - line_disc_paisa
                subtotal_paisa += line_total

                prepared_lines.append(
                    {
                        "product_id": product_id,
                        "batch_number": batch_no,
                        "expiry_date": expiry_str,
                        "qty_received": qty,
                        "unit_cost_paisa": unit_cost_paisa,
                        "sale_price_paisa": sale_price_paisa,
                        "line_discount_paisa": line_disc_paisa,
                        "line_total_paisa": line_total,
                    }
                )

            if inv_discount_paisa > subtotal_paisa:
                raise ValueError("Invoice discount cannot exceed subtotal.")

            taxable_paisa = subtotal_paisa - inv_discount_paisa
            tax_paisa = (taxable_paisa * int(tax_rate_bps) + 5000) // 10_000
            total_paisa = taxable_paisa + tax_paisa
            if paid_paisa > total_paisa:
                raise ValueError("Paid amount on purchase invoice cannot exceed invoice grand total.")
            balance_due_paisa = total_paisa - paid_paisa

            cur = conn.execute(
                """
                INSERT INTO purchases (
                    purchase_number, supplier_id, supplier_invoice_no, invoice_date,
                    subtotal_paisa, discount_paisa, tax_rate_bps, tax_paisa,
                    total_paisa, paid_paisa, balance_due_paisa, status,
                    created_by, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?)
                """,
                (
                    purchase_number,
                    supplier_id,
                    supplier_invoice_no.strip(),
                    inv_date,
                    subtotal_paisa,
                    inv_discount_paisa,
                    int(tax_rate_bps),
                    tax_paisa,
                    total_paisa,
                    paid_paisa,
                    balance_due_paisa,
                    user_id,
                    notes.strip(),
                    now_iso,
                ),
            )
            purchase_id = int(cur.lastrowid)

            for pl in prepared_lines:
                # Check if exact same (product_id, batch_number, expiry_date) batch already exists
                existing_batch = conn.execute(
                    """
                    SELECT * FROM batches
                    WHERE product_id = ? AND LOWER(batch_number) = LOWER(?) AND expiry_date = ?
                    """,
                    (pl["product_id"], pl["batch_number"], pl["expiry_date"]),
                ).fetchone()

                if existing_batch:
                    batch_id = int(existing_batch["id"])
                    qty_before = int(existing_batch["qty_remaining"])
                    qty_after = qty_before + pl["qty_received"]
                    new_qty_received = int(existing_batch["qty_received"]) + pl["qty_received"]
                    # Weighted average unit cost on remaining stock
                    old_val = qty_before * int(existing_batch["purchase_cost_paisa"])
                    new_val = pl["line_total_paisa"]
                    weighted_cost = (old_val + new_val) // qty_after if qty_after > 0 else pl["unit_cost_paisa"]

                    conn.execute(
                        """
                        UPDATE batches SET
                            qty_received = ?,
                            qty_remaining = ?,
                            purchase_cost_paisa = ?,
                            sale_price_paisa = ?,
                            supplier_id = ?,
                            purchase_reference = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            new_qty_received,
                            qty_after,
                            weighted_cost,
                            pl["sale_price_paisa"],
                            supplier_id,
                            purchase_number,
                            now_iso,
                            batch_id,
                        ),
                    )
                else:
                    qty_before = 0
                    qty_after = pl["qty_received"]
                    effective_unit_cost = pl["line_total_paisa"] // pl["qty_received"]
                    b_cur = conn.execute(
                        """
                        INSERT INTO batches (
                            product_id, batch_number, expiry_date, qty_received, qty_remaining,
                            purchase_cost_paisa, sale_price_paisa, supplier_id, purchase_reference,
                            is_quarantined, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                        """,
                        (
                            pl["product_id"],
                            pl["batch_number"],
                            pl["expiry_date"],
                            pl["qty_received"],
                            pl["qty_received"],
                            effective_unit_cost,
                            pl["sale_price_paisa"],
                            supplier_id,
                            purchase_number,
                            now_iso,
                            now_iso,
                        ),
                    )
                    batch_id = int(b_cur.lastrowid)

                # Update product default purchase and sale prices
                conn.execute(
                    """
                    UPDATE products SET
                        default_purchase_price_paisa = ?,
                        default_sale_price_paisa = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (pl["unit_cost_paisa"], pl["sale_price_paisa"], now_iso, pl["product_id"]),
                )

                conn.execute(
                    """
                    INSERT INTO purchase_lines (
                        purchase_id, product_id, batch_id, batch_number, expiry_date,
                        qty_received, qty_returned, unit_cost_paisa, sale_price_paisa,
                        line_discount_paisa, line_total_paisa
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        purchase_id,
                        pl["product_id"],
                        batch_id,
                        pl["batch_number"],
                        pl["expiry_date"],
                        pl["qty_received"],
                        pl["unit_cost_paisa"],
                        pl["sale_price_paisa"],
                        pl["line_discount_paisa"],
                        pl["line_total_paisa"],
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO stock_movements (
                        timestamp, product_id, batch_id, movement_type, qty_change,
                        qty_before, qty_after, unit_cost_paisa, reference_type, reference_id,
                        user_id, notes
                    ) VALUES (?, ?, ?, 'PURCHASE_RECEIPT', ?, ?, ?, ?, 'PURCHASE', ?, ?, ?)
                    """,
                    (
                        now_iso,
                        pl["product_id"],
                        batch_id,
                        pl["qty_received"],
                        qty_before,
                        qty_after,
                        pl["unit_cost_paisa"],
                        purchase_number,
                        user_id,
                        f"Purchase from {sup['name']} ({purchase_number})",
                    ),
                )

            # Update supplier balance if balance_due_paisa > 0
            if balance_due_paisa > 0:
                conn.execute(
                    "UPDATE suppliers SET current_balance_paisa = current_balance_paisa + ? WHERE id = ?",
                    (balance_due_paisa, supplier_id),
                )

            # Record supplier payment if paid_paisa > 0
            if paid_paisa > 0:
                pay_row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM payments").fetchone()
                pay_no = f"PAY-{int(pay_row['next_id']):05d}"
                conn.execute(
                    """
                    INSERT INTO payments (
                        payment_number, payment_date, timestamp, payment_type, method,
                        amount_paisa, purchase_id, supplier_id, reference_no, recorded_by, notes
                    ) VALUES (?, ?, ?, 'SUPPLIER_PAYMENT', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pay_no,
                        inv_date,
                        now_iso,
                        payment_method,
                        paid_paisa,
                        purchase_id,
                        supplier_id,
                        purchase_number,
                        user_id,
                        f"Payment on purchase {purchase_number}",
                    ),
                )

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CREATE_PURCHASE",
                entity_type="purchases",
                entity_id=str(purchase_id),
                reason=f"Recorded purchase {purchase_number} from {sup['name']}",
                details={"total_paisa": total_paisa, "paid_paisa": paid_paisa},
            )

        return self.get_purchase_invoice(purchase_id)

    def create_purchase_return(
        self,
        user_id: int,
        supplier_id: int,
        lines: list[dict[str, Any]],
        reason: str,
        purchase_id: int | None = None,
        return_date: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Process a supplier purchase return (debit/credit note), deduct batch stock, and reduce supplier balance."""
        actor = self.auth.require_permission(user_id, "PROCESS_RETURNS")
        if not (reason or "").strip():
            raise ValueError("Return reason is required.")
        if not lines:
            raise ValueError("At least one return line is required.")

        ret_date = return_date or date.today().isoformat()
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
            if not sup:
                raise ValueError(f"Supplier ID {supplier_id} not found.")

            next_r = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM purchase_returns").fetchone()
            return_number = f"PRET-{int(next_r['next_id']):05d}"

            cur = conn.execute(
                """
                INSERT INTO purchase_returns (
                    return_number, purchase_id, supplier_id, return_date, timestamp,
                    total_credit_paisa, reason, processed_by, notes
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (return_number, purchase_id, supplier_id, ret_date, now_iso, reason.strip(), user_id, notes.strip()),
            )
            pret_id = int(cur.lastrowid)

            total_credit_paisa = 0
            for item in lines:
                batch_id = int(item["batch_id"])
                qty_ret = int(item["qty_returned"])
                purchase_line_id = item.get("purchase_line_id")

                if qty_ret <= 0:
                    raise ValueError("Return quantity must be positive.")

                batch = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
                if not batch:
                    raise ValueError(f"Batch ID {batch_id} not found.")
                if int(batch["qty_remaining"]) < qty_ret:
                    raise InsufficientStockError(
                        f"Cannot return {qty_ret} units from batch '{batch['batch_number']}': "
                        f"only {batch['qty_remaining']} units remaining in stock."
                    )

                if purchase_line_id is not None:
                    pline = conn.execute("SELECT * FROM purchase_lines WHERE id = ?", (int(purchase_line_id),)).fetchone()
                    if not pline:
                        raise ValueError(f"Purchase line {purchase_line_id} not found.")
                    avail_to_ret = int(pline["qty_received"]) - int(pline["qty_returned"])
                    if qty_ret > avail_to_ret:
                        raise ValueError(
                            f"Cannot return {qty_ret} units on purchase line {purchase_line_id}: "
                            f"only {avail_to_ret} unreturned units remaining."
                        )
                    conn.execute(
                        "UPDATE purchase_lines SET qty_returned = qty_returned + ? WHERE id = ?",
                        (qty_ret, int(purchase_line_id)),
                    )
                    unit_cost = int(pline["line_total_paisa"]) // int(pline["qty_received"])
                else:
                    unit_cost = int(batch["purchase_cost_paisa"])

                line_credit = qty_ret * unit_cost
                total_credit_paisa += line_credit

                qty_before = int(batch["qty_remaining"])
                qty_after = qty_before - qty_ret
                conn.execute(
                    "UPDATE batches SET qty_remaining = ?, updated_at = ? WHERE id = ?",
                    (qty_after, now_iso, batch_id),
                )

                conn.execute(
                    """
                    INSERT INTO purchase_return_lines (
                        purchase_return_id, purchase_line_id, product_id, batch_id,
                        qty_returned, unit_cost_paisa, line_credit_paisa
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pret_id,
                        purchase_line_id,
                        int(batch["product_id"]),
                        batch_id,
                        qty_ret,
                        unit_cost,
                        line_credit,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO stock_movements (
                        timestamp, product_id, batch_id, movement_type, qty_change,
                        qty_before, qty_after, unit_cost_paisa, reference_type, reference_id,
                        user_id, notes
                    ) VALUES (?, ?, ?, 'SUPPLIER_RETURN', ?, ?, ?, ?, 'PURCHASE_RETURN', ?, ?, ?)
                    """,
                    (
                        now_iso,
                        int(batch["product_id"]),
                        batch_id,
                        -qty_ret,
                        qty_before,
                        qty_after,
                        unit_cost,
                        return_number,
                        user_id,
                        reason.strip(),
                    ),
                )

            conn.execute(
                "UPDATE purchase_returns SET total_credit_paisa = ? WHERE id = ?",
                (total_credit_paisa, pret_id),
            )
            conn.execute(
                "UPDATE suppliers SET current_balance_paisa = current_balance_paisa - ? WHERE id = ?",
                (total_credit_paisa, supplier_id),
            )

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CREATE_PURCHASE_RETURN",
                entity_type="purchase_returns",
                entity_id=str(pret_id),
                reason=reason.strip(),
                details={"return_number": return_number, "total_credit_paisa": total_credit_paisa},
            )

            return {
                "id": pret_id,
                "return_number": return_number,
                "supplier_id": supplier_id,
                "total_credit_paisa": total_credit_paisa,
                "return_date": ret_date,
            }

    def record_supplier_payment(
        self,
        user_id: int,
        supplier_id: int,
        amount_pkr: Decimal | int | float | str,
        method: str = "CASH",
        reference_no: str = "",
        payment_date: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Record a payment to a supplier and reduce outstanding supplier payable balance."""
        actor = self.auth.get_user(user_id)
        amount_paisa = pkr_to_paisa(amount_pkr)
        if amount_paisa <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        pay_date = payment_date or date.today().isoformat()
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            sup = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
            if not sup:
                raise ValueError(f"Supplier ID {supplier_id} not found.")

            next_pay = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM payments").fetchone()
            pay_no = f"PAY-{int(next_pay['next_id']):05d}"

            cur = conn.execute(
                """
                INSERT INTO payments (
                    payment_number, payment_date, timestamp, payment_type, method,
                    amount_paisa, supplier_id, reference_no, recorded_by, notes
                ) VALUES (?, ?, ?, 'SUPPLIER_PAYMENT', ?, ?, ?, ?, ?, ?)
                """,
                (pay_no, pay_date, now_iso, method, amount_paisa, supplier_id, reference_no.strip(), user_id, notes.strip()),
            )
            pay_id = int(cur.lastrowid)

            conn.execute(
                "UPDATE suppliers SET current_balance_paisa = current_balance_paisa - ? WHERE id = ?",
                (amount_paisa, supplier_id),
            )
            updated_sup = conn.execute("SELECT current_balance_paisa FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="SUPPLIER_PAYMENT",
                entity_type="payments",
                entity_id=str(pay_id),
                reason=f"Paid {pay_no} to supplier {sup['name']}",
                details={"amount_paisa": amount_paisa, "new_balance_paisa": updated_sup["current_balance_paisa"]},
            )

            return {
                "payment_id": pay_id,
                "payment_number": pay_no,
                "supplier_id": supplier_id,
                "amount_paisa": amount_paisa,
                "new_balance_paisa": int(updated_sup["current_balance_paisa"]),
            }

    def get_purchase_invoice(self, purchase_id: int) -> dict[str, Any]:
        """Get full purchase invoice details with line items."""
        with self.db.read_only() as conn:
            row = conn.execute(
                """
                SELECT p.*, s.name AS supplier_name, s.supplier_code
                FROM purchases p
                JOIN suppliers s ON s.id = p.supplier_id
                WHERE p.id = ?
                """,
                (purchase_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Purchase ID {purchase_id} not found.")
            inv = dict(row)
            lines = conn.execute(
                """
                SELECT pl.*, pr.medicine_name, pr.product_code, pr.strength, pr.dosage_form
                FROM purchase_lines pl
                JOIN products pr ON pr.id = pl.product_id
                WHERE pl.purchase_id = ?
                ORDER BY pl.id ASC
                """,
                (purchase_id,),
            ).fetchall()
            inv["lines"] = [dict(l) for l in lines]
            return inv

    def get_supplier_ledger(self, supplier_id: int) -> dict[str, Any]:
        """Return complete chronological ledger of purchases, returns, and payments for a supplier."""
        sup = self.get_supplier(supplier_id)
        with self.db.read_only() as conn:
            purchases = conn.execute(
                "SELECT id, purchase_number AS ref, invoice_date AS date, total_paisa AS debit_paisa, 0 AS credit_paisa, 'PURCHASE' AS type, notes FROM purchases WHERE supplier_id = ? AND status = 'COMPLETED'",
                (supplier_id,),
            ).fetchall()
            returns = conn.execute(
                "SELECT id, return_number AS ref, return_date AS date, 0 AS debit_paisa, total_credit_paisa AS credit_paisa, 'PURCHASE_RETURN' AS type, reason AS notes FROM purchase_returns WHERE supplier_id = ?",
                (supplier_id,),
            ).fetchall()
            payments = conn.execute(
                "SELECT id, payment_number AS ref, payment_date AS date, 0 AS debit_paisa, amount_paisa AS credit_paisa, 'PAYMENT' AS type, notes FROM payments WHERE supplier_id = ? AND payment_type = 'SUPPLIER_PAYMENT'",
                (supplier_id,),
            ).fetchall()

        entries = [dict(r) for r in (*purchases, *returns, *payments)]
        entries.sort(key=lambda x: (x["date"], x["ref"]))
        running = int(sup["opening_balance_paisa"])
        for e in entries:
            running += int(e["debit_paisa"]) - int(e["credit_paisa"])
            e["running_balance_paisa"] = running

        return {
            "supplier": sup,
            "opening_balance_paisa": int(sup["opening_balance_paisa"]),
            "current_balance_paisa": int(sup["current_balance_paisa"]),
            "entries": entries,
        }
