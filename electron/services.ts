import type Database from 'better-sqlite3';
import * as bcrypt from 'bcryptjs';
import * as fs from 'fs';
import * as path from 'path';
import { allocateFEFO, isExpired, todayISO } from '../src/lib/fefo';

type Row = Record<string, any>;
const today = () => new Date().toISOString().slice(0, 10);

export function createServices(db: Database.Database) {
  const q = (sql: string, ...p: any[]) => db.prepare(sql).all(...p) as Row[];
  const one = (sql: string, ...p: any[]) => db.prepare(sql).get(...p) as Row | undefined;
  const run = (sql: string, ...p: any[]) => db.prepare(sql).run(...p);
  const audit = (userId: number | null, action: string, entity: string, id: number, oldV: any, newV: any) =>
    run('INSERT INTO audit_log(user_id,action,entity,entity_id,old_value,new_value) VALUES(?,?,?,?,?,?)', userId, action, entity, id, JSON.stringify(oldV), JSON.stringify(newV));

  return {
    login(pin: string) {
      const users = q('SELECT * FROM users WHERE active=1');
      const u = users.find((x) => bcrypt.compareSync(pin, x.pin_hash));
      if (!u) throw new Error('Invalid PIN');
      const { pin_hash, ...safe } = u; return safe;
    },
    searchMedicines(query: string, limit = 30) {
      const s = (query || '').trim();
      if (!s) return q(`SELECT m.*, COALESCE((SELECT SUM(qty_base) FROM batches WHERE medicine_id=m.id),0) AS stock FROM medicines m WHERE active=1 ORDER BY name LIMIT ?`, limit);
      const byBarcode = one(`SELECT m.*, COALESCE((SELECT SUM(qty_base) FROM batches WHERE medicine_id=m.id),0) AS stock FROM medicines m JOIN medicine_barcodes b ON b.medicine_id=m.id WHERE b.barcode=?`, s);
      if (byBarcode) return [byBarcode];
      try {
        const fts = s.split(/\s+/).map((w) => `"${w.replace(/"/g, '')}"*`).join(' ');
        return q(`SELECT m.*, COALESCE((SELECT SUM(qty_base) FROM batches WHERE medicine_id=m.id),0) AS stock FROM medicines_fts f JOIN medicines m ON m.id=f.rowid WHERE medicines_fts MATCH ? AND m.active=1 LIMIT ?`, fts, limit);
      } catch { return q(`SELECT m.*, COALESCE((SELECT SUM(qty_base) FROM batches WHERE medicine_id=m.id),0) AS stock FROM medicines m WHERE active=1 AND (name LIKE ? OR generic LIKE ? OR company LIKE ?) LIMIT ?`, `%${s}%`, `%${s}%`, `%${s}%`, limit); }
    },
    listMedicines(f: any = {}) {
      return q(`SELECT m.*, COALESCE((SELECT SUM(qty_base) FROM batches WHERE medicine_id=m.id),0) AS stock,
        (SELECT MIN(expiry) FROM batches WHERE medicine_id=m.id AND qty_base>0) AS nearest_expiry,
        (SELECT batch_no FROM batches WHERE medicine_id=m.id AND qty_base>0 ORDER BY expiry LIMIT 1) AS nearest_batch
        FROM medicines m WHERE active=1 ORDER BY name LIMIT 500`);
    },
    medicineStock(id: number) { return q('SELECT * FROM batches WHERE medicine_id=? ORDER BY expiry', id); },
    createMedicine(m: any) {
      const r = run(`INSERT INTO medicines(name,generic,company,category,form,strength,tablets_per_strip,strips_per_box,purchase_price_paisa,sale_price_paisa,mrp_paisa,reorder_level,rack,controlled) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
        m.name, m.generic || '', m.company || '', m.category || '', m.form || 'Tablet', m.strength || '', m.tablets_per_strip || 10, m.strips_per_box || 10, m.purchase_price_paisa || 0, m.sale_price_paisa || 0, m.mrp_paisa || 0, m.reorder_level || 10, m.rack || '', m.controlled ? 1 : 0);
      const id = Number(r.lastInsertRowid);
      if (m.barcode) run('INSERT INTO medicine_barcodes(medicine_id,barcode,is_primary) VALUES(?,?,1)', id, m.barcode);
      return { id };
    },
    alerts() {
      const t = today();
      const expiring = q(`SELECT m.name, b.batch_no, b.expiry FROM batches b JOIN medicines m ON m.id=b.medicine_id WHERE b.qty_base>0 AND b.expiry BETWEEN ? AND date(?,'+90 days') ORDER BY b.expiry LIMIT 50`, t, t);
      const expired = q(`SELECT m.name, b.batch_no, b.expiry FROM batches b JOIN medicines m ON m.id=b.medicine_id WHERE b.qty_base>0 AND b.expiry < ? ORDER BY b.expiry LIMIT 50`, t);
      const low = q(`SELECT m.name, m.reorder_level, COALESCE((SELECT SUM(qty_base) FROM batches WHERE medicine_id=m.id),0) AS stock FROM medicines m WHERE m.active=1 AND stock <= m.reorder_level LIMIT 50`);
      return { expiring, expired, low };
    },
    adjustStock(a: any) {
      return db.transaction(() => {
        const b = one('SELECT * FROM batches WHERE id=?', a.batchId); if (!b) throw new Error('Batch not found');
        run('UPDATE batches SET qty_base=qty_base+? WHERE id=?', a.delta, a.batchId);
        run('INSERT INTO stock_movements(medicine_id,batch_id,type,qty_base,note,user_id) VALUES(?,?,?,?,?,?)', b.medicine_id, a.batchId, 'ADJUSTMENT', a.delta, a.reason || '', a.userId || null);
        audit(a.userId || null, 'ADJUST', 'batch', a.batchId, b.qty_base, b.qty_base + a.delta);
        return { ok: true };
      })();
    },
    scanLookup(barcode: string, userId?: number) {
      const med = one(`SELECT m.* FROM medicines m JOIN medicine_barcodes b ON b.medicine_id=m.id WHERE b.barcode=?`, barcode);
      run('INSERT INTO scan_log(barcode,medicine_id,user_id,result) VALUES(?,?,?,?)', barcode, med?.id || null, userId || null, med ? 'FOUND' : 'UNKNOWN');
      if (!med) return { found: false, barcode };
      return { found: true, medicine: med, batches: this.medicineStock(med.id) };
    },
    stockIn(a: any) {
      return db.transaction(() => {
        for (const line of a.lines) {
          let medId = line.medicineId;
          if (!medId && line.newMedicine) { medId = Number(this.createMedicine(line.newMedicine).id); }
          if (!medId) throw new Error('Medicine missing in stock-in line');
          let batch = one('SELECT * FROM batches WHERE medicine_id=? AND batch_no=?', medId, line.batchNo);
          if (batch) run('UPDATE batches SET qty_base=qty_base+?, expiry=? WHERE id=?', line.qtyBase, line.expiry, batch.id);
          else { const r = run('INSERT INTO batches(medicine_id,batch_no,expiry,qty_base,cost_paisa) VALUES(?,?,?,?,?)', medId, line.batchNo, line.expiry, line.qtyBase, line.costPaisa || 0); batch = { id: Number(r.lastInsertRowid) }; }
          run('INSERT INTO stock_movements(medicine_id,batch_id,type,qty_base,ref_type,note,user_id) VALUES(?,?,?,?,?,?,?)', medId, batch.id, 'PURCHASE', line.qtyBase, 'STOCKIN', a.supplierId ? `supplier:${a.supplierId}` : '', a.userId || null);
          if (line.salePaisa) run('UPDATE medicines SET sale_price_paisa=?, mrp_paisa=? WHERE id=?', line.salePaisa, line.salePaisa, medId);
        }
        return { ok: true, lines: a.lines.length };
      })();
    },
    createSale(a: any) {
      return db.transaction(() => {
        const t = today();
        const items: any[] = [];
        let subtotal = 0;
        for (const it of a.items) {
          const med = one('SELECT * FROM medicines WHERE id=?', it.medicineId); if (!med) throw new Error('Medicine not found');
          const batches = q('SELECT * FROM batches WHERE medicine_id=?', it.medicineId);
          const alloc = it.batchId ? [{ batch_id: it.batchId, batch_no: '', qty: it.qtyBase }] : allocateFEFO(batches as any, it.qtyBase, t);
          for (const al of alloc) {
            const b = one('SELECT * FROM batches WHERE id=?', al.batch_id); if (!b || b.qty_base < al.qty) throw new Error(`Stock short for ${med.name}`);
            if (isExpired(b.expiry, t)) throw new Error(`Expired batch blocked: ${med.name} ${b.batch_no}`);
            run('UPDATE batches SET qty_base=qty_base-? WHERE id=?', al.qty, al.batch_id);
            run('INSERT INTO stock_movements(medicine_id,batch_id,type,qty_base,ref_type,user_id) VALUES(?,?,?,?,?,?)', med.id, al.batch_id, 'SALE', -al.qty, 'SALE', a.userId || null);
          }
          const amount = Math.max(0, it.qtyBase * it.pricePaisa - (it.discountPaisa || 0));
          subtotal += amount; items.push({ ...it, alloc, amount });
        }
        const discount = Math.round((subtotal * (a.billDiscountPct || 0)) / 100) + (a.billDiscountAmt || 0);
        const afterDisc = Math.max(0, subtotal - discount);
        const tax = Math.round((afterDisc * (a.taxPct || 0)) / 100);
        const total = Math.round((afterDisc + tax) / 100) * 100;
        const billNo = 'B' + String(Date.now()).slice(-8);
        const sale = run(`INSERT INTO sales(bill_no,customer_id,user_id,subtotal_paisa,discount_paisa,tax_paisa,total_paisa,paid_paisa,payment_method,status,doctor_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)`,
          billNo, a.customerId || 1, a.userId || null, subtotal, discount, tax, total, a.paidPaisa || total, a.paymentMethod || 'Cash', a.paymentMethod === 'Credit' ? 'CREDIT' : 'COMPLETED', a.doctorName || '');
        const saleId = Number(sale.lastInsertRowid);
        for (const it of items) for (const al of it.alloc) run('INSERT INTO sale_items(sale_id,medicine_id,batch_id,qty_base,unit,unit_qty,price_paisa,discount_paisa,amount_paisa) VALUES(?,?,?,?,?,?,?,?,?)', saleId, it.medicineId, al.batch_id, al.qty, it.unit, it.unitQty, it.pricePaisa, it.discountPaisa || 0, it.amount);
        for (const p of (a.payments || [{ method: a.paymentMethod || 'Cash', amount: a.paidPaisa || total }])) run('INSERT INTO sale_payments(sale_id,method,amount_paisa) VALUES(?,?,?)', saleId, p.method, p.amount);
        if (a.paymentMethod === 'Credit' && a.customerId) run('UPDATE customers SET balance_paisa=balance_paisa+? WHERE id=?', total - (a.paidPaisa || 0), a.customerId);
        for (const it of items) { const med = one('SELECT * FROM medicines WHERE id=?', it.medicineId); if (med && med.controlled) run('INSERT INTO controlled_drug_register(sale_id,medicine_id,qty_base,patient_name,prescriber) VALUES(?,?,?,?,?)', saleId, it.medicineId, it.qtyBase, a.patientName || '', a.doctorName || ''); }
        audit(a.userId || null, 'CREATE', 'sale', saleId, null, { billNo, total });
        return { billNo, saleId, total, subtotal, discount, tax };
      })();
    },
    createReturn(a: any) {
      return db.transaction(() => {
        for (const it of a.items) {
          run('UPDATE batches SET qty_base=qty_base+? WHERE id=?', it.qtyBase, it.batchId);
          run('INSERT INTO stock_movements(medicine_id,batch_id,type,qty_base,ref_type,user_id) VALUES(?,?,?,?,?,?)', it.medicineId, it.batchId, 'RETURN', it.qtyBase, 'SALE_RETURN', a.userId || null);
          run('INSERT INTO sale_returns(sale_id,medicine_id,batch_id,qty_base,reason) VALUES(?,?,?,?,?)', a.saleId, it.medicineId, it.batchId, it.qtyBase, a.reason || '');
        }
        return { ok: true };
      })();
    },
    holdBill(data: any) { const r = run('INSERT INTO held_bills(data) VALUES(?)', JSON.stringify(data)); return { id: Number(r.lastInsertRowid) }; },
    heldList() { return q('SELECT * FROM held_bills ORDER BY id DESC LIMIT 20'); },
    dashboard() {
      const t = today();
      const salesToday = one(`SELECT COALESCE(SUM(total_paisa),0) AS total, COUNT(*) AS bills FROM sales WHERE date(created_at)=? AND status!='VOID'`, t);
      const profit = one(`SELECT COALESCE(SUM(si.amount_paisa - si.qty_base*m.purchase_price_paisa/m.tablets_per_strip),0) AS profit FROM sale_items si JOIN medicines m ON m.id=si.medicine_id JOIN sales s ON s.id=si.sale_id WHERE date(s.created_at)=?`, t);
      const stockVal = one(`SELECT COALESCE(SUM(b.qty_base*m.purchase_price_paisa/m.tablets_per_strip),0) AS v FROM batches b JOIN medicines m ON m.id=b.medicine_id`);
      const custDues = one('SELECT COALESCE(SUM(balance_paisa),0) AS v FROM customers');
      const supDues = one('SELECT COALESCE(SUM(balance_paisa),0) AS v FROM suppliers');
      const trend = q(`SELECT date(created_at) AS d, SUM(total_paisa) AS total FROM sales WHERE date(created_at) >= date(?,'-6 days') GROUP BY d ORDER BY d`, t);
      const top = q(`SELECT m.name, SUM(si.qty_base) AS qty, SUM(si.amount_paisa) AS amt FROM sale_items si JOIN medicines m ON m.id=si.medicine_id GROUP BY m.id ORDER BY qty DESC LIMIT 10`);
      const alerts = this.alerts();
      return { salesToday: salesToday?.total || 0, profit: profit?.profit || 0, bills: salesToday?.bills || 0, stockValue: stockVal?.v || 0, customerDues: custDues?.v || 0, supplierDues: supDues?.v || 0, lowCount: alerts.low.length, expiringCount: alerts.expiring.length, expiredCount: alerts.expired.length, trend, top, alerts };
    },
    listCustomers() { return q('SELECT * FROM customers ORDER BY name'); },
    createCustomer(c: any) { const r = run('INSERT INTO customers(name,phone,address,credit_limit_paisa,allergies,notes) VALUES(?,?,?,?,?,?)', c.name, c.phone || '', c.address || '', c.creditLimitPaisa || 0, c.allergies || '', c.notes || ''); return { id: Number(r.lastInsertRowid) }; },
    listSuppliers() { return q('SELECT * FROM suppliers ORDER BY name'); },
    createPurchase(a: any) {
      return db.transaction(() => {
        const r = run('INSERT INTO purchases(supplier_id,invoice_no,total_paisa,paid_paisa) VALUES(?,?,?,?)', a.supplierId, a.invoiceNo || '', a.totalPaisa, a.paidPaisa || 0);
        const pid = Number(r.lastInsertRowid);
        this.stockIn({ lines: a.lines, supplierId: a.supplierId, userId: a.userId });
        for (const l of a.lines) run('INSERT INTO purchase_items(purchase_id,medicine_id,qty_base,cost_paisa) VALUES(?,?,?,?)', pid, l.medicineId, l.qtyBase, l.costPaisa || 0);
        if (a.supplierId) run('UPDATE suppliers SET balance_paisa=balance_paisa+? WHERE id=?', a.totalPaisa - (a.paidPaisa || 0), a.supplierId);
        return { id: pid };
      })();
    },
    salesReport(from: string, to: string) { return q(`SELECT * FROM sales WHERE date(created_at) BETWEEN ? AND ? ORDER BY created_at DESC LIMIT 500`, from, to); },
    auditList() { return q('SELECT * FROM audit_log ORDER BY id DESC LIMIT 200'); },
    getSettings() { const rows = q('SELECT * FROM settings'); const o: any = {}; rows.forEach((r) => o[r.key] = r.value); return o; },
    setSettings(s: any) { for (const [k, v] of Object.entries(s)) run('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', k, String(v)); return { ok: true }; },
    backup() {
      const dir = path.join(process.cwd(), 'backups'); // Electron main overrides via userData in production path below
      try { const p = (db as any).name || ''; if (p) { fs.mkdirSync(path.dirname(p) + '/backups', { recursive: true }); const dest = path.join(path.dirname(p), 'backups', `pharmacy-${new Date().toISOString().replace(/[:.]/g, '-')}.db`); fs.copyFileSync(p, dest); return { path: dest }; } } catch {}
      return { path: dir };
    },
    printReceipt(arg: any) {
      const lines = [`PHARMACORE`, `Bill: ${arg.billNo}`, `Total: Rs ${(arg.total / 100).toFixed(2)}`, `Thank you — Get well soon!`];
      const txt = lines.join('\n');
      // ESC/POS: real thermal printers accept this text stream via USB/serial in production;
      // here we persist the receipt so it can be sent to a printer driver / PDF step.
      const dir = path.join(process.cwd(), 'receipts'); fs.mkdirSync(dir, { recursive: true });
      const f = path.join(dir, `${arg.billNo}.txt`); fs.writeFileSync(f, '\x1B@' + txt + '\n\x1D\x56\x00');
      return { path: f, text: txt };
    },
  };
}
