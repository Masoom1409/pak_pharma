"""Expenses, Cashier Shift Cash Reconciliation, Financial Analytics, and Dashboard KPI Service."""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
import os
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from app.db.database import DatabaseManager, format_pkr, paisa_to_pkr, pkr_to_paisa
from app.services.auth_service import AuthService
from app.services.inventory_service import InventoryService


class FinanceAndReportService:
    """Manages operating expenses, cashier shift cash drawer reconciliation, dashboard metrics, and financial reports."""

    def __init__(self, db: DatabaseManager, auth: AuthService, inventory: InventoryService) -> None:
        self.db = db
        self.auth = auth
        self.inventory = inventory

    def record_expense(
        self,
        user_id: int,
        category: str,
        description: str,
        amount_pkr: Decimal | int | float | str,
        payment_method: str = "CASH",
        expense_date: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Record a daily shop operating expense (e.g., electricity, rent, Ice/Cold-chain, packaging)."""
        actor = self.auth.require_permission(user_id, "RECORD_EXPENSES")
        amt_paisa = pkr_to_paisa(amount_pkr)
        if amt_paisa <= 0:
            raise ValueError("Expense amount must be greater than zero.")
        if not (category or "").strip() or not (description or "").strip():
            raise ValueError("Expense category and description are required.")

        exp_date = expense_date or date.today().isoformat()
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            next_e = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM expenses").fetchone()
            exp_no = f"EXP-{int(next_e['next_id']):05d}"
            cur = conn.execute(
                """
                INSERT INTO expenses (
                    expense_number, expense_date, category, description,
                    amount_paisa, payment_method, recorded_by, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp_no,
                    exp_date,
                    category.strip(),
                    description.strip(),
                    amt_paisa,
                    payment_method.upper(),
                    user_id,
                    notes.strip(),
                    now_iso,
                ),
            )
            exp_id = int(cur.lastrowid)
            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="RECORD_EXPENSE",
                entity_type="expenses",
                entity_id=str(exp_id),
                reason=f"Recorded expense {exp_no} ({category.strip()})",
                details={"amount_paisa": amt_paisa},
            )
            return {
                "id": exp_id,
                "expense_number": exp_no,
                "expense_date": exp_date,
                "category": category.strip(),
                "description": description.strip(),
                "amount_paisa": amt_paisa,
                "payment_method": payment_method.upper(),
            }

    def list_expenses(self, start_date: str = "", end_date: str = "", category: str = "") -> list[dict[str, Any]]:
        """Query shop expenses within a date range."""
        with self.db.read_only() as conn:
            sql = """
                SELECT e.*, u.full_name AS recorded_by_name
                FROM expenses e
                JOIN users u ON u.id = e.recorded_by
                WHERE 1=1
            """
            params: list[Any] = []
            if start_date:
                sql += " AND e.expense_date >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND e.expense_date <= ?"
                params.append(end_date)
            if category and category != "ALL":
                sql += " AND LOWER(e.category) = LOWER(?)"
                params.append(category)
            sql += " ORDER BY e.expense_date DESC, e.id DESC"
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def open_cashier_shift(
        self,
        user_id: int,
        opening_cash_pkr: Decimal | int | float | str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Open a cashier shift with a verified opening cash drawer balance."""
        actor = self.auth.get_user(user_id)
        open_paisa = pkr_to_paisa(opening_cash_pkr)
        if open_paisa < 0:
            raise ValueError("Opening cash balance cannot be negative.")
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            existing_open = conn.execute(
                "SELECT shift_number FROM cashier_shifts WHERE user_id = ? AND status = 'OPEN'",
                (user_id,),
            ).fetchone()
            if existing_open:
                raise ValueError(f"User already has an open shift ({existing_open['shift_number']}).")

            next_sh = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM cashier_shifts").fetchone()
            shift_no = f"SHF-{int(next_sh['next_id']):05d}"
            cur = conn.execute(
                """
                INSERT INTO cashier_shifts (
                    shift_number, user_id, opened_at, opening_cash_paisa, status, notes
                ) VALUES (?, ?, ?, ?, 'OPEN', ?)
                """,
                (shift_no, user_id, now_iso, open_paisa, notes.strip()),
            )
            shift_id = int(cur.lastrowid)
            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="OPEN_SHIFT",
                entity_type="cashier_shifts",
                entity_id=str(shift_id),
                reason=f"Opened shift {shift_no}",
                details={"opening_cash_paisa": open_paisa},
            )
            return {
                "id": shift_id,
                "shift_number": shift_no,
                "user_id": user_id,
                "opened_at": now_iso,
                "opening_cash_paisa": open_paisa,
                "status": "OPEN",
            }

    def close_cashier_shift(
        self,
        user_id: int,
        shift_id: int,
        actual_closing_cash_pkr: Decimal | int | float | str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Close an open cashier shift and reconcile expected vs. actual physical cash."""
        actor = self.auth.get_user(user_id)
        actual_paisa = pkr_to_paisa(actual_closing_cash_pkr)
        now_iso = datetime.now().isoformat(timespec="seconds")

        with self.db.transaction() as conn:
            sh = conn.execute("SELECT * FROM cashier_shifts WHERE id = ?", (shift_id,)).fetchone()
            if not sh:
                raise ValueError(f"Shift ID {shift_id} not found.")
            if sh["status"] != "OPEN":
                raise ValueError(f"Shift {sh['shift_number']} is already closed.")

            opened_at = sh["opened_at"]
            open_date = opened_at[:10]

            # Calculate cash inflows & outflows since shift opened
            cash_in = conn.execute(
                """
                SELECT COALESCE(SUM(amount_paisa), 0) AS total
                FROM payments
                WHERE method = 'CASH'
                  AND payment_type IN ('SALE_PAYMENT', 'CUSTOMER_RECEIPT')
                  AND timestamp >= ?
                """,
                (opened_at,),
            ).fetchone()["total"]

            cash_out_payments = conn.execute(
                """
                SELECT COALESCE(SUM(amount_paisa), 0) AS total
                FROM payments
                WHERE method = 'CASH'
                  AND payment_type IN ('CUSTOMER_REFUND', 'SUPPLIER_PAYMENT')
                  AND timestamp >= ?
                """,
                (opened_at,),
            ).fetchone()["total"]

            cash_expenses = conn.execute(
                """
                SELECT COALESCE(SUM(amount_paisa), 0) AS total
                FROM expenses
                WHERE payment_method = 'CASH'
                  AND created_at >= ?
                """,
                (opened_at,),
            ).fetchone()["total"]

            expected_paisa = int(sh["opening_cash_paisa"]) + int(cash_in) - int(cash_out_payments) - int(cash_expenses)
            variance_paisa = actual_paisa - expected_paisa

            conn.execute(
                """
                UPDATE cashier_shifts SET
                    closed_at = ?,
                    expected_closing_cash_paisa = ?,
                    actual_closing_cash_paisa = ?,
                    variance_paisa = ?,
                    status = 'CLOSED',
                    notes = ?
                WHERE id = ?
                """,
                (now_iso, expected_paisa, actual_paisa, variance_paisa, notes.strip(), shift_id),
            )

            self.auth._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CLOSE_SHIFT",
                entity_type="cashier_shifts",
                entity_id=str(shift_id),
                reason=f"Closed shift {sh['shift_number']}",
                details={
                    "expected_paisa": expected_paisa,
                    "actual_paisa": actual_paisa,
                    "variance_paisa": variance_paisa,
                },
            )

            return {
                "shift_id": shift_id,
                "shift_number": sh["shift_number"],
                "opening_cash_paisa": int(sh["opening_cash_paisa"]),
                "cash_in_paisa": int(cash_in),
                "cash_out_payments_paisa": int(cash_out_payments),
                "cash_expenses_paisa": int(cash_expenses),
                "expected_closing_cash_paisa": expected_paisa,
                "actual_closing_cash_paisa": actual_paisa,
                "variance_paisa": variance_paisa,
                "closed_at": now_iso,
            }

    def get_financial_summary(self, start_date: str, end_date: str, user_id: int | None = None) -> dict[str, Any]:
        """Compute comprehensive financial analytics for a period (`start_date` to `end_date`).

        Explicit Accounting Definitions:
        - `gross_sales_ex_tax_paisa`: Sum of `subtotal_paisa - discount_paisa` on completed/returned sales.
        - `sales_returns_ex_tax_paisa`: Sum of `subtotal_refund_paisa` on customer sales returns in the period.
        - `net_sales_ex_tax_paisa`: `gross_sales_ex_tax_paisa - sales_returns_ex_tax_paisa`.
        - `gross_cogs_paisa`: Sum of `total_cogs_paisa` on sales in the period (exact batch cost).
        - `cogs_reversed_on_returns_paisa`: Sum of `cogs_reversed_paisa` on customer returns in the period.
        - `net_cogs_paisa`: `gross_cogs_paisa - cogs_reversed_on_returns_paisa`.
        - `gross_profit_paisa`: `net_sales_ex_tax_paisa - net_cogs_paisa`.
        - `stock_write_offs_paisa`: Cost of damaged, expired, and lost stock written off in the period.
        - `operating_expenses_paisa`: Total operating expenses recorded in the period.
        - `estimated_net_profit_paisa`: `gross_profit_paisa - stock_write_offs_paisa - operating_expenses_paisa`.
        """
        if user_id is not None:
            self.auth.require_permission(user_id, "VIEW_FINANCIAL_REPORTS")

        with self.db.read_only() as conn:
            s_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS invoice_count,
                    COALESCE(SUM(subtotal_paisa), 0) AS subtotal_paisa,
                    COALESCE(SUM(discount_paisa), 0) AS inv_discount_paisa,
                    COALESCE(SUM(subtotal_paisa - discount_paisa), 0) AS gross_sales_ex_tax_paisa,
                    COALESCE(SUM(tax_paisa), 0) AS tax_collected_paisa,
                    COALESCE(SUM(grand_total_paisa), 0) AS gross_billed_inc_tax_paisa,
                    COALESCE(SUM(total_cogs_paisa), 0) AS gross_cogs_paisa
                FROM sales
                WHERE status != 'VOIDED' AND invoice_date >= ? AND invoice_date <= ?
                """,
                (start_date, end_date),
            ).fetchone()

            ret_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS return_count,
                    COALESCE(SUM(subtotal_refund_paisa), 0) AS returns_ex_tax_paisa,
                    COALESCE(SUM(tax_refund_paisa), 0) AS tax_refunded_paisa,
                    COALESCE(SUM(total_refund_paisa), 0) AS total_refund_inc_tax_paisa,
                    COALESCE(SUM(cogs_reversed_paisa), 0) AS cogs_reversed_paisa
                FROM sales_returns
                WHERE return_date >= ? AND return_date <= ?
                """,
                (start_date, end_date),
            ).fetchone()

            pur_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS purchase_count,
                    COALESCE(SUM(total_paisa), 0) AS total_purchases_paisa
                FROM purchases
                WHERE status = 'COMPLETED' AND invoice_date >= ? AND invoice_date <= ?
                """,
                (start_date, end_date),
            ).fetchone()

            wo_row = conn.execute(
                """
                SELECT COALESCE(SUM(total_cost_impact_paisa), 0) AS write_off_paisa
                FROM stock_adjustments
                WHERE adjustment_type IN ('DAMAGE_WRITE_OFF', 'EXPIRY_WRITE_OFF', 'LOST_STOCK')
                  AND adjustment_date >= ? AND adjustment_date <= ?
                """,
                (start_date, end_date),
            ).fetchone()

            exp_row = conn.execute(
                """
                SELECT COALESCE(SUM(amount_paisa), 0) AS expenses_paisa
                FROM expenses
                WHERE expense_date >= ? AND expense_date <= ?
                """,
                (start_date, end_date),
            ).fetchone()

        gross_sales_ex_tax = int(s_row["gross_sales_ex_tax_paisa"])
        returns_ex_tax = int(ret_row["returns_ex_tax_paisa"])
        net_sales_ex_tax = gross_sales_ex_tax - returns_ex_tax

        gross_cogs = int(s_row["gross_cogs_paisa"])
        cogs_reversed = int(ret_row["cogs_reversed_paisa"])
        net_cogs = gross_cogs - cogs_reversed

        gross_profit = net_sales_ex_tax - net_cogs
        write_offs = int(wo_row["write_off_paisa"])
        operating_expenses = int(exp_row["expenses_paisa"])
        estimated_net_profit = gross_profit - write_offs - operating_expenses

        return {
            "start_date": start_date,
            "end_date": end_date,
            "invoice_count": int(s_row["invoice_count"]),
            "return_count": int(ret_row["return_count"]),
            "purchase_count": int(pur_row["purchase_count"]),
            "gross_sales_ex_tax_paisa": gross_sales_ex_tax,
            "sales_returns_ex_tax_paisa": returns_ex_tax,
            "net_sales_ex_tax_paisa": net_sales_ex_tax,
            "tax_collected_net_paisa": int(s_row["tax_collected_paisa"]) - int(ret_row["tax_refunded_paisa"]),
            "gross_billed_inc_tax_paisa": int(s_row["gross_billed_inc_tax_paisa"]),
            "gross_cogs_paisa": gross_cogs,
            "cogs_reversed_on_returns_paisa": cogs_reversed,
            "net_cogs_paisa": net_cogs,
            "gross_profit_paisa": gross_profit,
            "stock_write_offs_paisa": write_offs,
            "operating_expenses_paisa": operating_expenses,
            "estimated_net_profit_paisa": estimated_net_profit,
            "total_purchases_paisa": int(pur_row["total_purchases_paisa"]),
        }

    def get_dashboard_metrics(self, reference_date: str | None = None) -> dict[str, Any]:
        """Compute real-time Dashboard KPIs directly from the SQLite database."""
        ref_date = reference_date or date.today().isoformat()
        today_fin = self.get_financial_summary(ref_date, ref_date, user_id=None)
        expiry_data = self.inventory.get_expiry_and_quarantine_report(reference_date=ref_date)
        low_stock_products = self.inventory.search_products(stock_filter="LOW_STOCK", reference_date=ref_date)

        with self.db.read_only() as conn:
            inv_totals = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM products WHERE is_active = 1) AS total_active_products,
                    COALESCE(SUM(CASE WHEN b.is_quarantined = 0 AND b.expiry_date >= ? THEN b.qty_remaining ELSE 0 END), 0) AS total_sellable_units,
                    COALESCE(SUM(CASE WHEN b.is_quarantined = 0 AND b.expiry_date >= ? THEN b.qty_remaining * b.purchase_cost_paisa ELSE 0 END), 0) AS total_inventory_cost_paisa,
                    COALESCE(SUM(CASE WHEN b.is_quarantined = 0 AND b.expiry_date >= ? THEN b.qty_remaining * b.sale_price_paisa ELSE 0 END), 0) AS total_inventory_retail_paisa
                FROM batches b
                JOIN products p ON p.id = b.product_id
                WHERE p.is_active = 1 AND b.qty_remaining > 0
                """,
                (ref_date, ref_date, ref_date),
            ).fetchone()

            cust_bal = conn.execute(
                "SELECT COALESCE(SUM(current_balance_paisa), 0) AS total FROM customers WHERE is_active = 1"
            ).fetchone()["total"]

            sup_bal = conn.execute(
                "SELECT COALESCE(SUM(current_balance_paisa), 0) AS total FROM suppliers WHERE is_active = 1"
            ).fetchone()["total"]

        near_expiry_all = (
            expiry_data["near_30_days"] + expiry_data["near_60_days"] + expiry_data["near_90_days"]
        )

        return {
            "reference_date": ref_date,
            "today_net_sales_paisa": today_fin["net_sales_ex_tax_paisa"],
            "today_gross_billed_paisa": today_fin["gross_billed_inc_tax_paisa"],
            "today_gross_profit_paisa": today_fin["gross_profit_paisa"],
            "today_estimated_net_profit_paisa": today_fin["estimated_net_profit_paisa"],
            "today_purchases_paisa": today_fin["total_purchases_paisa"],
            "today_expenses_paisa": today_fin["operating_expenses_paisa"],
            "today_invoice_count": today_fin["invoice_count"],
            "total_active_products": int(inv_totals["total_active_products"]),
            "total_sellable_units": int(inv_totals["total_sellable_units"]),
            "total_inventory_cost_paisa": int(inv_totals["total_inventory_cost_paisa"]),
            "total_inventory_retail_paisa": int(inv_totals["total_inventory_retail_paisa"]),
            "low_stock_count": len(low_stock_products),
            "low_stock_items": low_stock_products[:25],
            "near_expiry_count": len(near_expiry_all),
            "near_expiry_30_count": len(expiry_data["near_30_days"]),
            "near_expiry_items": near_expiry_all[:25],
            "expired_batch_count": len(expiry_data["expired"]),
            "expired_units_total": sum(int(x["qty_remaining"]) for x in expiry_data["expired"]),
            "expired_items": expiry_data["expired"][:25],
            "quarantined_batch_count": len(expiry_data["quarantined"]),
            "customer_receivables_paisa": int(cust_bal),
            "supplier_payables_paisa": int(sup_bal),
        }

    def get_sales_by_product_and_category(self, start_date: str, end_date: str) -> dict[str, list[dict[str, Any]]]:
        """Generate product-wise and category-wise sales and gross profit breakdown."""
        with self.db.read_only() as conn:
            by_product = conn.execute(
                """
                SELECT
                    p.id AS product_id,
                    p.product_code,
                    p.medicine_name,
                    p.category,
                    SUM(sl.qty_units - sl.qty_returned) AS net_qty_sold,
                    SUM(
                        CASE WHEN sl.qty_units > 0
                        THEN (sl.line_total_paisa * (sl.qty_units - sl.qty_returned)) / sl.qty_units
                        ELSE 0 END
                    ) AS net_revenue_paisa,
                    SUM((sl.qty_units - sl.qty_returned) * sl.unit_cost_paisa) AS net_cogs_paisa
                FROM sale_lines sl
                JOIN sales s ON s.id = sl.sale_id
                JOIN products p ON p.id = sl.product_id
                WHERE s.status != 'VOIDED' AND s.invoice_date >= ? AND s.invoice_date <= ?
                GROUP BY p.id
                HAVING net_qty_sold > 0
                ORDER BY net_revenue_paisa DESC
                """,
                (start_date, end_date),
            ).fetchall()

        prod_list: list[dict[str, Any]] = []
        cat_map: dict[str, dict[str, Any]] = {}

        for r in by_product:
            item = dict(r)
            item["gross_profit_paisa"] = int(item["net_revenue_paisa"]) - int(item["net_cogs_paisa"])
            prod_list.append(item)

            cat = item["category"]
            if cat not in cat_map:
                cat_map[cat] = {
                    "category": cat,
                    "net_qty_sold": 0,
                    "net_revenue_paisa": 0,
                    "net_cogs_paisa": 0,
                    "gross_profit_paisa": 0,
                }
            cat_map[cat]["net_qty_sold"] += int(item["net_qty_sold"])
            cat_map[cat]["net_revenue_paisa"] += int(item["net_revenue_paisa"])
            cat_map[cat]["net_cogs_paisa"] += int(item["net_cogs_paisa"])
            cat_map[cat]["gross_profit_paisa"] += int(item["gross_profit_paisa"])

        cat_list = sorted(cat_map.values(), key=lambda x: x["net_revenue_paisa"], reverse=True)
        return {"by_product": prod_list, "by_category": cat_list}

    def get_sales_by_payment_method(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Summarize payments collected by payment method for cash/payment reconciliation."""
        with self.db.read_only() as conn:
            rows = conn.execute(
                """
                SELECT
                    method,
                    SUM(CASE WHEN payment_type IN ('SALE_PAYMENT', 'CUSTOMER_RECEIPT') THEN amount_paisa ELSE 0 END) AS inflows_paisa,
                    SUM(CASE WHEN payment_type IN ('CUSTOMER_REFUND', 'SUPPLIER_PAYMENT') THEN amount_paisa ELSE 0 END) AS outflows_paisa,
                    COUNT(*) AS tx_count
                FROM payments
                WHERE payment_date >= ? AND payment_date <= ?
                GROUP BY method
                ORDER BY inflows_paisa DESC
                """,
                (start_date, end_date),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["net_paisa"] = int(d["inflows_paisa"]) - int(d["outflows_paisa"])
                result.append(d)
            return result

    def get_inventory_valuation_report(self, reference_date: str | None = None) -> dict[str, Any]:
        """Return batch-wise stock valuation report separating sellable, expired, and quarantined stock."""
        ref_date = reference_date or date.today().isoformat()
        with self.db.read_only() as conn:
            rows = conn.execute(
                """
                SELECT
                    b.id AS batch_id,
                    p.product_code,
                    p.medicine_name,
                    p.generic_name,
                    p.category,
                    b.batch_number,
                    b.expiry_date,
                    b.qty_remaining,
                    b.purchase_cost_paisa,
                    b.sale_price_paisa,
                    b.is_quarantined,
                    (b.qty_remaining * b.purchase_cost_paisa) AS batch_cost_value_paisa,
                    (b.qty_remaining * b.sale_price_paisa) AS batch_retail_value_paisa
                FROM batches b
                JOIN products p ON p.id = b.product_id
                WHERE b.qty_remaining > 0
                ORDER BY p.medicine_name ASC, b.expiry_date ASC
                """
            ).fetchall()

        batches = []
        sellable_cost = 0
        sellable_retail = 0
        expired_cost = 0
        quarantined_cost = 0

        for r in rows:
            d = dict(r)
            is_exp = d["expiry_date"] < ref_date
            d["status_label"] = (
                "QUARANTINED"
                if d["is_quarantined"]
                else ("EXPIRED" if is_exp else "SELLABLE")
            )
            if d["is_quarantined"]:
                quarantined_cost += int(d["batch_cost_value_paisa"])
            elif is_exp:
                expired_cost += int(d["batch_cost_value_paisa"])
            else:
                sellable_cost += int(d["batch_cost_value_paisa"])
                sellable_retail += int(d["batch_retail_value_paisa"])
            batches.append(d)

        return {
            "reference_date": ref_date,
            "sellable_cost_paisa": sellable_cost,
            "sellable_retail_paisa": sellable_retail,
            "expired_cost_paisa": expired_cost,
            "quarantined_cost_paisa": quarantined_cost,
            "batches": batches,
        }

    def export_report_rows_to_csv(self, rows: list[dict[str, Any]], file_path: str) -> str:
        """Export any tabular report dictionary list to CSV."""
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        if not rows:
            with open(file_path, "w", newline="", encoding="utf-8") as f:
                f.write("No records found\n")
            return os.path.abspath(file_path)

        headers = list(rows[0].keys())
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return os.path.abspath(file_path)
