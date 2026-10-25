"""PySide6 Windows Desktop User Interface for PakPharma POS & Medical Store Management System."""

from __future__ import annotations

from datetime import date
import os
import sys
from typing import Any
import uuid

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QSplitter,
        QStackedWidget,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False
    QDialog = object  # type: ignore
    QMainWindow = object  # type: ignore
    QWidget = object  # type: ignore

from app.db.database import DatabaseManager, format_pkr, paisa_to_pkr
from app.i18n.translations import tr
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
)
from app.services.purchase_service import PurchaseService
from app.services.sales_service import CreditLimitExceededError, DuplicateInvoiceError, SalesService


APP_STYLESHEET = """
QMainWindow { background-color: #F1F5F9; }
QFrame#Sidebar { background-color: #0F172A; min-width: 225px; max-width: 245px; }
QPushButton.NavBtn {
    background-color: transparent;
    color: #E2E8F0;
    text-align: left;
    padding: 11px 16px;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton.NavBtn:hover { background-color: #1E293B; color: #FFFFFF; }
QPushButton.NavBtn:checked { background-color: #0284C7; color: #FFFFFF; }
QFrame.KpiCard {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 12px;
}
QLabel.KpiTitle { color: #475569; font-size: 12px; font-weight: 600; }
QLabel.KpiValue { color: #0F172A; font-size: 20px; font-weight: 800; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #94A3B8;
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 13px;
}
QLineEdit#BarcodeScanField {
    border: 2px solid #0284C7;
    background-color: #F0F9FF;
    font-size: 15px;
    font-weight: bold;
    padding: 8px 12px;
}
QPushButton.PrimaryBtn {
    background-color: #0284C7;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton.PrimaryBtn:hover { background-color: #0369A1; }
QPushButton.SuccessBtn {
    background-color: #16A34A;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 10px 18px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton.DangerBtn {
    background-color: #DC2626;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: bold;
}
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    gridline-color: #E2E8F0;
    font-size: 12.5px;
}
QHeaderView::section {
    background-color: #1E293B;
    color: #FFFFFF;
    padding: 7px;
    font-weight: bold;
    border: none;
}
"""


