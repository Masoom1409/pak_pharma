# PakPharma POS & Medical Store Management System (v1.0.0)

**Offline-First Windows 10/11 Retail Pharmacy Inventory, FEFO Batch Tracking, Barcode Billing & Accounting System for Pakistan**

## 1. Technology Stack & Architectural Highlights

* **Desktop User Interface**: Python 3.11+ with **PySide6 (Qt6)** (`app/ui/main_window.py`) featuring a dark navigation sidebar, high-contrast KPI cards, keyboard-first POS shortcuts (`F2` New Sale, `F3` Add Medicine, `F4` Purchases, `F12` Complete & Print Receipt), dedicated USB barcode scanner input field, and one-click **English / Urdu (`اردو`)** RTL language toggle (`app/i18n/translations.py`).
* **Local Database & Persistence**: **SQLite 3** (`app/db/database.py`) configured in **Write-Ahead Logging (`PRAGMA journal_mode = WAL`)** mode with strict foreign keys (`PRAGMA foreign_keys = ON`), `BEGIN IMMEDIATE` ACID transactions, and automatic versioned schema migrations (`schema_migrations` table, V1 & V2).
* **Decimal-Safe Currency Arithmetic**: All monetary amounts in Pakistani Rupees (`PKR / Rs`) are stored and calculated as exact 64-bit integer **paisa** (`1 PKR = 100 paisa`) converted via `decimal.Decimal` (`ROUND_HALF_UP`), eliminating IEEE-754 floating-point rounding drift.
* **Security & Audit Trail**: Local user accounts (`ADMIN`, `MANAGER`, `CASHIER`) secured with **PBKDF2-HMAC-SHA256** (200,000 iterations + 16-byte cryptographic salt) and an immutable `audit_logs` table (`app/services/auth_service.py`).
* **Receipt, Invoice & Barcode Label Engine**: **ReportLab** vector PDF & raw **ESC/POS** byte-stream generator (`app/printing/printing_service.py`) supporting **58 mm** and **80 mm** thermal receipt printers, **A4 Tax/Sales Invoices**, and **50 mm × 25 mm** barcode stickers (`EAN-13`, `EAN-8`, `UPC-A`, and `Code 128`).
* **Windows Packaging**: **PyInstaller** (`installer/PakPharmaPOS.spec`) paired with **Inno Setup 6** (`installer/PakPharmaPOS_Installer.iss`) and a one-click batch builder (`installer/build_windows_installer.bat`).

## 2. Reproducible Windows 10 / 11 Build Steps

> **Transparency Note**: Because this development and verification environment runs on a Linux x86_64 container without a Windows PE cross-compiler or `PySide6` wheel repository, the standalone `.exe` binary and Inno Setup `.exe` installer must be compiled on a Windows 10/11 build machine using the included `installer\build_windows_installer.bat` script. Once compiled on the build machine, the resulting `PakPharmaPOS_Setup_v1.0.0.exe` installs and runs 100% offline on any customer Windows 10/11 PC without Python or development tools installed.

