import { SEED_MEDS } from './seedData';
import { allocateFEFO } from './fefo';

// IPC bridge. In Electron, calls go to the main process (SQLite).
// In a plain browser (vite dev preview), a localStorage-backed demo store is used
// so the UI can be tested without Electron. Production data always lives in SQLite.
type Api = Record<string, (a?: any) => Promise<any>>;
const electronApi = (typeof window !== 'undefined' ? (window as any).pharmacore : undefined) as Api | undefined;

function demoStore() {
  const key = 'pharmacore-demo-v1';
  const saved = localStorage.getItem(key);
  if (saved) return JSON.parse(saved);
  const meds = SEED_MEDS.map(([name, generic, company, form, strength, buy, sell], i) => ({
    id: i + 1, name, generic, company, form, strength, tablets_per_strip: 10, strips_per_box: 10,
    purchase_price_paisa: buy * 100, sale_price_paisa: sell * 100, mrp_paisa: sell * 100, reorder_level: 20, rack: `A-${(i % 8) + 1}`, controlled: /Xanax|Lexotanil|Tramadol|Codeine/.test(name) ? 1 : 0,
    stock: 700, nearest_expiry: '2026-12-15', barcode: `890${String(1000000 + i).slice(1)}${i % 10}`,
    batches: [{ id: i * 2 + 1, batch_no: `B${200 + i}`, expiry: '2026-12-15', qty_base: 200 }, { id: i * 2 + 2, batch_no: `B${100 + i}`, expiry: '2027-06-30', qty_base: 500 }],
  }));
  const s = { meds, sales: [] as any[], customers: [{ id: 1, name: 'Walk-in Customer', phone: '' }, { id: 2, name: 'Ahmed Raza', phone: '0300-9998888' }], suppliers: [{ id: 1, name: 'Karachi Pharma Distributors', phone: '0300-1234567' }] };
  localStorage.setItem(key, JSON.stringify(s)); return s;
}
function saveDemo(s: any) { localStorage.setItem('pharmacore-demo-v1', JSON.stringify(s)); }

const demo: Api = {
  'medicines:search': async (a: any) => { const s = demoStore(); const q = (a?.q || '').toLowerCase(); return s.meds.filter((m: any) => !q || m.name.toLowerCase().includes(q) || m.generic.toLowerCase().includes(q) || m.company.toLowerCase().includes(q) || m.barcode === a.q).slice(0, 30); },
  'medicines:list': async () => demoStore().meds,
  'medicines:stock': async (a: any) => demoStore().meds.find((m: any) => m.id === a.id)?.batches || [],
  'medicines:create': async (a: any) => { const s = demoStore(); const id = s.meds.length + 1; s.meds.push({ id, ...a, stock: 0, batches: [] }); saveDemo(s); return { id }; },
  'dashboard': async () => { const s = demoStore(); return { salesToday: 0, profit: 0, bills: s.sales.length, stockValue: s.meds.reduce((x: number, m: any) => x + m.stock * m.purchase_price_paisa, 0), customerDues: 0, supplierDues: 0, lowCount: 0, expiringCount: s.meds.length, expiredCount: 0, trend: [], top: [], alerts: { expiring: [], expired: [], low: [] } }; },
  'inventory:alerts': async () => ({ expiring: demoStore().meds.slice(0, 5).map((m: any) => ({ name: m.name, batch_no: 'B-DEC', expiry: '2026-12-15' })), expired: [], low: [] }),
  'customers:list': async () => demoStore().customers,
  'suppliers:list': async () => demoStore().suppliers,
  'scan:lookup': async (a: any) => { const m = demoStore().meds.find((x: any) => x.barcode === a.barcode); return m ? { found: true, medicine: m, batches: m.batches } : { found: false, barcode: a.barcode }; },
  'pos:sale': async (a: any) => { const s = demoStore(); for (const it of a.items) { const m = s.meds.find((x: any) => x.id === it.medicineId); if (!m) throw new Error('Medicine not found'); allocateFEFO(m.batches, it.qtyBase); const alloc = allocateFEFO(m.batches, it.qtyBase); for (const al of alloc) { const b = m.batches.find((x: any) => x.id === al.batch_id); if (b) b.qty_base -= al.qty; } m.stock = m.batches.reduce((x: number, b: any) => x + b.qty_base, 0); } const total = a.items.reduce((x: number, it: any) => x + it.qtyBase * it.pricePaisa, 0); const billNo = 'B' + String(Date.now()).slice(-8); s.sales.push({ bill_no: billNo, total_paisa: total, created_at: new Date().toISOString() }); saveDemo(s); return { billNo, total }; },
  'auth:login': async (a: any) => { if (a.pin === '1234') return { id: 1, name: 'Owner', role: 'Owner' }; if (a.pin === '1111') return { id: 2, name: 'Cashier', role: 'Cashier' }; throw new Error('Invalid PIN'); },
};
const FALLBACKS: Api = { ...demo, 'settings:get': async () => ({ store_name: 'PharmaCore Medical Store', currency: 'PKR' }), 'settings:set': async () => ({ ok: true }), 'app:dbPath': async () => 'Browser demo — localStorage (Electron uses %APPDATA%/PharmaCore/pharmacy.db)', 'reports:sales': async () => demoStore().sales, 'audit:list': async () => [], 'backup:create': async () => ({ path: 'demo-backup' }), 'pos:heldList': async () => [], 'pos:held': async () => ({ id: 1 }), 'pos:return': async () => ({ ok: true }), 'inventory:adjust': async () => ({ ok: true }), 'scan:stockIn': async () => ({ ok: true }), 'customers:create': async () => ({ id: 99 }), 'purchases:create': async () => ({ id: 1 }) };

export async function api<T = any>(channel: string, arg?: any): Promise<T> {
  if (electronApi?.[channel]) { const r = await electronApi[channel](arg); if (!r.ok) throw new Error(r.error || 'Request failed'); return r.data as T; }
  const fn = FALLBACKS[channel]; if (!fn) throw new Error(`No demo handler for ${channel} — run in Electron`);
  return fn(arg) as T;
}