class LoginDialog(QDialog):
    """Modal login screen authenticating against PBKDF2 local user accounts."""

    def __init__(self, auth_service: AuthService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.auth_service = auth_service
        self.authenticated_user: dict[str, Any] | None = None
        self.setWindowTitle("PakPharma POS - Staff Login")
        self.setMinimumWidth(380)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("PakPharma POS & Inventory")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0F172A;")
        sub = QLabel("Offline Retail Medical Store System (Pakistan)")
        sub.setStyleSheet("font-size: 12px; color: #475569; margin-bottom: 10px;")
        layout.addWidget(title)
        layout.addWidget(sub)

        form = QFormLayout()
        self.user_edit = QLineEdit("admin")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Enter password (default: Admin@123)")
        form.addRow("Username:", self.user_edit)
        form.addRow("Password:", self.pass_edit)
        layout.addLayout(form)

        btn_login = QPushButton("Sign In to Pharmacy Counter")
        btn_login.setProperty("class", "PrimaryBtn")
        btn_login.clicked.connect(self._attempt_login)
        layout.addWidget(btn_login)

    def _attempt_login(self) -> None:
        try:
            self.authenticated_user = self.auth_service.authenticate(
                self.user_edit.text(),
                self.pass_edit.text(),
            )
            self.accept()
        except AuthenticationError as e:
            QMessageBox.warning(self, "Login Failed", str(e))


class NewMedicineDialog(QDialog):
    """Fast New Medicine & Initial Batch dialog (auto-opened when an unknown barcode is scanned)."""

    def __init__(
        self,
        inventory_service: InventoryService,
        user_id: int,
        prefill_barcode: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.inventory_service = inventory_service
        self.user_id = user_id
        self.prefill_barcode = prefill_barcode
        self.created_product: dict[str, Any] | None = None
        self.setWindowTitle("Add New Medicine & Opening Batch")
        self.setMinimumWidth(480)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        if self.prefill_barcode:
            banner = QLabel(
                f"Unknown Barcode Scanned: <b>{self.prefill_barcode}</b><br/>"
                "Please enter the medicine details below to register this barcode."
            )
            banner.setStyleSheet("background-color: #FEF3C7; color: #92400E; padding: 8px; border-radius: 5px;")
            layout.addWidget(banner)

        form = QFormLayout()
        self.barcode_edit = QLineEdit(self.prefill_barcode)
        self.name_edit = QLineEdit()
        self.generic_edit = QLineEdit()
        self.mfg_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems(["Analgesic", "Antibiotic", "Antacid / GI", "Antidiabetic", "Cardiovascular", "Syrup / Pediatric", "Surgical / Disposables", "General"])
        self.dosage_combo = QComboBox()
        self.dosage_combo.addItems(["Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Cream / Ointment", "Drops", "Sachet", "Inhaler"])
        self.strength_edit = QLineEdit()
        self.strength_edit.setPlaceholderText("e.g., 500 mg or 250 mg/5 ml")
        self.pack_spin = QSpinBox()
        self.pack_spin.setRange(1, 1000)
        self.pack_spin.setValue(10)
        self.p_price_spin = QDoubleSpinBox()
        self.p_price_spin.setRange(0.0, 500000.0)
        self.p_price_spin.setDecimals(2)
        self.s_price_spin = QDoubleSpinBox()
        self.s_price_spin.setRange(0.0, 500000.0)
        self.s_price_spin.setDecimals(2)
        self.min_stock_spin = QSpinBox()
        self.min_stock_spin.setRange(0, 10000)
        self.min_stock_spin.setValue(20)
        self.batch_edit = QLineEdit("BATCH-01")
        self.expiry_edit = QLineEdit("2028-12-31")
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(0, 100000)
        self.qty_spin.setValue(50)

        form.addRow("Barcode (EAN/UPC/Code128):", self.barcode_edit)
        form.addRow("Medicine / Brand Name *:", self.name_edit)
        form.addRow("Generic / Salt Name *:", self.generic_edit)
        form.addRow("Manufacturer / Company *:", self.mfg_edit)
        form.addRow("Category:", self.category_combo)
        form.addRow("Dosage Form:", self.dosage_combo)
        form.addRow("Strength:", self.strength_edit)
        form.addRow("Units per Pack:", self.pack_spin)
        form.addRow("Unit Purchase Price (Rs) *:", self.p_price_spin)
        form.addRow("Unit Retail Sale Price (Rs) *:", self.s_price_spin)
        form.addRow("Low-Stock Alert Threshold:", self.min_stock_spin)
        form.addRow("Opening Batch Number *:", self.batch_edit)
        form.addRow("Expiry Date (YYYY-MM-DD) *:", self.expiry_edit)
        form.addRow("Initial Quantity (Units) *:", self.qty_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save_medicine)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_medicine(self) -> None:
        try:
            self.created_product = self.inventory_service.create_product(
                user_id=self.user_id,
                medicine_name=self.name_edit.text(),
                generic_name=self.generic_edit.text(),
                manufacturer=self.mfg_edit.text(),
                purchase_price_pkr=str(self.p_price_spin.value()),
                sale_price_pkr=str(self.s_price_spin.value()),
                category=self.category_combo.currentText(),
                dosage_form=self.dosage_combo.currentText(),
                strength=self.strength_edit.text(),
                pack_size=self.pack_spin.value(),
                barcode=self.barcode_edit.text() if self.barcode_edit.text().strip() else None,
                min_stock_threshold=self.min_stock_spin.value(),
                initial_batch_number=self.batch_edit.text(),
                initial_expiry_date=self.expiry_edit.text(),
                initial_qty=self.qty_spin.value(),
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Validation Error", str(e))


class PakPharmaMainWindow(QMainWindow):
    """Main Desktop Window for PakPharma POS & Medical Store Management System."""

    def __init__(
        self,
        db: DatabaseManager,
        auth: AuthService,
        inventory: InventoryService,
        purchases: PurchaseService,
        sales: SalesService,
        finance: FinanceAndReportService,
        backup: BackupService,
        printing: PrintingService,
        current_user: dict[str, Any],
    ) -> None:
        super().__init__()
        self.db = db
        self.auth = auth
        self.inventory = inventory
        self.purchases = purchases
        self.sales = sales
        self.finance = finance
        self.backup = backup
        self.printing = printing
        self.current_user = current_user
        self.current_lang = self.db.get_setting("ui_language", "en")
        self.pos_cart: list[dict[str, Any]] = []

        self.setWindowTitle(tr("app_title", self.current_lang))
        self.resize(1366, 820)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_main_layout()
        self._register_shortcuts()
        self.refresh_all_views()

    def _build_main_layout(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Left navigation sidebar
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 16, 12, 16)
        sb_layout.setSpacing(6)

        brand_lbl = QLabel("PAKPHARMA POS")
        brand_lbl.setStyleSheet("color: #38BDF8; font-size: 17px; font-weight: 900; padding: 6px;")
        user_lbl = QLabel(f"{self.current_user['full_name']}\nRole: {self.current_user['role']}")
        user_lbl.setStyleSheet("color: #94A3B8; font-size: 11.5px; padding: 4px 6px 12px 6px;")
        sb_layout.addWidget(brand_lbl)
        sb_layout.addWidget(user_lbl)

        self.stack = QStackedWidget()
        self.nav_buttons: list[QPushButton] = []

        nav_items = [
            ("nav_dashboard", self._create_dashboard_page()),
            ("nav_pos", self._create_pos_page()),
            ("nav_medicines", self._create_medicines_page()),
            ("nav_purchases", self._create_purchases_page()),
            ("nav_inventory", self._create_expiry_page()),
            ("nav_returns", self._create_returns_page()),
            ("nav_parties", self._create_parties_page()),
            ("nav_reports", self._create_reports_page()),
            ("nav_users", self._create_users_page()),
            ("nav_backup", self._create_backup_page()),
        ]

        for idx, (nav_key, page_widget) in enumerate(nav_items):
            btn = QPushButton(tr(nav_key, self.current_lang))
            btn.setProperty("class", "NavBtn")
            btn.setCheckable(True)
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, i=idx: self.switch_page(i))
            sb_layout.addWidget(btn)
            self.nav_buttons.append(btn)
            self.stack.addWidget(page_widget)

        sb_layout.addStretch()
        lang_btn = QPushButton(tr("lang_toggle", self.current_lang))
        lang_btn.setProperty("class", "PrimaryBtn")
        lang_btn.clicked.connect(self.toggle_language)
        sb_layout.addWidget(lang_btn)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready | Offline SQLite WAL Mode Active | USB Barcode Wedge Ready")

    def _register_shortcuts(self) -> None:
        QShortcut(QKeySequence("F2"), self, activated=lambda: self.switch_page(1))
        QShortcut(QKeySequence("F3"), self, activated=self.open_add_medicine_dialog)
        QShortcut(QKeySequence("F4"), self, activated=lambda: self.switch_page(3))
        QShortcut(QKeySequence("F12"), self, activated=self.complete_pos_sale)

    def switch_page(self, index: int) -> None:
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == index)
        self.stack.setCurrentIndex(index)
        if index == 1 and hasattr(self, "pos_barcode_input"):
            self.pos_barcode_input.setFocus()

    def toggle_language(self) -> None:
        self.current_lang = "ur" if self.current_lang == "en" else "en"
        self.db.set_setting("ui_language", self.current_lang, self.current_user["id"])
        self.setWindowTitle(tr("app_title", self.current_lang))
        if self.current_lang == "ur":
            self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        else:
            self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.refresh_all_views()

    # ------------------------------------------------------------------
    # Page 1: Dashboard
    # ------------------------------------------------------------------
    def _create_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        top_bar = QHBoxLayout()
        header = QLabel(self.db.get_setting("shop_name", "Al-Shifa Pharmacy & Medical Store"))
        header.setStyleSheet("font-size: 22px; font-weight: 800; color: #0F172A;")
        top_bar.addWidget(header)
        top_bar.addStretch()

        for label_txt, callback in [
            ("New Sale (F2)", lambda: self.switch_page(1)),
            ("Add Medicine (F3)", self.open_add_medicine_dialog),
            ("Purchase Stock (F4)", lambda: self.switch_page(3)),
            ("Inventory & FEFO", lambda: self.switch_page(4)),
            ("Financial Reports", lambda: self.switch_page(7)),
        ]:
            b = QPushButton(label_txt)
            b.setProperty("class", "PrimaryBtn")
            b.clicked.connect(callback)
            top_bar.addWidget(b)
        layout.addLayout(top_bar)

        # KPI Grid (10 cards)
        kpi_grid = QGridLayout()
        self.kpi_labels: dict[str, QLabel] = {}
        kpi_defs = [
            ("today_sales", "Today's Net Sales (Ex-Tax)"),
            ("gross_profit", "Today's Gross Profit (Sales - COGS)"),
            ("net_profit", "Today's Est. Net Profit"),
            ("today_purchases", "Today's Purchases"),
            ("total_stock", "Active Products / Total Units"),
            ("low_stock", "Low-Stock Medicines"),
            ("near_expiry", "Near-Expiry Batches (<=90d)"),
            ("expired_stock", "Expired Stock (Blocked)"),
            ("receivables", "Customer Receivables"),
            ("payables", "Supplier Payables"),
        ]
        for idx, (k, title) in enumerate(kpi_defs):
            card = QFrame()
            card.setProperty("class", "KpiCard")
            cl = QVBoxLayout(card)
            t_lbl = QLabel(title)
            t_lbl.setProperty("class", "KpiTitle")
            v_lbl = QLabel("Rs 0.00")
            v_lbl.setProperty("class", "KpiValue")
            cl.addWidget(t_lbl)
            cl.addWidget(v_lbl)
            self.kpi_labels[k] = v_lbl
            kpi_grid.addWidget(card, idx // 5, idx % 5)
        layout.addLayout(kpi_grid)

        # Split tables: Low stock & Near/Expired batches
        tables_row = QHBoxLayout()
        low_box = QGroupBox("Low-Stock Medicines Requiring Reorder")
        low_l = QVBoxLayout(low_box)
        self.dash_low_table = QTableWidget(0, 4)
        self.dash_low_table.setHorizontalHeaderLabels(["Code", "Medicine", "Sellable Units", "Min Threshold"])
        self.dash_low_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        low_l.addWidget(self.dash_low_table)

        exp_box = QGroupBox("Expired & Near-Expiry Batches Requiring Attention")
        exp_l = QVBoxLayout(exp_box)
        self.dash_exp_table = QTableWidget(0, 5)
        self.dash_exp_table.setHorizontalHeaderLabels(["Medicine", "Batch #", "Expiry Date", "Days Left", "Qty"])
        self.dash_exp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        exp_l.addWidget(self.dash_exp_table)

        tables_row.addWidget(low_box)
        tables_row.addWidget(exp_box)
        layout.addLayout(tables_row, stretch=1)
        return page

    # ------------------------------------------------------------------
    # Page 2: Point of Sale (POS) & Barcode Billing
    # ------------------------------------------------------------------
    def _create_pos_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)

        scan_bar = QHBoxLayout()
        self.pos_barcode_input = QLineEdit()
        self.pos_barcode_input.setObjectName("BarcodeScanField")
        self.pos_barcode_input.setPlaceholderText(tr("scan_barcode_placeholder", self.current_lang))
        self.pos_barcode_input.returnPressed.connect(self.handle_pos_barcode_scan)
        scan_bar.addWidget(QLabel("<b>USB Barcode Scanner:</b>"))
        scan_bar.addWidget(self.pos_barcode_input, stretch=2)

        self.pos_search_combo = QComboBox()
        self.pos_search_combo.setEditable(True)
        self.pos_search_combo.setMinimumWidth(280)
        add_btn = QPushButton("Add Selected Item")
        add_btn.setProperty("class", "PrimaryBtn")
        add_btn.clicked.connect(self.add_selected_combo_to_cart)
        scan_bar.addWidget(QLabel("Manual Search:"))
        scan_bar.addWidget(self.pos_search_combo, stretch=2)
        scan_bar.addWidget(add_btn)
        layout.addLayout(scan_bar)

        self.pos_table = QTableWidget(0, 8)
        self.pos_table.setHorizontalHeaderLabels([
            "Product Code", "Medicine Name", "FEFO Batch", "Expiry", "Unit/Pack", "Qty", "Unit Rate (Rs)", "Line Total (Rs)"
        ])
        self.pos_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.pos_table, stretch=1)

        footer = QHBoxLayout()
        self.pos_discount_spin = QDoubleSpinBox()
        self.pos_discount_spin.setRange(0.0, 100000.0)
        self.pos_discount_spin.valueChanged.connect(self.update_pos_totals)
        self.pos_method_combo = QComboBox()
        self.pos_method_combo.addItems(["CASH", "CARD", "EASYPAISA", "JAZZCASH", "BANK_TRANSFER", "CREDIT"])
        self.pos_tendered_spin = QDoubleSpinBox()
        self.pos_tendered_spin.setRange(0.0, 1000000.0)
        self.pos_total_lbl = QLabel("Grand Total: Rs 0.00")
        self.pos_total_lbl.setStyleSheet("font-size: 22px; font-weight: 900; color: #16A34A;")

        clear_btn = QPushButton("Clear Cart")
        clear_btn.setProperty("class", "DangerBtn")
        clear_btn.clicked.connect(self.clear_pos_cart)

        checkout_btn = QPushButton("Complete Sale & Print Receipt (F12)")
        checkout_btn.setProperty("class", "SuccessBtn")
        checkout_btn.clicked.connect(self.complete_pos_sale)

        footer.addWidget(QLabel("Discount (Rs):"))
        footer.addWidget(self.pos_discount_spin)
        footer.addWidget(QLabel("Payment Method:"))
        footer.addWidget(self.pos_method_combo)
        footer.addWidget(QLabel("Cash Tendered (Rs):"))
        footer.addWidget(self.pos_tendered_spin)
        footer.addStretch()
        footer.addWidget(self.pos_total_lbl)
        footer.addWidget(clear_btn)
        footer.addWidget(checkout_btn)
        layout.addLayout(footer)
        return page

    # ------------------------------------------------------------------
    # Page 3: Medicine Master & Barcode Label Printing
    # ------------------------------------------------------------------
    def _create_medicines_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)

        bar = QHBoxLayout()
        self.med_search_edit = QLineEdit()
        self.med_search_edit.setPlaceholderText("Search by Medicine Name, Generic Salt, Brand, Barcode, or Code...")
        self.med_search_edit.textChanged.connect(self.refresh_medicines_table)
        bar.addWidget(self.med_search_edit, stretch=1)

        btn_add = QPushButton("Add New Medicine (F3)")
        btn_add.setProperty("class", "PrimaryBtn")
        btn_add.clicked.connect(self.open_add_medicine_dialog)
        bar.addWidget(btn_add)
        layout.addLayout(bar)

        self.med_table = QTableWidget(0, 9)
        self.med_table.setHorizontalHeaderLabels([
            "Code", "Medicine Name", "Generic / Salt", "Manufacturer", "Strength",
            "Barcode", "Purchase (Rs)", "Sale Price (Rs)", "Sellable Stock"
        ])
        self.med_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.med_table, stretch=1)
        return page

    def _create_purchases_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>Supplier Purchase Invoices & Batch Stock Receiving</h3>"))
        self.pur_table = QTableWidget(0, 6)
        self.pur_table.setHorizontalHeaderLabels(["Purchase #", "Date", "Supplier", "Total (Rs)", "Paid (Rs)", "Balance Due (Rs)"])
        self.pur_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.pur_table, stretch=1)
        return page

    def _create_expiry_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>FEFO Batch Inventory, Expiry Alerts (30/60/90 Days) & Quarantine</h3>"))
        self.batch_table = QTableWidget(0, 8)
        self.batch_table.setHorizontalHeaderLabels([
            "Code", "Medicine", "Batch #", "Expiry Date", "Qty Remaining", "Unit Cost", "Sale Price", "Status"
        ])
        self.batch_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.batch_table, stretch=1)
        return page

    def _create_returns_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>Customer Sales Returns, Supplier Credit Notes & Stock Write-Offs</h3>"))
        self.adj_table = QTableWidget(0, 6)
        self.adj_table.setHorizontalHeaderLabels(["Adjustment #", "Date", "Type", "Batch ID", "Qty Delta", "Reason"])
        self.adj_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.adj_table, stretch=1)
        return page

    def _create_parties_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>Suppliers & Credit Customers Ledger</h3>"))
        self.sup_table = QTableWidget(0, 5)
        self.sup_table.setHorizontalHeaderLabels(["Code", "Supplier Name", "Contact", "Phone", "Payable Balance (Rs)"])
        self.sup_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.sup_table, stretch=1)
        return page

    def _create_reports_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>Financial Analytics: Net Sales, Exact Batch COGS, Gross Profit & Expenses</h3>"))
        self.rep_summary_lbl = QLabel()
        self.rep_summary_lbl.setStyleSheet("background: #FFFFFF; padding: 14px; border: 1px solid #CBD5E1; border-radius: 6px; font-size: 13.5px;")
        layout.addWidget(self.rep_summary_lbl)
        self.rep_table = QTableWidget(0, 5)
        self.rep_table.setHorizontalHeaderLabels(["Product Code", "Medicine Name", "Net Qty Sold", "Net Revenue (Rs)", "Gross Profit (Rs)"])
        self.rep_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.rep_table, stretch=1)
        return page

    def _create_users_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>User Roles (Admin / Manager / Cashier) & Security Audit Trail</h3>"))
        self.audit_table = QTableWidget(0, 6)
        self.audit_table.setHorizontalHeaderLabels(["Timestamp", "Username", "Action", "Entity", "Record ID", "Reason"])
        self.audit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.audit_table, stretch=1)
        return page

    def _create_backup_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(QLabel("<h3>Database-Consistent Backups, SHA-256 Verification & Safe Restore</h3>"))
        self.backup_table = QTableWidget(0, 5)
        self.backup_table.setHorizontalHeaderLabels(["Timestamp", "Type", "Size (Bytes)", "SHA-256 Checksum", "File Path"])
        self.backup_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.backup_table, stretch=1)
        return page

    # ------------------------------------------------------------------
    # Data Refresh & Interactive Handlers
    # ------------------------------------------------------------------
    def refresh_all_views(self) -> None:
        metrics = self.finance.get_dashboard_metrics()
        self.kpi_labels["today_sales"].setText(format_pkr(metrics["today_net_sales_paisa"]))
        self.kpi_labels["gross_profit"].setText(format_pkr(metrics["today_gross_profit_paisa"]))
        self.kpi_labels["net_profit"].setText(format_pkr(metrics["today_estimated_net_profit_paisa"]))
        self.kpi_labels["today_purchases"].setText(format_pkr(metrics["today_purchases_paisa"]))
        self.kpi_labels["total_stock"].setText(f"{metrics['total_active_products']} / {metrics['total_sellable_units']}")
        self.kpi_labels["low_stock"].setText(str(metrics["low_stock_count"]))
        self.kpi_labels["near_expiry"].setText(str(metrics["near_expiry_count"]))
        self.kpi_labels["expired_stock"].setText(f"{metrics['expired_batch_count']} ({metrics['expired_units_total']} u)")
        self.kpi_labels["receivables"].setText(format_pkr(metrics["customer_receivables_paisa"]))
        self.kpi_labels["payables"].setText(format_pkr(metrics["supplier_payables_paisa"]))

        # Low stock table
        self.dash_low_table.setRowCount(len(metrics["low_stock_items"]))
        for r_idx, item in enumerate(metrics["low_stock_items"]):
            self.dash_low_table.setItem(r_idx, 0, QTableWidgetItem(item["product_code"]))
            self.dash_low_table.setItem(r_idx, 1, QTableWidgetItem(item["medicine_name"]))
            self.dash_low_table.setItem(r_idx, 2, QTableWidgetItem(str(item["sellable_stock"])))
            self.dash_low_table.setItem(r_idx, 3, QTableWidgetItem(str(item["min_stock_threshold"])))

        # Expired + Near expiry table
        exp_combined = metrics["expired_items"] + metrics["near_expiry_items"]
        self.dash_exp_table.setRowCount(len(exp_combined))
        for r_idx, b in enumerate(exp_combined):
            self.dash_exp_table.setItem(r_idx, 0, QTableWidgetItem(b["medicine_name"]))
            self.dash_exp_table.setItem(r_idx, 1, QTableWidgetItem(b["batch_number"]))
            self.dash_exp_table.setItem(r_idx, 2, QTableWidgetItem(b["expiry_date"]))
            self.dash_exp_table.setItem(r_idx, 3, QTableWidgetItem(str(b["days_to_expiry"])))
            self.dash_exp_table.setItem(r_idx, 4, QTableWidgetItem(str(b["qty_remaining"])))

        self.refresh_medicines_table()

    def refresh_medicines_table(self) -> None:
        q = self.med_search_edit.text() if hasattr(self, "med_search_edit") else ""
        prods = self.inventory.search_products(query=q)
        self.med_table.setRowCount(len(prods))
        self.pos_search_combo.clear()
        for r_idx, p in enumerate(prods):
            self.pos_search_combo.addItem(f"{p['medicine_name']} {p['strength']} ({p['primary_barcode']})", p["id"])
            self.med_table.setItem(r_idx, 0, QTableWidgetItem(p["product_code"]))
            self.med_table.setItem(r_idx, 1, QTableWidgetItem(p["medicine_name"]))
            self.med_table.setItem(r_idx, 2, QTableWidgetItem(p["generic_name"]))
            self.med_table.setItem(r_idx, 3, QTableWidgetItem(p["manufacturer"]))
            self.med_table.setItem(r_idx, 4, QTableWidgetItem(p["strength"]))
            self.med_table.setItem(r_idx, 5, QTableWidgetItem(p["primary_barcode"]))
            self.med_table.setItem(r_idx, 6, QTableWidgetItem(format_pkr(p["default_purchase_price_paisa"], False)))
            self.med_table.setItem(r_idx, 7, QTableWidgetItem(format_pkr(p["default_sale_price_paisa"], False)))
            self.med_table.setItem(r_idx, 8, QTableWidgetItem(str(p["sellable_stock"])))

    def open_add_medicine_dialog(self, prefill_barcode: str = "") -> None:
        dlg = NewMedicineDialog(self.inventory, self.current_user["id"], prefill_barcode=prefill_barcode, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.created_product:
            self.refresh_all_views()

    def handle_pos_barcode_scan(self) -> None:
        code = self.pos_barcode_input.text().strip()
        self.pos_barcode_input.clear()
        if not code:
            return
        scan_res = self.inventory.scan_barcode(code)
        if not scan_res["found"]:
            dlg = NewMedicineDialog(self.inventory, self.current_user["id"], prefill_barcode=code, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.created_product:
                self.refresh_all_views()
                self._add_product_to_pos_cart(dlg.created_product["id"], 1)
            return

        prod = scan_res["product"]
        mult = int(scan_res.get("pack_multiplier", 1))
        self._add_product_to_pos_cart(prod["id"], mult)

    def add_selected_combo_to_cart(self) -> None:
        pid = self.pos_search_combo.currentData()
        if pid:
            self._add_product_to_pos_cart(int(pid), 1)

    def _add_product_to_pos_cart(self, product_id: int, qty_to_add: int) -> None:
        prod = self.inventory.get_product_by_id(product_id)
        for item in self.pos_cart:
            if item["product_id"] == product_id:
                item["qty"] += qty_to_add
                self._render_pos_cart()
                return
        self.pos_cart.append(
            {
                "product_id": product_id,
                "product_code": prod["product_code"],
                "medicine_name": f"{prod['medicine_name']} {prod['strength']}".strip(),
                "qty": qty_to_add,
                "sale_unit_type": "UNIT",
                "unit_price_paisa": prod["default_sale_price_paisa"],
            }
        )
        self._render_pos_cart()

    def _render_pos_cart(self) -> None:
        self.pos_table.setRowCount(len(self.pos_cart))
        for idx, item in enumerate(self.pos_cart):
            line_tot = item["qty"] * item["unit_price_paisa"]
            self.pos_table.setItem(idx, 0, QTableWidgetItem(item["product_code"]))
            self.pos_table.setItem(idx, 1, QTableWidgetItem(item["medicine_name"]))
            self.pos_table.setItem(idx, 2, QTableWidgetItem("Auto-FEFO"))
            self.pos_table.setItem(idx, 3, QTableWidgetItem("Earliest Valid"))
            self.pos_table.setItem(idx, 4, QTableWidgetItem(item["sale_unit_type"]))
            self.pos_table.setItem(idx, 5, QTableWidgetItem(str(item["qty"])))
            self.pos_table.setItem(idx, 6, QTableWidgetItem(format_pkr(item["unit_price_paisa"], False)))
            self.pos_table.setItem(idx, 7, QTableWidgetItem(format_pkr(line_tot, False)))
        self.update_pos_totals()

    def update_pos_totals(self) -> None:
        sub_paisa = sum(i["qty"] * i["unit_price_paisa"] for i in self.pos_cart)
        disc_paisa = int(round(self.pos_discount_spin.value() * 100))
        net_paisa = max(0, sub_paisa - disc_paisa)
        self.pos_total_lbl.setText(f"Grand Total: {format_pkr(net_paisa)}")

    def clear_pos_cart(self) -> None:
        self.pos_cart.clear()
        self._render_pos_cart()

    def complete_pos_sale(self) -> None:
        if not self.pos_cart:
            QMessageBox.information(self, "Empty Cart", "Scan or add at least one medicine before completing sale.")
            return
        try:
            tendered = self.pos_tendered_spin.value()
            inv = self.sales.create_sale_invoice(
                cashier_id=self.current_user["id"],
                cart_items=self.pos_cart,
                payment_method=self.pos_method_combo.currentText(),
                tendered_pkr=str(tendered) if tendered > 0 else None,
                invoice_discount_pkr=str(self.pos_discount_spin.value()),
                idempotency_key=str(uuid.uuid4()),
            )
            self.clear_pos_cart()
            self.refresh_all_views()
            QMessageBox.information(
                self,
                "Sale Completed",
                f"Invoice {inv['invoice_number']} saved!\n"
                f"Grand Total: {format_pkr(inv['grand_total_paisa'])}\n"
                f"Change Due: {format_pkr(inv['change_due_paisa'])}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Sale Error", str(e))
