import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';

export const SCHEMA_VERSION = 1;

const MIGRATIONS: string[] = [`
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, pin_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('Owner','Manager','Pharmacist','Cashier')), active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS manufacturers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS medicines (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, generic TEXT, company TEXT, category TEXT, form TEXT, strength TEXT,
  tablets_per_strip INTEGER DEFAULT 10, strips_per_box INTEGER DEFAULT 10,
  purchase_price_paisa INTEGER DEFAULT 0, sale_price_paisa INTEGER DEFAULT 0, mrp_paisa INTEGER DEFAULT 0,
  reorder_level INTEGER DEFAULT 10, rack TEXT, schedule TEXT DEFAULT 'OTC', controlled INTEGER DEFAULT 0, cold_chain INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, image TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS medicine_barcodes (id INTEGER PRIMARY KEY AUTOINCREMENT, medicine_id INTEGER NOT NULL REFERENCES medicines(id), barcode TEXT UNIQUE NOT NULL, is_primary INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY AUTOINCREMENT, medicine_id INTEGER NOT NULL REFERENCES medicines(id), batch_no TEXT NOT NULL, expiry TEXT NOT NULL, qty_base INTEGER NOT NULL DEFAULT 0, cost_paisa INTEGER DEFAULT 0, mrp_paisa INTEGER DEFAULT 0, UNIQUE(medicine_id, batch_no));
CREATE TABLE IF NOT EXISTS stock_movements (id INTEGER PRIMARY KEY AUTOINCREMENT, medicine_id INTEGER NOT NULL REFERENCES medicines(id), batch_id INTEGER REFERENCES batches(id), type TEXT NOT NULL, qty_base INTEGER NOT NULL, ref_type TEXT, ref_id INTEGER, note TEXT, user_id INTEGER, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, address TEXT, balance_paisa INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS purchase_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id INTEGER REFERENCES suppliers(id), status TEXT DEFAULT 'DRAFT', total_paisa INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS purchase_order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, po_id INTEGER REFERENCES purchase_orders(id), medicine_id INTEGER REFERENCES medicines(id), qty_base INTEGER, cost_paisa INTEGER);
CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id INTEGER REFERENCES suppliers(id), invoice_no TEXT, total_paisa INTEGER DEFAULT 0, paid_paisa INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS purchase_items (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER REFERENCES purchases(id), medicine_id INTEGER REFERENCES medicines(id), batch_id INTEGER REFERENCES batches(id), qty_base INTEGER, cost_paisa INTEGER);
CREATE TABLE IF NOT EXISTS purchase_returns (id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER REFERENCES purchases(id), medicine_id INTEGER REFERENCES medicines(id), qty_base INTEGER, reason TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, address TEXT, credit_limit_paisa INTEGER DEFAULT 0, balance_paisa INTEGER DEFAULT 0, allergies TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY AUTOINCREMENT, bill_no TEXT UNIQUE NOT NULL, customer_id INTEGER REFERENCES customers(id), user_id INTEGER REFERENCES users(id), shift_id INTEGER, subtotal_paisa INTEGER DEFAULT 0, discount_paisa INTEGER DEFAULT 0, tax_paisa INTEGER DEFAULT 0, total_paisa INTEGER DEFAULT 0, paid_paisa INTEGER DEFAULT 0, payment_method TEXT DEFAULT 'Cash', status TEXT DEFAULT 'COMPLETED', doctor_name TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS sale_items (id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER NOT NULL REFERENCES sales(id), medicine_id INTEGER REFERENCES medicines(id), batch_id INTEGER REFERENCES batches(id), qty_base INTEGER NOT NULL, unit TEXT, unit_qty REAL, price_paisa INTEGER, discount_paisa INTEGER DEFAULT 0, amount_paisa INTEGER);
CREATE TABLE IF NOT EXISTS sale_payments (id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER REFERENCES sales(id), method TEXT, amount_paisa INTEGER, ref TEXT);
CREATE TABLE IF NOT EXISTS sale_returns (id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER REFERENCES sales(id), medicine_id INTEGER REFERENCES medicines(id), batch_id INTEGER REFERENCES batches(id), qty_base INTEGER, reason TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS held_bills (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, amount_paisa INTEGER, category TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS cash_register_shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id), opening_paisa INTEGER DEFAULT 0, closing_paisa INTEGER, status TEXT DEFAULT 'OPEN', opened_at TEXT DEFAULT (datetime('now')), closed_at TEXT);
CREATE TABLE IF NOT EXISTS controlled_drug_register (id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER REFERENCES sales(id), medicine_id INTEGER REFERENCES medicines(id), qty_base INTEGER, patient_name TEXT, prescriber TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS drug_interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, generic_a TEXT NOT NULL, generic_b TEXT NOT NULL, severity TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS scan_log (id INTEGER PRIMARY KEY AUTOINCREMENT, barcode TEXT, medicine_id INTEGER, user_id INTEGER, result TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, message TEXT, ref_id INTEGER, seen INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, entity TEXT, entity_id INTEGER, old_value TEXT, new_value TEXT, created_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name);
CREATE INDEX IF NOT EXISTS idx_batches_medicine ON batches(medicine_id, expiry);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_movements_medicine ON stock_movements(medicine_id, created_at);
CREATE VIRTUAL TABLE IF NOT EXISTS medicines_fts USING fts5(name, generic, company, content='medicines', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS medicines_ai AFTER INSERT ON medicines BEGIN INSERT INTO medicines_fts(rowid, name, generic, company) VALUES (new.id, new.name, new.generic, new.company); END;
CREATE TRIGGER IF NOT EXISTS medicines_ad AFTER DELETE ON medicines BEGIN INSERT INTO medicines_fts(medicines_fts, rowid, name, generic, company) VALUES ('delete', old.id, old.name, old.generic, old.company); END;
`];

