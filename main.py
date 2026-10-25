"""Main entry point for PakPharma POS & Medical Store Management System."""

from __future__ import annotations

import argparse
import os
import sys

from app.db.database import DatabaseManager, format_pkr
from app.printing.printing_service import PrintingService
from app.services.auth_service import AuthService
from app.services.backup_service import BackupService
from app.services.finance_service import FinanceAndReportService
from app.services.inventory_service import InventoryService
from app.services.purchase_service import PurchaseService
from app.services.sales_service import SalesService
from app.ui.main_window import LoginDialog, PYSIDE6_AVAILABLE, PakPharmaMainWindow


def get_default_data_dir() -> str:
    """Resolve user-writable application data directory on Windows (%LOCALAPPDATA%\\PakPharmaPOS) or Linux."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "PakPharmaPOS")
    return os.path.join(os.path.expanduser("~"), ".pakpharma_pos")


def create_app_context(data_dir: str | None = None) -> dict:
    """Initialize database and all application services."""
    base_dir = os.path.abspath(data_dir or get_default_data_dir())
    db_path = os.path.join(base_dir, "data", "pakpharma.sqlite3")
    backup_dir = os.path.join(base_dir, "backups")

    db = DatabaseManager(db_path)
    auth = AuthService(db)
    inventory = InventoryService(db, auth)
    purchases = PurchaseService(db, auth)
    sales = SalesService(db, auth, inventory)
    finance = FinanceAndReportService(db, auth, inventory)
    backup = BackupService(db, auth, backup_dir)
    printing = PrintingService(db)

    return {
        "base_dir": base_dir,
        "db_path": db_path,
        "backup_dir": backup_dir,
        "db": db,
        "auth": auth,
        "inventory": inventory,
        "purchases": purchases,
        "sales": sales,
        "finance": finance,
        "backup": backup,
        "printing": printing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PakPharma POS - Offline Pharmacy Management System")
    parser.add_argument("--data-dir", type=str, default=None, help="Custom directory for SQLite database and backups")
    parser.add_argument("--status-cli", action="store_true", help="Print database and dashboard KPI status to console and exit")
    args = parser.parse_args()

    ctx = create_app_context(args.data_dir)

    # Automatic scheduled backup on startup if enabled
    if ctx["db"].get_setting("auto_backup_enabled", "1") == "1":
        try:
            ctx["backup"].create_backup(backup_type="SCHEDULED", notes="Automatic startup backup")
        except Exception as e:
            sys.stderr.write(f"Warning: Scheduled startup backup skipped: {e}\n")

    if args.status_cli:
        metrics = ctx["finance"].get_dashboard_metrics()
        print("=== PakPharma POS Status ===")
        print(f"Database Path       : {ctx['db_path']}")
        print(f"Active Products     : {metrics['total_active_products']}")
        print(f"Sellable Units      : {metrics['total_sellable_units']}")
        print(f"Today's Net Sales   : {format_pkr(metrics['today_net_sales_paisa'])}")
        print(f"Today's Gross Profit: {format_pkr(metrics['today_gross_profit_paisa'])}")
        print(f"Today's Net Profit  : {format_pkr(metrics['today_estimated_net_profit_paisa'])}")
        return 0

    if not PYSIDE6_AVAILABLE:
        print(
            "PySide6 GUI runtime is not installed in this environment.\n"
            "On Windows 10/11, launch the compiled PakPharmaPOS.exe or install dependencies via:\n"
            "  pip install -r requirements.txt\n"
            "  python main.py"
        )
        return 1

    from PySide6.QtWidgets import QApplication

    qt_app = QApplication(sys.argv)
    login_dlg = LoginDialog(ctx["auth"])
    if login_dlg.exec() != LoginDialog.DialogCode.Accepted or not login_dlg.authenticated_user:
        return 0

    win = PakPharmaMainWindow(
        db=ctx["db"],
        auth=ctx["auth"],
        inventory=ctx["inventory"],
        purchases=ctx["purchases"],
        sales=ctx["sales"],
        finance=ctx["finance"],
        backup=ctx["backup"],
        printing=ctx["printing"],
        current_user=login_dlg.authenticated_user,
    )
    win.show()
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