### Step-by-Step Build on a Windows Build Machine:
1. Extract `PakPharma_POS_Windows_Project_Source_and_Build_Kit.zip` to `C:\PakPharma_Build\`.
2. Ensure Python 3.11+ (64-bit) and [Inno Setup 6](https://jrsoftware.org/isinfo.php) are installed on the build PC.
3. Double-click `installer\build_windows_installer.bat` (or run from Command Prompt):
   ```bat
   cd C:\PakPharma_Build\pakpharma_pos
   installer\build_windows_installer.bat
   ```
4. The script automatically:
   * Creates an isolated `.venv_build` virtual environment and installs `requirements.txt`.
   * Executes the 20-criteria automated acceptance test suite (`tests/test_acceptance_suite.py`).
   * Runs `pyinstaller --noconfirm --clean installer\PakPharmaPOS.spec` to produce `dist\PakPharmaPOS\PakPharmaPOS.exe`.
   * Invokes Inno Setup (`ISCC.exe installer\PakPharmaPOS_Installer.iss`) to generate `dist_installer\PakPharmaPOS_Setup_v1.0.0.exe`.

## 3. Customer Installation & Uninstallation on Windows 10 / 11

* **Installation**: Run `PakPharmaPOS_Setup_v1.0.0.exe`. No internet connection, Python runtime, or administrator elevation is required. Application binaries are placed in `%LOCALAPPDATA%\Programs\PakPharmaPOS\`, while the SQLite database and backups are stored in `%LOCALAPPDATA%\PakPharmaPOS\data\` and `%LOCALAPPDATA%\PakPharmaPOS\backups\`.
* **Default Login Credentials** (change immediately after first login under *9. Users & Audit Trail*):
  * **Administrator**: Username `admin` / Password `Admin@123`
  * **Manager**: Username `manager` / Password `Manager@123`
  * **Cashier**: Username `cashier` / Password `Cashier@123`
* **Uninstallation & Upgrades**: Uninstalling via *Windows Settings → Apps → Installed Apps → PakPharma POS* removes the application binaries while **preserving** `%LOCALAPPDATA%\PakPharmaPOS\data\pakpharma.sqlite3` and `%LOCALAPPDATA%\PakPharmaPOS\backups\` (`uninsneveruninstall` flag) so shop data is never lost during version upgrades.

## 4. Hardware Compatibility & Setup Guide

### A. USB Barcode Scanners (1D / 2D)
* **Supported Models**: Honeywell Voyager 1200g / 1250g / 1470g, Zebra DS2208 / LS2208, Sunlux XL-6200A / XL-3610, Datalogic QuickScan QW2100, Speed-X, and all standard USB HID Keyboard-Wedge barcode scanners sold in Pakistan.
* **Configuration**:
  1. Plug the scanner into any USB port; Windows 10/11 loads the built-in HID Keyboard driver automatically.
  2. Scan the **"Add CR (Carriage Return / Enter) Suffix"** configuration barcode from your scanner's quick-start card so the scanner sends `Enter` after every scan.
  3. Symbologies supported out of the box: **EAN-13** (international & Pakistani GS1 `896` prefix packs), **EAN-8**, **UPC-A**, and **Code 128** (in-store batch/product labels).

### B. Thermal Receipt Printers (58 mm & 80 mm)
* **Supported Models**: BlackCopper BC-85AC / BC-80POS, Xprinter XP-58IIH / XP-Q200 / XP-N160II, Epson TM-T20III / TM-T82, Speed-X 80mm USB/LAN, Rongta RP80.
* **Configuration**:
  1. Install the manufacturer's Windows printer driver and set paper size to `80mm Roll` or `58mm Roll`.
  2. In PakPharma POS, open **10. Backup & Settings** and set `receipt_paper_width_mm` to `80` or `58`.
  3. PakPharma POS generates both native vector PDF receipts (`generate_thermal_receipt_pdf`) for Windows print spoolers and raw **ESC/POS** command byte streams (`generate_escpos_raw_bytes`) with automatic paper-cut (`GS V A 03`).

### C. Thermal Barcode Label Printers
* **Supported Models**: Xprinter XP-365B / XP-370B, TSC TE244 / TTP-244 Pro, Zebra ZD220 / GK420t, Speed-X Label Printer.
* **Configuration**: Load standard **50 mm × 25 mm** (2" × 1") direct-thermal self-adhesive label rolls. Click **Print Barcode Label** on any medicine in *3. Medicines & Barcodes* to generate scannable EAN-13 or Code 128 sticker sheets showing Shop Name, Medicine + Strength, Barcode, and MRP in PKR.

## 5. Known Limitations & Honest Disclosure

1. **Linux Container Build Environment**: Because this workspace runs inside an isolated Linux container without a Windows OS kernel, `PakPharmaPOS.exe` and `PakPharmaPOS_Setup_v1.0.0.exe` cannot be compiled into Windows PE binaries inside this container. Complete, reproducible build scripts (`PakPharmaPOS.spec`, `PakPharmaPOS_Installer.iss`, and `build_windows_installer.bat`) are provided and verified against the codebase.
2. **Local-Only Backup Risk**: While PakPharma POS performs online SQLite backups (`backup()` API), SHA-256 integrity checks, isolated temporary-DB restore validation, and automatic pre-restore snapshots, **a local-only system on a single PC cannot protect against computer theft, fire, complete disk hardware failure, or ransomware unless the shopkeeper regularly copies backups to an external USB flash drive or off-site storage**.
3. **Regulatory & Tax Configuration**: Pakistani retail pharmacy tax rules (e.g., FBR POS integration or provincial sales tax exemptions on essential medicines) and DRAP scheduling vary by jurisdiction and registration status. Tax rates (`default_tax_rate_bps`) are therefore 100% user-configurable (default `0 bps = 0.00%`) rather than hard-coded.
4. **Starter Catalog Verification**: Every item in the included 20-item demonstration dataset is explicitly flagged `SAMPLE_DEMONSTRATION` with an in-store `200` prefix barcode. Shopkeepers must verify actual physical pack barcodes and DRAP-approved MRPs when receiving live stock.
