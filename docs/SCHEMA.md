# PharmaCore — Database Schema (SQLite, v1)

Money: `*_paisa` = integer paisa (Rs × 100). Stock: `qty_base` = smallest unit (tablets).
All tables in `electron/db.ts`; indexes on medicines(name), batches(medicine_id, expiry),
sales(created_at), stock_movements(medicine_id, created_at).

| Table | Purpose / key columns |
|---|---|
| users, settings, meta | PIN hash (bcrypt), role, key/value settings, schema_version |
| categories, manufacturers | Lookup lists (medicines.category/company are free text in v1 for import simplicity) |
| medicines | name, generic/salt, company, category, form, strength, tablets_per_strip, strips_per_box, purchase/sale/MRP paisa, reorder_level, rack, schedule, controlled, cold_chain, active |
| medicine_barcodes | medicine_id → barcode UNIQUE (one barcode = one medicine; many barcodes per medicine) |
| batches | medicine_id, batch_no UNIQUE per medicine, expiry (YYYY-MM-DD), qty_base, cost_paisa, mrp_paisa |
| stock_movements | Every purchase/sale/return/adjustment, with batch, ref, user, timestamp |
| suppliers, purchase_orders, purchase_order_items | Supplier master + PO draft |
| purchases, purchase_items, purchase_returns | GRN invoices, lines, returns |
| customers | Credit limit, balance (udhaar), allergies, notes |
| sales, sale_items, sale_payments, sale_returns | Bill (bill_no UNIQUE), FEFO batch lines, split payments, returns to correct batch |
| held_bills | JSON cart for hold/recall |
| expenses, cash_register_shifts | Expense tracking, shift open/close + day-end cash count |
| controlled_drug_register | Controlled sales with patient + prescriber |
| drug_interactions | generic_a, generic_b, severity, message (seeded: Warfarin/Aspirin, Ibuprofen/Aspirin, Metformin/Ciprofloxacin) |
| scan_log, notifications, audit_log | Who scanned what; alerts; who changed what (old/new JSON) |
| medicines_fts | FTS5 virtual table on name/generic/company, kept in sync by triggers |

FEFO rule: sale allocation sorts non-expired batches by expiry ascending; expired batches
are excluded and can never be sold (enforced in both `src/lib/fefo.ts` and `electron/services.ts`).