const SEED_MEDS: [string, string, string, string, string, number, number][] = [
  ['Panadol Extra', 'Paracetamol + Caffeine', 'GSK', 'Tablet', '500mg', 120, 180],
  ['Panadol', 'Paracetamol', 'GSK', 'Tablet', '500mg', 95, 150],
  ['Brufen', 'Ibuprofen', 'Abbott', 'Tablet', '400mg', 210, 320],
  ['Augmentin', 'Co-Amoxiclav', 'GSK', 'Tablet', '625mg', 1450, 1850],
  ['Flagyl', 'Metronidazole', 'Sanofi', 'Tablet', '400mg', 180, 280],
  ['Arinac', 'Ibuprofen + Pseudoephedrine', 'Abbott', 'Tablet', '400mg', 260, 390],
  ['Disprin', 'Aspirin', 'Reckitt', 'Tablet', '300mg', 80, 130],
  ['Cataflam', 'Diclofenac', 'Novartis', 'Tablet', '50mg', 340, 500],
  ['Voltaren', 'Diclofenac', 'Novartis', 'Gel', '1%', 620, 890],
  ['Septran', 'Co-Trimoxazole', 'GSK', 'Tablet', '480mg', 150, 240],
  ['Strepsils', 'Amylmetacresol', 'Reckitt', 'Lozenge', '-', 420, 650],
  ['Gaviscon', 'Alginate', 'Reckitt', 'Syrup', '150ml', 780, 1150],
  ['Omeprazole', 'Omeprazole', 'Getz', 'Capsule', '20mg', 380, 580],
  ['Esomeprazole', 'Esomeprazole', 'Getz', 'Capsule', '40mg', 520, 780],
  ['Loprin', 'Aspirin', 'Tabros', 'Tablet', '75mg', 140, 220],
  ['Cardioprin', 'Aspirin', 'Tabros', 'Tablet', '100mg', 160, 250],
  ['Atorva', 'Atorvastatin', 'Getz', 'Tablet', '10mg', 420, 640],
  ['Amlodipine', 'Amlodipine', 'Sandoz', 'Tablet', '5mg', 190, 300],
  ['Losartan', 'Losartan', 'Getz', 'Tablet', '50mg', 360, 540],
  ['Metformin', 'Metformin', 'Getz', 'Tablet', '500mg', 210, 320],
  ['Glucophage', 'Metformin', 'Merck', 'Tablet', '500mg', 380, 560],
  ['Insulin R', 'Insulin Regular', 'Novo Nordisk', 'Injection', '100IU', 1450, 1950],
  ['Ciprofloxacin', 'Ciprofloxacin', 'Sandoz', 'Tablet', '500mg', 290, 440],
  ['Azithromycin', 'Azithromycin', 'Pfizer', 'Tablet', '500mg', 680, 980],
  ['Cefixime', 'Cefixime', 'Getz', 'Capsule', '400mg', 720, 1050],
  ['Amoxicillin', 'Amoxicillin', 'GSK', 'Capsule', '500mg', 320, 480],
  ['Doxycycline', 'Doxycycline', 'Tabros', 'Capsule', '100mg', 240, 370],
  ['Cetirizine', 'Cetirizine', 'Sandoz', 'Tablet', '10mg', 150, 240],
  ['Loratadine', 'Loratadine', 'Tabros', 'Tablet', '10mg', 170, 260],
  ['Montelukast', 'Montelukast', 'Getz', 'Tablet', '10mg', 480, 720],
  ['Salbutamol', 'Salbutamol', 'GSK', 'Inhaler', '100mcg', 890, 1250],
  ['Ventolin', 'Salbutamol', 'GSK', 'Syrup', '120ml', 340, 510],
  ['Betnesol', 'Betamethasone', 'GSK', 'Tablet', '0.5mg', 210, 330],
  ['Hydrocortisone', 'Hydrocortisone', 'Tabros', 'Cream', '1%', 380, 570],
  ['Polyfax', 'Polymyxin + Bacitracin', 'GSK', 'Ointment', '20g', 420, 640],
  ['Betnovate', 'Betamethasone', 'GSK', 'Cream', '0.1%', 560, 840],
  ['Calpol', 'Paracetamol', 'GSK', 'Syrup', '120ml', 280, 420],
  ['Brufen Syrup', 'Ibuprofen', 'Abbott', 'Syrup', '120ml', 310, 470],
  ['ORS', 'Oral Rehydration Salts', 'Tabros', 'Sachet', '-', 60, 100],
  ['Electral', 'ORS', 'Tabros', 'Sachet', '-', 55, 95],
  ['Imodium', 'Loperamide', 'Janssen', 'Capsule', '2mg', 390, 590],
  ['Domperidone', 'Domperidone', 'Getz', 'Tablet', '10mg', 180, 280],
  ['Gravinate', 'Dimenhydrinate', 'Tabros', 'Tablet', '50mg', 160, 250],
  ['Xanax', 'Alprazolam', 'Pfizer', 'Tablet', '0.5mg', 780, 1150],
  ['Lexotanil', 'Bromazepam', 'Roche', 'Tablet', '3mg', 690, 1020],
  ['Tramadol', 'Tramadol', 'Sandoz', 'Capsule', '50mg', 420, 640],
  ['Codeine Syrup', 'Codeine', 'Tabros', 'Syrup', '120ml', 520, 780],
  ['Vitamin D3', 'Cholecalciferol', 'Tabros', 'Capsule', '50000IU', 480, 720],
  ['Evion', 'Vitamin E', 'Merck', 'Capsule', '400mg', 360, 540],
  ['Folic Acid', 'Folic Acid', 'Tabros', 'Tablet', '5mg', 90, 150],
  ['Iron Plus', 'Ferrous Sulphate', 'Abbott', 'Tablet', '-', 240, 370],
  ['Calcium D', 'Calcium + Vit D', 'Tabros', 'Tablet', '-', 290, 440],
  ['Surbex-Z', 'Multivitamin', 'Abbott', 'Tablet', '-', 620, 920],
  ['Enzar HS', 'Pancreatin', 'Tabros', 'Capsule', '-', 340, 520],
  ['Creon', 'Pancreatin', 'Abbott', 'Capsule', '-', 1450, 2100],
  ['Dulcolax', 'Bisacodyl', 'Sanofi', 'Tablet', '5mg', 210, 320],
  ['Lactulose', 'Lactulose', 'Abbott', 'Syrup', '120ml', 420, 640],
  ['Provas', 'Paracetamol IV', 'Tabros', 'Injection', '1g', 890, 1300],
  ['Avil', 'Pheniramine', 'Sanofi', 'Tablet', '25mg', 140, 220],
  ['Rigix', 'Cetirizine', 'Tabros', 'Tablet', '10mg', 130, 210],
];

