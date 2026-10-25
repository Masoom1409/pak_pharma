"""Database engine, schema definition, versioned migrations, and connection manager."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import os
import secrets
import sqlite3
from typing import Any, Generator


PAISA_FACTOR = Decimal("100")


def pkr_to_paisa(amount: Decimal | int | float | str) -> int:
    """Convert a PKR amount to integer paisa using exact Decimal arithmetic (ROUND_HALF_UP)."""
    if isinstance(amount, float):
        d = Decimal(str(amount))
    elif isinstance(amount, (int, str, Decimal)):
        d = Decimal(amount)
    else:
        raise TypeError(f"Unsupported currency type: {type(amount)}")
    return int((d * PAISA_FACTOR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paisa_to_pkr(paisa: int | None) -> Decimal:
    """Convert integer paisa back to exact 2-decimal PKR Decimal."""
    if paisa is None:
        return Decimal("0.00")
    return (Decimal(int(paisa)) / PAISA_FACTOR).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_pkr(paisa: int | None, include_symbol: bool = True) -> str:
    """Format integer paisa as 'Rs 1,234.50'."""
    val = paisa_to_pkr(paisa)
    formatted = f"{val:,.2f}"
    return f"Rs {formatted}" if include_symbol else formatted


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password using PBKDF2-HMAC-SHA256 with 200,000 iterations."""
    if not password or len(password) < 4:
        raise ValueError("Password must be at least 4 characters long.")
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Constant-time verification of PBKDF2-HMAC-SHA256 password hash."""
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, password_hash)


MIGRATION_V1_SQL = """
-- Schema migrations tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

-- Application settings (key-value store)
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL
);

-- Users & Roles (ADMIN, MANAGER, CASHIER)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'MANAGER', 'CASHIER')),
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

-- Audit logs for security & sensitive actions
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id),
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    reason TEXT,
    details_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);

-- Suppliers
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    contact_person TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    ntn_strn TEXT,
    opening_balance_paisa INTEGER NOT NULL DEFAULT 0,
    current_balance_paisa INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);

-- Customers (for credit sales and patient history; optional on cash sales)
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    cnic TEXT,
    credit_limit_paisa INTEGER NOT NULL DEFAULT 0 CHECK (credit_limit_paisa >= 0),
    opening_balance_paisa INTEGER NOT NULL DEFAULT 0,
    current_balance_paisa INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

-- Medicine Master / Products
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    medicine_name TEXT NOT NULL,
    generic_name TEXT NOT NULL,
    brand_name TEXT,
    manufacturer TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'General',
    dosage_form TEXT NOT NULL DEFAULT 'Tablet',
    strength TEXT NOT NULL DEFAULT '',
    pack_size INTEGER NOT NULL DEFAULT 1 CHECK (pack_size >= 1),
    unit_of_measure TEXT NOT NULL DEFAULT 'Unit',
    pack_unit_name TEXT NOT NULL DEFAULT 'Pack',
    default_purchase_price_paisa INTEGER NOT NULL DEFAULT 0 CHECK (default_purchase_price_paisa >= 0),
    default_sale_price_paisa INTEGER NOT NULL DEFAULT 0 CHECK (default_sale_price_paisa >= 0),
    min_stock_threshold INTEGER NOT NULL DEFAULT 10 CHECK (min_stock_threshold >= 0),
    preferred_supplier_id INTEGER REFERENCES suppliers(id),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_sample_record INTEGER NOT NULL DEFAULT 0 CHECK (is_sample_record IN (0, 1)),
    verification_status TEXT NOT NULL DEFAULT 'USER_ENTERED' CHECK (verification_status IN ('VERIFIED', 'USER_ENTERED', 'SAMPLE_DEMONSTRATION', 'UNVERIFIED_IMPORT')),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(medicine_name, strength, dosage_form, manufacturer, pack_size)
);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(medicine_name);
CREATE INDEX IF NOT EXISTS idx_products_generic ON products(generic_name);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_name);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_manufacturer ON products(manufacturer);

-- Barcodes (Primary + Alternate Barcodes per product)
CREATE TABLE IF NOT EXISTS product_barcodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    barcode TEXT NOT NULL UNIQUE COLLATE NOCASE,
    barcode_type TEXT NOT NULL DEFAULT 'EAN13' CHECK (barcode_type IN ('EAN13', 'EAN8', 'UPCA', 'CODE128', 'INTERNAL')),
    is_primary INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
    pack_multiplier INTEGER NOT NULL DEFAULT 1 CHECK (pack_multiplier >= 1),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_barcodes_product ON product_barcodes(product_id);
