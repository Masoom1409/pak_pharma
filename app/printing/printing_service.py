"""Configurable Receipt Printer (58mm/80mm Thermal PDF & ESC/POS Raw), A4 Invoice PDF, and Barcode Label PDF Generator."""

from __future__ import annotations

import os
from typing import Any

from reportlab.graphics.barcode import code128, eanbc
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from app.db.database import DatabaseManager, format_pkr, paisa_to_pkr


class PrintingService:
    """Generates printable 58mm/80mm thermal receipts, ESC/POS raw byte streams, A4 tax invoices, and barcode labels."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def generate_thermal_receipt_pdf(
        self,
        sale_invoice: dict[str, Any],
        output_path: str,
        paper_width_mm: int | None = None,
    ) -> str:
        """Generate a 58mm or 80mm thermal POS receipt PDF using ReportLab."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        settings = self.db.get_all_settings()
        width_mm = paper_width_mm or int(settings.get("receipt_paper_width_mm", "80"))
        if width_mm not in (58, 80):
            width_mm = 80

        lines = sale_invoice.get("lines", [])
        # Calculate dynamic paper height based on number of lines
        height_mm = max(135, 95 + len(lines) * 10)
        page_w = width_mm * mm
        page_h = height_mm * mm

        c = canvas.Canvas(output_path, pagesize=(page_w, page_h))
        margin = 3.5 * mm
        y = page_h - 6 * mm
        center_x = page_w / 2.0

        shop_name = settings.get("shop_name", "Al-Shifa Pharmacy & Medical Store")
        shop_addr = settings.get("shop_address", "Karachi, Pakistan")
        shop_phone = settings.get("shop_phone", "")
        shop_lic = settings.get("shop_license_no", "")
        footer_msg = settings.get("receipt_footer_message", "Thank you for visiting!")

        # Header
        c.setFont("Helvetica-Bold", 10 if width_mm == 80 else 8.5)
        c.drawCentredString(center_x, y, shop_name[:38])
        y -= 4 * mm
        c.setFont("Helvetica", 7.5 if width_mm == 80 else 6.5)
        c.drawCentredString(center_x, y, shop_addr[:48])
        y -= 3.5 * mm
        if shop_phone:
            c.drawCentredString(center_x, y, f"Tel: {shop_phone}")
            y -= 3.5 * mm
        if shop_lic:
            c.drawCentredString(center_x, y, f"Drug Lic: {shop_lic}")
            y -= 3.5 * mm

        # Dashed divider
        c.setDash(2, 2)
        c.line(margin, y, page_w - margin, y)
        c.setDash()
        y -= 4 * mm

        # Invoice metadata
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(margin, y, f"Inv #: {sale_invoice['invoice_number']}")
        c.drawRightString(page_w - margin, y, f"Date: {sale_invoice['invoice_date']}")
        y -= 3.5 * mm
        c.setFont("Helvetica", 7)
        cust_label = sale_invoice.get("registered_customer_name") or sale_invoice.get("customer_name_walkin") or "Walk-in"
        c.drawString(margin, y, f"Customer: {cust_label[:26]}")
        c.drawRightString(page_w - margin, y, f"Cashier: {sale_invoice.get('cashier_name', '')[:14]}")
        y -= 3.5 * mm

        c.setDash(2, 2)
        c.line(margin, y, page_w - margin, y)
        c.setDash()
        y -= 4 * mm

        # Table Header
        c.setFont("Helvetica-Bold", 7)
        c.drawString(margin, y, "Item / Batch")
        c.drawRightString(page_w - 28 * mm, y, "Qty")
        c.drawRightString(page_w - 15 * mm, y, "Rate")
        c.drawRightString(page_w - margin, y, "Total")
        y -= 2.5 * mm
        c.line(margin, y, page_w - margin, y)
        y -= 3.5 * mm

        # Line Items
        c.setFont("Helvetica", 7)
        for sl in lines:
            med_title = f"{sl.get('medicine_name', 'Item')} {sl.get('strength', '')}".strip()
            c.drawString(margin, y, med_title[:28])
            y -= 3.2 * mm
            batch_info = f"  [{sl['batch_number']} Exp:{sl['expiry_date']}]"
            c.setFont("Helvetica", 6.2)
            c.drawString(margin, y, batch_info[:26])
            c.setFont("Helvetica", 7)
            c.drawRightString(page_w - 28 * mm, y, str(sl["qty_units"]))
            c.drawRightString(page_w - 15 * mm, y, format_pkr(sl["unit_price_paisa"], False))
            c.drawRightString(page_w - margin, y, format_pkr(sl["line_total_paisa"], False))
            y -= 3.8 * mm

        c.setDash(2, 2)
        c.line(margin, y, page_w - margin, y)
        c.setDash()
        y -= 4 * mm

        # Totals section
        c.setFont("Helvetica", 7.5)
        c.drawString(margin, y, "Subtotal:")
        c.drawRightString(page_w - margin, y, format_pkr(sale_invoice["subtotal_paisa"]))
        y -= 3.5 * mm

        if int(sale_invoice.get("discount_paisa", 0)) > 0:
            c.drawString(margin, y, "Invoice Discount:")
            c.drawRightString(page_w - margin, y, f"-{format_pkr(sale_invoice['discount_paisa'])}")
            y -= 3.5 * mm

        if int(sale_invoice.get("tax_paisa", 0)) > 0:
            rate_pct = int(sale_invoice.get("tax_rate_bps", 0)) / 100.0
            c.drawString(margin, y, f"Tax ({rate_pct:.2f}%):")
            c.drawRightString(page_w - margin, y, format_pkr(sale_invoice["tax_paisa"]))
            y -= 3.5 * mm

        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, "GRAND TOTAL:")
        c.drawRightString(page_w - margin, y, format_pkr(sale_invoice["grand_total_paisa"]))
        y -= 4.2 * mm

        c.setFont("Helvetica", 7.5)
        c.drawString(margin, y, f"Paid ({sale_invoice['payment_method']}):")
        c.drawRightString(page_w - margin, y, format_pkr(sale_invoice["paid_paisa"]))
        y -= 3.5 * mm

        c.drawString(margin, y, "Change Due:")
        c.drawRightString(page_w - margin, y, format_pkr(sale_invoice["change_due_paisa"]))
        y -= 3.5 * mm

        if int(sale_invoice.get("credit_due_paisa", 0)) > 0:
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(margin, y, "Credit Balance Due:")
            c.drawRightString(page_w - margin, y, format_pkr(sale_invoice["credit_due_paisa"]))
            y -= 4 * mm

        # Barcode of Invoice Number for fast return scanning
        y -= 9 * mm
        try:
            bc = code128.Code128(sale_invoice["invoice_number"], barHeight=7 * mm, barWidth=0.28 * mm)
            bc.drawOn(c, max(margin, center_x - bc.width / 2.0), y)
            y -= 3.5 * mm
        except Exception:
            pass

        # Footer message
        c.setFont("Helvetica-Oblique", 6.5)
        words = footer_msg.split()
        line_buf = ""
        for w in words:
            if len(line_buf) + len(w) + 1 <= 46:
                line_buf = f"{line_buf} {w}".strip()
            else:
                c.drawCentredString(center_x, y, line_buf)
                y -= 3 * mm
                line_buf = w
        if line_buf:
            c.drawCentredString(center_x, y, line_buf)

        c.showPage()
        c.save()
        return os.path.abspath(output_path)

    def generate_escpos_raw_bytes(self, sale_invoice: dict[str, Any], width_chars: int = 42) -> bytes:
        """Generate standard ESC/POS raw command byte stream for direct USB/Serial thermal printers."""
        settings = self.db.get_all_settings()
        ESC = b"\x1b"
        GS = b"\x1d"
        INIT = ESC + b"@"
        ALIGN_CENTER = ESC + b"a\x01"
        ALIGN_LEFT = ESC + b"a\x00"
        BOLD_ON = ESC + b"E\x01"
        BOLD_OFF = ESC + b"E\x00"
        CUT_PAPER = GS + b"V\x41\x03"

        out = bytearray()
        out.extend(INIT)
        out.extend(ALIGN_CENTER)
        out.extend(BOLD_ON)
        out.extend((settings.get("shop_name", "Pharmacy") + "\n").encode("ascii", errors="replace"))
        out.extend(BOLD_OFF)
        out.extend((settings.get("shop_address", "") + "\n").encode("ascii", errors="replace"))
        out.extend((f"Tel: {settings.get('shop_phone', '')}\n").encode("ascii", errors="replace"))
        out.extend(("-" * width_chars + "\n").encode("ascii"))

        out.extend(ALIGN_LEFT)
        out.extend((f"Invoice : {sale_invoice['invoice_number']}\n").encode("ascii"))
        out.extend((f"Date    : {sale_invoice['invoice_timestamp']}\n").encode("ascii"))
        out.extend(("-" * width_chars + "\n").encode("ascii"))

        for sl in sale_invoice.get("lines", []):
            name = f"{sl.get('medicine_name', 'Item')} ({sl['batch_number']})"[:width_chars]
            out.extend((name + "\n").encode("ascii", errors="replace"))
            qty_rate = f"  {sl['qty_units']} x {format_pkr(sl['unit_price_paisa'], False)}"
            tot_str = format_pkr(sl["line_total_paisa"], False)
            spaces = max(1, width_chars - len(qty_rate) - len(tot_str))
            out.extend((qty_rate + (" " * spaces) + tot_str + "\n").encode("ascii"))

        out.extend(("-" * width_chars + "\n").encode("ascii"))
        out.extend(BOLD_ON)
        gt_label = "GRAND TOTAL:"
        gt_val = format_pkr(sale_invoice["grand_total_paisa"])
        out.extend((gt_label + (" " * max(1, width_chars - len(gt_label) - len(gt_val))) + gt_val + "\n").encode("ascii"))
        out.extend(BOLD_OFF)
        out.extend((f"Paid ({sale_invoice['payment_method']}): {format_pkr(sale_invoice['paid_paisa'])}\n").encode("ascii"))
        out.extend((f"Change Due: {format_pkr(sale_invoice['change_due_paisa'])}\n").encode("ascii"))
        out.extend(("\n" + settings.get("receipt_footer_message", "") + "\n\n\n").encode("ascii", errors="replace"))
        out.extend(CUT_PAPER)
        return bytes(out)

    def generate_a4_invoice_pdf(self, sale_invoice: dict[str, Any], output_path: str) -> str:
        """Generate a formal A4 Sales / Tax Invoice PDF for institutional or credit customers."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        settings = self.db.get_all_settings()

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ShopTitle",
            parent=styles["Heading1"],
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#1F4E78"),
        )
        sub_style = ParagraphStyle("SubInfo", parent=styles["Normal"], fontSize=9, leading=12)

        elements: list[Any] = []
        elements.append(Paragraph(settings.get("shop_name", "Al-Shifa Pharmacy & Medical Store"), title_style))
        elements.append(
            Paragraph(
                f"{settings.get('shop_address', '')}<br/>"
                f"Phone: {settings.get('shop_phone', '')} | Drug Sale License: {settings.get('shop_license_no', '')}",
                sub_style,
            )
        )
        elements.append(Spacer(1, 5 * mm))

        cust_name = sale_invoice.get("registered_customer_name") or sale_invoice.get("customer_name_walkin") or "Walk-in Customer"
        meta_data = [
            [
                f"Invoice Number: {sale_invoice['invoice_number']}",
                f"Invoice Date: {sale_invoice['invoice_date']}",
            ],
            [
                f"Customer: {cust_name}",
                f"Payment Method: {sale_invoice['payment_method']} ({sale_invoice['status']})",
            ],
            [
                f"Doctor / Ref: {sale_invoice.get('doctor_name') or 'N/A'}",
                f"Cashier: {sale_invoice.get('cashier_name', '')}",
            ],
        ]
        meta_table = Table(meta_data, colWidths=[90 * mm, 90 * mm])
        meta_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ]
            )
        )
        elements.append(meta_table)
        elements.append(Spacer(1, 6 * mm))

        # Line items table
        table_rows = [
            ["#", "Product / Medicine", "Batch #", "Expiry", "Qty", "Unit Rate", "Disc", "Line Total"]
        ]
        for idx, sl in enumerate(sale_invoice.get("lines", []), start=1):
            med_desc = f"{sl.get('medicine_name', '')} {sl.get('strength', '')} ({sl.get('dosage_form', '')})".strip()
            table_rows.append(
                [
                    str(idx),
                    med_desc[:38],
                    sl["batch_number"],
                    sl["expiry_date"],
                    str(sl["qty_units"]),
                    format_pkr(sl["unit_price_paisa"]),
                    format_pkr(sl["line_discount_paisa"]),
                    format_pkr(sl["line_total_paisa"]),
                ]
            )

        # Summary rows
        table_rows.append(["", "", "", "", "", "", "Subtotal:", format_pkr(sale_invoice["subtotal_paisa"])])
        table_rows.append(["", "", "", "", "", "", "Discount:", f"-{format_pkr(sale_invoice['discount_paisa'])}"])
        table_rows.append(["", "", "", "", "", "", "Tax:", format_pkr(sale_invoice["tax_paisa"])])
        table_rows.append(["", "", "", "", "", "", "Grand Total:", format_pkr(sale_invoice["grand_total_paisa"])])
        table_rows.append(["", "", "", "", "", "", "Amount Paid:", format_pkr(sale_invoice["paid_paisa"])])
        table_rows.append(["", "", "", "", "", "", "Change / Credit:", format_pkr(sale_invoice["change_due_paisa"] or sale_invoice["credit_due_paisa"])])

        col_widths = [10 * mm, 56 * mm, 24 * mm, 22 * mm, 14 * mm, 18 * mm, 16 * mm, 20 * mm]
        t = Table(table_rows, colWidths=col_widths, repeatRows=1)
        num_items = len(sale_invoice.get("lines", []))
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, num_items), 0.4, colors.HexColor("#CBD5E1")),
                    ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                    ("FONTNAME", (6, num_items + 1), (7, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (6, num_items + 4), (7, num_items + 4), 1.0, colors.HexColor("#1F4E78")),
                ]
            )
        )
        elements.append(t)
        elements.append(Spacer(1, 8 * mm))
        elements.append(Paragraph(settings.get("receipt_footer_message", ""), sub_style))

        doc.build(elements)
        return os.path.abspath(output_path)

    def generate_barcode_labels_pdf(
        self,
        product: dict[str, Any],
        output_path: str,
        copies: int = 1,
        label_width_mm: float = 50.0,
        label_height_mm: float = 25.0,
    ) -> str:
        """Generate printable thermal barcode stickers (default 50mm x 25mm for Zebra/Xprinter/TSC label printers).

        Each label prints:
        - Shop name header
        - Medicine name + strength + dosage form
        - Scannable vector barcode (EAN-13 or Code 128)
        - Human-readable barcode digits + Retail Price in PKR
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        copies = max(1, int(copies))
        shop_name = self.db.get_setting("shop_name", "Al-Shifa Pharmacy")
        barcode_str = product.get("primary_barcode") or product.get("product_code") or "0000000000000"
        med_line = f"{product.get('medicine_name', '')} {product.get('strength', '')}".strip()
        price_str = format_pkr(product.get("default_sale_price_paisa", 0))

        w = label_width_mm * mm
        h = label_height_mm * mm
        c = canvas.Canvas(output_path, pagesize=(w, h))

        for _ in range(copies):
            c.setFont("Helvetica-Bold", 6.5)
            c.drawCentredString(w / 2.0, h - 3.8 * mm, shop_name[:30])

            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(w / 2.0, h - 7.2 * mm, med_line[:26])

            # Draw vector barcode
            bc_drawn = False
            if barcode_str.isdigit() and len(barcode_str) == 13:
                try:
                    d = Drawing(w - 6 * mm, 10 * mm)
                    ean = eanbc.Ean13BarcodeWidget(barcode_str)
                    ean.barHeight = 9 * mm
                    ean.barWidth = 0.28 * mm
                    d.add(ean)
                    d.drawOn(c, 5 * mm, 6.2 * mm)
                    bc_drawn = True
                except Exception:
                    bc_drawn = False

            if not bc_drawn:
                bc128 = code128.Code128(barcode_str, barHeight=8.5 * mm, barWidth=0.26 * mm)
                bc128.drawOn(c, max(2 * mm, (w - bc128.width) / 2.0), 7.2 * mm)
                c.setFont("Helvetica", 6.5)
                c.drawCentredString(w / 2.0, 4.5 * mm, barcode_str)

            c.setFont("Helvetica-Bold", 8.0)
            c.drawCentredString(w / 2.0, 1.5 * mm, f"MRP: {price_str}")
            c.showPage()

        c.save()
        return os.path.abspath(output_path)
