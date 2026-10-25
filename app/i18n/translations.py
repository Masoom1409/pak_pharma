"""Bilingual English and Urdu (اردو) translation dictionary and RTL layout helper for PakPharma POS."""

from __future__ import annotations

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "PakPharma POS & Medical Store Management System",
        "nav_dashboard": "1. Dashboard",
        "nav_pos": "2. POS Billing (F2)",
        "nav_medicines": "3. Medicines & Barcodes",
        "nav_purchases": "4. Purchases & Stock In",
        "nav_inventory": "5. Batches & Expiry (FEFO)",
        "nav_returns": "6. Returns & Write-Offs",
        "nav_parties": "7. Suppliers & Customers",
        "nav_reports": "8. Reports & Expenses",
        "nav_users": "9. Users & Audit Trail",
        "nav_backup": "10. Backup & Settings",
        "kpi_today_sales": "Today's Net Sales",
        "kpi_gross_profit": "Today's Gross Profit",
        "kpi_net_profit": "Estimated Net Profit",
        "kpi_total_stock": "Active Products / Units",
        "kpi_low_stock": "Low-Stock Medicines",
        "kpi_near_expiry": "Near-Expiry Batches (<=90d)",
        "kpi_expired": "Expired Batches (Blocked)",
        "kpi_purchases": "Today's Purchases",
        "kpi_receivables": "Customer Receivables",
        "kpi_payables": "Supplier Payables",
        "scan_barcode_placeholder": "Scan USB Barcode or Enter Code and press Enter...",
        "btn_new_sale": "New Sale (F2)",
        "btn_add_medicine": "Add Medicine (F3)",
        "btn_purchase_stock": "Purchase Stock (F4)",
        "btn_print_receipt": "Complete & Print Receipt (F12)",
        "btn_print_label": "Print Barcode Label",
        "lang_toggle": "اردو (Urdu) / English",
    },
    "ur": {
        "app_title": "پاک فارما پی او ایس اینڈ میڈیکل سٹور مینجمنٹ سسٹم",
        "nav_dashboard": "1. ڈیش بورڈ (Dashboard)",
        "nav_pos": "2. بلنگ کاؤنٹر (POS Billing)",
        "nav_medicines": "3. ادویات اور بارکوڈز (Medicines)",
        "nav_purchases": "4. خریداری اور اسٹاک آمد (Purchases)",
        "nav_inventory": "5. بیچ اور ایکسپائری (Expiry/FEFO)",
        "nav_returns": "6. واپسی اور اسٹاک ایڈجسٹمنٹ (Returns)",
        "nav_parties": "7. سپلائرز اور کسٹمرز (Parties)",
        "nav_reports": "8. رپورٹس اور اخراجات (Reports)",
        "nav_users": "9. صارفین اور آڈٹ لاگ (Users/Audit)",
        "nav_backup": "10. بیک اپ اور سیٹنگز (Backup)",
        "kpi_today_sales": "آج کی کل فروخت (Net Sales)",
        "kpi_gross_profit": "آج کا مجموعی منافع (Gross Profit)",
        "kpi_net_profit": "تخمینی خالص منافع (Est. Net Profit)",
        "kpi_total_stock": "کل ادویات اور اسٹاک یونٹس",
        "kpi_low_stock": "کم اسٹاک والی ادویات (Low Stock)",
        "kpi_near_expiry": "قریب المیعاد ادویات (Near Expiry)",
        "kpi_expired": "زائد المیعاد اسٹاک (Expired)",
        "kpi_purchases": "آج کی خریداری (Purchases)",
        "kpi_receivables": "کسٹمر واجبات (Receivables)",
        "kpi_payables": "سپلائر واجبات (Payables)",
        "scan_barcode_placeholder": "بارکوڈ اسکین کریں اور انٹر دبائیں...",
        "btn_new_sale": "نیا بل بنائیں (F2)",
        "btn_add_medicine": "نئی دوا شامل کریں (F3)",
        "btn_purchase_stock": "اسٹاک خریداری (F4)",
        "btn_print_receipt": "بل محفوظ اور پرنٹ کریں (F12)",
        "btn_print_label": "بارکوڈ لیبل پرنٹ کریں",
        "lang_toggle": "English / اردو",
    },
}


def tr(key: str, lang: str = "en") -> str:
    """Translate a UI key into English ('en') or Urdu ('ur')."""
    lang_dict = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    return lang_dict.get(key, TRANSLATIONS["en"].get(key, key))