CREATE INDEX IF NOT EXISTS idx_barcodes_code ON product_barcodes(barcode);

-- Stock Batches (Strict Batch & Expiry Separation)
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_number TEXT NOT NULL COLLATE NOCASE,
    expiry_date TEXT NOT NULL, -- ISO YYYY-MM-DD
    qty_received INTEGER NOT NULL DEFAULT 0 CHECK (qty_received >= 0),
    qty_remaining INTEGER NOT NULL DEFAULT 0 CHECK (qty_remaining >= 0),
    purchase_cost_paisa INTEGER NOT NULL DEFAULT 0 CHECK (purchase_cost_paisa >= 0),
    sale_price_paisa INTEGER NOT NULL DEFAULT 0 CHECK (sale_price_paisa >= 0),
    supplier_id INTEGER REFERENCES suppliers(id),
    purchase_reference TEXT,
    is_quarantined INTEGER NOT NULL DEFAULT 0 CHECK (is_quarantined IN (0, 1)),
    quarantine_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, batch_number, expiry_date)
);
CREATE INDEX IF NOT EXISTS idx_batches_product ON batches(product_id);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_batches_remaining ON batches(qty_remaining);

-- Stock Movement Ledger (Immutable audit trail of every stock change)
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    movement_type TEXT NOT NULL CHECK (movement_type IN (
        'INITIAL_STOCK',
        'PURCHASE_RECEIPT',
        'SALE_DEDUCTION',
        'SALE_VOID_RESTORE',
        'CUSTOMER_RETURN',
        'SUPPLIER_RETURN',
        'DAMAGE_WRITE_OFF',
        'EXPIRY_WRITE_OFF',
        'LOST_STOCK',
        'MANUAL_ADJUSTMENT_IN',
        'MANUAL_ADJUSTMENT_OUT',
        'QUARANTINE_HOLD',
        'QUARANTINE_RELEASE'
    )),
    qty_change INTEGER NOT NULL,
    qty_before INTEGER NOT NULL,
    qty_after INTEGER NOT NULL,
    unit_cost_paisa INTEGER NOT NULL DEFAULT 0,
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id),
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_batch ON stock_movements(batch_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_ts ON stock_movements(timestamp);

-- Purchase Invoices
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    supplier_invoice_no TEXT,
    invoice_date TEXT NOT NULL, -- YYYY-MM-DD
    subtotal_paisa INTEGER NOT NULL DEFAULT 0,
    discount_paisa INTEGER NOT NULL DEFAULT 0,
    tax_rate_bps INTEGER NOT NULL DEFAULT 0, -- basis points, e.g., 1800 = 18.00%
    tax_paisa INTEGER NOT NULL DEFAULT 0,
    total_paisa INTEGER NOT NULL DEFAULT 0,
    paid_paisa INTEGER NOT NULL DEFAULT 0,
    balance_due_paisa INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED', 'VOIDED')),
    created_by INTEGER REFERENCES users(id),
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(invoice_date);
CREATE INDEX IF NOT EXISTS idx_purchases_supplier ON purchases(supplier_id);

-- Purchase Invoice Line Items
CREATE TABLE IF NOT EXISTS purchase_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    batch_number TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    qty_received INTEGER NOT NULL CHECK (qty_received > 0),
    qty_returned INTEGER NOT NULL DEFAULT 0 CHECK (qty_returned >= 0 AND qty_returned <= qty_received),
    unit_cost_paisa INTEGER NOT NULL CHECK (unit_cost_paisa >= 0),
    sale_price_paisa INTEGER NOT NULL CHECK (sale_price_paisa >= 0),
    line_discount_paisa INTEGER NOT NULL DEFAULT 0 CHECK (line_discount_paisa >= 0),
    line_total_paisa INTEGER NOT NULL CHECK (line_total_paisa >= 0)
);
CREATE INDEX IF NOT EXISTS idx_purchase_lines_purchase ON purchase_lines(purchase_id);

