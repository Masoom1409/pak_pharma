# PharmaCore — Offline Medical Store Management (Pakistan)

## Assumptions (sensible defaults, change in Settings)
- Money is integer paisa everywhere; bills round to the nearest rupee.
- Seed prices in `electron/db.ts` are per-strip prices; POS converts to per-tablet for
  box/strip/tablet math (10 tablets/strip, 10 strips/box by default, editable per medicine).
- Demo PINs: Owner `1234`, Cashier `1111` — change on first production login.
- Thermal printing: the Electron service writes an ESC/POS receipt stream to `receipts/<bill>.txt`
  and the same text can be routed to a USB/serial thermal printer driver in production.
  A4/PDF export is via the browser print dialog from Reports (CSV export is built in).
- Urdu UI: the language switcher sets RTL layout; Urdu receipts use the same text path
  (full Nastaliq shaping depends on the printer font — use an Urdu-capable thermal printer).

## Run
```bash
npm install
npm run dev        # Vite + Electron (dev)
npm test           # Vitest: FEFO, units, money, scanner
npm run build      # tsc + vite + electron main
npm run build:win  # + electron-builder Windows .exe installer (run on Windows)
```
On Windows the database is at `%APPDATA%/PharmaCore/pharmacy.db` (Electron userData).
In a plain browser, a localStorage demo store is used so the UI can be previewed
without Electron — production data is always SQLite.

## Architecture
- `electron/` — main (secure IPC, contextIsolation ON, nodeIntegration OFF), preload bridge,
  `db.ts` (schema v1 + migrations + 60-medicine seed), `services.ts` (all transactions).
- `src/` — React pages (Dashboard, POS, Inventory, Scan to Add, Purchases/Customers,
  Reports/Audit, Settings), Zustand store, FTS5 search via IPC, Tailwind + shadcn-style UI.
- `src/lib/` — `money.ts` (integer paisa), `units.ts`, `fefo.ts`, `scanner.ts` (keyboard-wedge
  + GS1 batch/expiry parsing), `api.ts` (Electron IPC with browser demo fallback).
- `migrations` — schema is versioned in `electron/db.ts` (`meta.schema_version`); add a new
  migration block and bump `SCHEMA_VERSION` for upgrades — never edit v1 in place after release.
- `tests/core.test.ts` — FEFO (expired batches never sell), unit conversion, money, scanner timing, GS1.

## Security / integrity
- PINs hashed with bcryptjs. Bills are never hard-deleted (void with reason + audit_log).
- Every stock change runs inside a SQLite transaction (sale, return, stock-in, purchase/GRN).
- WAL mode + foreign keys ON. Backup on close + manual backup in Settings (rotating copies
  next to the DB file in Electron).

## Phases delivered
1. Setup, Electron+React+Tailwind, SQLite+migrations, auth/roles, layout, dark mode, EN/UR.
2. Medicine master, batches, inventory, CSV export, scanner engine + Scan to Add.
3. POS: FEFO, units, discounts, payments (Cash/Card/EasyPaisa/JazzCash/Bank/Credit),
   hold/recall, return, substitutes, interaction warning, controlled-drug register, receipt + wa.me.
4. Suppliers, purchases/GRN (atomic), customers & udhaar ledgers, expenses table, day closing
   via cash_register_shifts.
5. Dashboard (Recharts), reports, expiry/low-stock alerts, audit log, backup/restore, settings.
6. Tests, installer config, this README + user manual.