export function openDb(dbPath: string): Database.Database {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');
  const cur = (db.prepare("SELECT value FROM meta WHERE key='schema_version'").get() as any)?.value;
  if (!cur) {
    db.exec(MIGRATIONS[0]);
    db.prepare("INSERT INTO meta(key,value) VALUES('schema_version',?)").run(String(SCHEMA_VERSION));
    seed(db);
  }
  return db;
}

function seed(db: Database.Database) {
  const bcrypt = require('bcryptjs');
  const insUser = db.prepare('INSERT INTO users(name,pin_hash,role) VALUES(?,?,?)');
  insUser.run('Owner', bcrypt.hashSync('1234', 10), 'Owner');
  insUser.run('Cashier', bcrypt.hashSync('1111', 10), 'Cashier');
  const insSup = db.prepare('INSERT INTO suppliers(name,phone) VALUES(?,?)');
  insSup.run('Karachi Pharma Distributors', '0300-1234567');
  insSup.run('Tabros Traders', '0321-7654321');
  const insCust = db.prepare('INSERT INTO customers(name,phone) VALUES(?,?)');
  insCust.run('Walk-in Customer', '');
  insCust.run('Ahmed Raza', '0300-9998888');
  const insMed = db.prepare(`INSERT INTO medicines(name,generic,company,form,strength,purchase_price_paisa,sale_price_paisa,mrp_paisa,reorder_level,rack,controlled) VALUES(?,?,?,?,?,?,?,?,?,?,?)`);
  const insBar = db.prepare('INSERT INTO medicine_barcodes(medicine_id,barcode,is_primary) VALUES(?,?,1)');
  const insBatch = db.prepare('INSERT INTO batches(medicine_id,batch_no,expiry,qty_base,cost_paisa) VALUES(?,?,?,?,?)');
  SEED_MEDS.forEach(([name, generic, company, form, strength, buy, sell], i) => {
    const controlled = /Xanax|Lexotanil|Tramadol|Codeine/.test(name) ? 1 : 0;
    const r = insMed.run(name, generic, company, form, strength, buy * 100, sell * 100, sell * 100, 20, `A-${(i % 8) + 1}`, controlled);
    const id = Number(r.lastInsertRowid);
    insBar.run(id, `890${String(1000000 + i).slice(1)}${i % 10}`);
    // Two batches: one near expiry for alert testing, one long-dated, FEFO order differs.
    insBatch.run(id, `B${100 + i}`, '2027-06-30', 500, buy * 100);
    insBatch.run(id, `B${200 + i}`, '2026-12-15', 200, buy * 100);
  });
  db.prepare(`INSERT INTO drug_interactions(generic_a,generic_b,severity,message) VALUES
    ('Warfarin','Aspirin','high','Bleeding risk — check with pharmacist before dispensing together'),
    ('Ibuprofen','Aspirin','medium','Combined NSAIDs increase stomach-bleed risk'),
    ('Metformin','Ciprofloxacin','medium','Monitor blood sugar when combined')`).run();
  db.prepare(`INSERT INTO settings(key,value) VALUES('store_name','PharmaCore Medical Store'),('currency','PKR'),('tax_pct','0'),('receipt_size','80mm'),('language','en'),('theme','light')`).run();
}