-- Sales / POS Invoices
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    idempotency_key TEXT UNIQUE,
    invoice_date TEXT NOT NULL, -- YYYY-MM-DD
    invoice_timestamp TEXT NOT NULL, -- ISO timestamp
    customer_id INTEGER REFERENCES customers(id),
    customer_name_walkin TEXT,
    subtotal_paisa INTEGER NOT NULL DEFAULT 0,
    discount_paisa INTEGER NOT NULL DEFAULT 0,
    tax_rate_bps INTEGER NOT NULL DEFAULT 0,
    tax_paisa INTEGER NOT NULL DEFAULT 0,
    grand_total_paisa INTEGER NOT NULL DEFAULT 0,
    total_cogs_paisa INTEGER NOT NULL DEFAULT 0,
    paid_paisa INTEGER NOT NULL DEFAULT 0,
    change_due_paisa INTEGER NOT NULL DEFAULT 0,
    credit_due_paisa INTEGER NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'CASH' CHECK (payment_method IN ('CASH', 'CARD', 'EASYPAISA', 'JAZZCASH', 'BANK_TRANSFER', 'CREDIT', 'SPLIT')),
    status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED', 'VOIDED', 'RETURNED', 'PARTIALLY_RETURNED')),
    void_reason TEXT,
    voided_by INTEGER REFERENCES users(id),
    voided_at TEXT,
    cashier_id INTEGER NOT NULL REFERENCES users(id),
    shift_id INTEGER,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(invoice_date);
CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);
CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);

-- Sale Invoice Line Items (Batch-linked for exact COGS & FEFO tracking)
CREATE TABLE IF NOT EXISTS sale_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    batch_number TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    sale_unit_type TEXT NOT NULL DEFAULT 'UNIT' CHECK (sale_unit_type IN ('UNIT', 'PACK')),
    qty_units INTEGER NOT NULL CHECK (qty_units > 0),
    qty_returned INTEGER NOT NULL DEFAULT 0 CHECK (qty_returned >= 0 AND qty_returned <= qty_units),
    unit_price_paisa INTEGER NOT NULL CHECK (unit_price_paisa >= 0),
    unit_cost_paisa INTEGER NOT NULL CHECK (unit_cost_paisa >= 0),
    line_discount_paisa INTEGER NOT NULL DEFAULT 0 CHECK (line_discount_paisa >= 0),
    line_total_paisa INTEGER NOT NULL CHECK (line_total_paisa >= 0),
    expired_override_by INTEGER REFERENCES users(id),
    expired_override_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_sale_lines_sale ON sale_lines(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_lines_product ON sale_lines(product_id);
CREATE INDEX IF NOT EXISTS idx_sale_lines_batch ON sale_lines(batch_id);

-- Payments (Supports split payments on sales, customer credit payments, supplier payments)
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    payment_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payment_type TEXT NOT NULL CHECK (payment_type IN ('SALE_PAYMENT', 'CUSTOMER_RECEIPT', 'CUSTOMER_REFUND', 'SUPPLIER_PAYMENT', 'SUPPLIER_REFUND')),
    method TEXT NOT NULL CHECK (method IN ('CASH', 'CARD', 'EASYPAISA', 'JAZZCASH', 'BANK_TRANSFER')),
    amount_paisa INTEGER NOT NULL CHECK (amount_paisa >= 0),
    sale_id INTEGER REFERENCES sales(id),
    purchase_id INTEGER REFERENCES purchases(id),
    customer_id INTEGER REFERENCES customers(id),
    supplier_id INTEGER REFERENCES suppliers(id),
    reference_no TEXT,
    recorded_by INTEGER REFERENCES users(id),
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_payments_sale ON payments(sale_id);
CREATE INDEX IF NOT EXISTS idx_payments_customer ON payments(customer_id);
CREATE INDEX IF NOT EXISTS idx_payments_supplier ON payments(supplier_id);

-- Customer Sales Returns
CREATE TABLE IF NOT EXISTS sales_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    return_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    customer_id INTEGER REFERENCES customers(id),
    subtotal_refund_paisa INTEGER NOT NULL DEFAULT 0,
    tax_refund_paisa INTEGER NOT NULL DEFAULT 0,
    total_refund_paisa INTEGER NOT NULL DEFAULT 0,
    cogs_reversed_paisa INTEGER NOT NULL DEFAULT 0,
    refund_method TEXT NOT NULL DEFAULT 'CASH' CHECK (refund_method IN ('CASH', 'CREDIT_BALANCE', 'CARD', 'EASYPAISA', 'JAZZCASH', 'BANK_TRANSFER')),
    reason TEXT NOT NULL,
    processed_by INTEGER NOT NULL REFERENCES users(id),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS sales_return_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sales_return_id INTEGER NOT NULL REFERENCES sales_returns(id) ON DELETE CASCADE,
    sale_line_id INTEGER NOT NULL REFERENCES sale_lines(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    qty_returned INTEGER NOT NULL CHECK (qty_returned > 0),
    refund_paisa INTEGER NOT NULL CHECK (refund_paisa >= 0),
    cogs_reversed_paisa INTEGER NOT NULL CHECK (cogs_reversed_paisa >= 0),
    restock_condition TEXT NOT NULL DEFAULT 'GOOD' CHECK (restock_condition IN ('GOOD', 'DAMAGED'))
);

-- Supplier Purchase Returns (Credit Notes)
CREATE TABLE IF NOT EXISTS purchase_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    purchase_id INTEGER REFERENCES purchases(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    return_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    total_credit_paisa INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    processed_by INTEGER NOT NULL REFERENCES users(id),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS purchase_return_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_return_id INTEGER NOT NULL REFERENCES purchase_returns(id) ON DELETE CASCADE,
    purchase_line_id INTEGER REFERENCES purchase_lines(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    qty_returned INTEGER NOT NULL CHECK (qty_returned > 0),
    unit_cost_paisa INTEGER NOT NULL CHECK (unit_cost_paisa >= 0),
    line_credit_paisa INTEGER NOT NULL CHECK (line_credit_paisa >= 0)
);

-- Stock Adjustments & Write-Offs (Damaged, Expired, Lost, Manual)
CREATE TABLE IF NOT EXISTS stock_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adjustment_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    adjustment_date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    adjustment_type TEXT NOT NULL CHECK (adjustment_type IN (
        'DAMAGE_WRITE_OFF',
        'EXPIRY_WRITE_OFF',
        'LOST_STOCK',
        'MANUAL_ADJUSTMENT_IN',
        'MANUAL_ADJUSTMENT_OUT',
        'QUARANTINE_HOLD',
        'QUARANTINE_RELEASE'
    )),
    qty_delta INTEGER NOT NULL,
    unit_cost_paisa INTEGER NOT NULL DEFAULT 0,
    total_cost_impact_paisa INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    authorized_by INTEGER NOT NULL REFERENCES users(id),
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_stock_adjustments_date ON stock_adjustments(adjustment_date);

-- Operating Expenses
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    expense_date TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_paisa INTEGER NOT NULL CHECK (amount_paisa > 0),
    payment_method TEXT NOT NULL DEFAULT 'CASH' CHECK (payment_method IN ('CASH', 'BANK_TRANSFER', 'EASYPAISA', 'JAZZCASH', 'CARD')),
    recorded_by INTEGER NOT NULL REFERENCES users(id),
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);

-- Cashier Shifts & Cash Drawer Reconciliation
CREATE TABLE IF NOT EXISTS cashier_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_number TEXT NOT NULL UNIQUE COLLATE NOCASE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    opening_cash_paisa INTEGER NOT NULL DEFAULT 0 CHECK (opening_cash_paisa >= 0),
    expected_closing_cash_paisa INTEGER,
    actual_closing_cash_paisa INTEGER,
    variance_paisa INTEGER,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    notes TEXT
);

-- Backup History Log
CREATE TABLE IF NOT EXISTS backup_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256_checksum TEXT NOT NULL,
    backup_type TEXT NOT NULL CHECK (backup_type IN ('MANUAL', 'SCHEDULED', 'PRE_RESTORE')),
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    triggered_by INTEGER REFERENCES users(id),
    notes TEXT
);
"""

MIGRATION_V2_SQL = """
-- Migration V2: Add prescription reference and doctor name on sales for narcotics/antibiotic tracking if needed
ALTER TABLE sales ADD COLUMN doctor_name TEXT DEFAULT '';
ALTER TABLE sales ADD COLUMN prescription_ref TEXT DEFAULT '';
"""

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial_pharmacy_schema", MIGRATION_V1_SQL),
    (2, "add_prescription_fields_to_sales", MIGRATION_V2_SQL),
]

DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "shop_name": ("Al-Shifa Pharmacy & Medical Store", "Retail pharmacy name printed on invoices and receipts"),
    "shop_name_urdu": ("الشفا فارمیسی اینڈ میڈیکل سٹور", "Pharmacy name in Urdu"),
    "shop_address": ("Shop #14, Block 7, Gulshan-e-Iqbal, Karachi, Pakistan", "Pharmacy physical address"),
    "shop_phone": ("+92-21-34981234 / 0300-1234567", "Pharmacy contact numbers"),
    "shop_license_no": ("DRAP/KHI/RET-2026-0891", "Pharmacy drug sale license number"),
    "currency_code": ("PKR", "Primary currency code"),
    "currency_symbol": ("Rs", "Currency display prefix"),
    "default_tax_rate_bps": ("0", "Default sales tax rate in basis points (0 = 0.00%, 1800 = 18.00%)"),
    "expiry_alert_days_1": ("30", "Critical near-expiry alert threshold in days"),
    "expiry_alert_days_2": ("60", "Warning near-expiry alert threshold in days"),
    "expiry_alert_days_3": ("90", "Planning near-expiry alert threshold in days"),
    "allow_negative_stock": ("0", "Allow selling beyond available batch stock (0=No, 1=Yes)"),
    "block_expired_sales": ("1", "Block selling expired batches by default (1=Block, 0=Allow)"),
    "allow_admin_expired_override": ("1", "Allow Admin/Manager to override expired block with recorded reason"),
    "cashier_max_discount_bps": ("500", "Maximum discount a Cashier can apply in basis points (500 = 5.00%)"),
    "manager_max_discount_bps": ("2000", "Maximum discount a Manager can apply in basis points (2000 = 20.00%)"),
    "receipt_paper_width_mm": ("80", "Thermal receipt width in mm (58 or 80)"),
    "receipt_footer_message": ("Thank you for visiting! Keep medicines out of reach of children. No return on cut strips or fridge items without receipt.", "Footer message on receipts"),
    "backup_retention_count": ("14", "Number of automatic backups to retain before pruning oldest"),
    "auto_backup_enabled": ("1", "Enable automatic background backup on launch/close"),
    "ui_language": ("en", "Default interface language (en or ur)"),
}


class DatabaseManager:
    """Thread-safe, transactional SQLite database manager with automatic migrations."""

    def __init__(self, db_path: str) -> None:
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.initialize_and_migrate()

    def get_connection(self) -> sqlite3.Connection:
        """Create a configured SQLite connection with WAL mode and foreign keys enforced."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
        except sqlite3.OperationalError:
            conn.execute("PRAGMA journal_mode = MEMORY;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Execute a block inside an immediate ACID transaction (rolls back on any error)."""
        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK;")
            raise
        finally:
            conn.close()

    @contextmanager
    def read_only(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a connection for read queries."""
        conn = self.get_connection()
        try:
            yield conn
        finally:
            conn.close()

    def initialize_and_migrate(self) -> list[int]:
        """Run all pending schema migrations and seed default settings and users."""
        applied_versions: list[int] = []
        with self.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                );
                """
            )
            existing = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            now_iso = datetime.now().isoformat(timespec="seconds")
            for version, name, sql in MIGRATIONS:
                if version not in existing:
                    for statement in self._split_sql_statements(sql):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                        (version, name, now_iso),
                    )
                    applied_versions.append(version)

            # Seed default settings without overwriting existing values
            for key, (val, desc) in DEFAULT_SETTINGS.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO app_settings (key, value, description, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (key, val, desc, now_iso),
                )

            # Seed default users if users table is empty
            user_count = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()["cnt"]
            if user_count == 0:
                default_users = [
                    ("admin", "Chief Pharmacist (Admin)", "ADMIN", "Admin@123"),
                    ("manager", "Store Manager", "MANAGER", "Manager@123"),
                    ("cashier", "Counter Cashier", "CASHIER", "Cashier@123"),
                ]
                for uname, fname, role, pwd in default_users:
                    phash, psalt = hash_password(pwd)
                    conn.execute(
                        """
                        INSERT INTO users (username, full_name, role, password_hash, password_salt, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (uname, fname, role, phash, psalt, now_iso),
                    )
        return applied_versions

    @staticmethod
    def _split_sql_statements(sql_script: str) -> list[str]:
        """Split a multi-statement SQL script safely."""
        statements: list[str] = []
        current: list[str] = []
        for line in sql_script.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            current.append(line)
            if stripped.endswith(";"):
                stmt = "\n".join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
        if current:
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
        return statements

    def get_setting(self, key: str, default: str = "") -> str:
        """Fetch an application setting value."""
        with self.read_only() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str, user_id: int | None = None) -> None:
        """Update an application setting value and record in audit log."""
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (key, value, description, updated_at)
                VALUES (?, ?, '', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, str(value), now_iso),
            )
            if user_id is not None:
                u_row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
                uname = u_row["username"] if u_row else "system"
                conn.execute(
                    """
                    INSERT INTO audit_logs (timestamp, user_id, username, action, entity_type, entity_id, reason, details_json)
                    VALUES (?, ?, ?, 'UPDATE_SETTING', 'app_settings', ?, 'Configuration change', ?)
                    """,
                    (now_iso, user_id, uname, key, f'{{"value": "{value}"}}'),
                )

    def get_all_settings(self) -> dict[str, str]:
        """Return all settings as a dictionary."""
        with self.read_only() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}
