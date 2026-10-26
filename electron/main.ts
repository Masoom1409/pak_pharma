import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import * as path from 'path';
import * as fs from 'fs';
import { openDb } from './db';
import { createServices } from './services';

let win: BrowserWindow | null = null;
let dbPath = path.join(app.getPath('userData'), 'pharmacy.db');
let svc: ReturnType<typeof createServices>;

function createWindow() {
  win = new BrowserWindow({
    width: 1366, height: 768, minWidth: 1024, minHeight: 600,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
    autoHideMenuBar: true,
  });
  if (process.env.VITE_DEV_SERVER_URL) win.loadURL(process.env.VITE_DEV_SERVER_URL);
  else win.loadFile(path.join(__dirname, '../dist/index.html'));
}
app.whenReady().then(() => {
  try { svc = createServices(openDb(dbPath)); } catch (e) { dialog.showErrorBox('Database error', String(e)); app.quit(); return; }
  // Generic, validated IPC surface — no raw SQL from the renderer.
  const handlers: Record<string, (a: any) => any> = {
    'auth:login': (a) => svc.login(a.pin),
    'medicines:search': (a) => svc.searchMedicines(a.q, a.limit),
    'medicines:list': (a) => svc.listMedicines(a),
    'medicines:create': (a) => svc.createMedicine(a),
    'medicines:stock': (a) => svc.medicineStock(a.id),
    'inventory:alerts': () => svc.alerts(),
    'inventory:adjust': (a) => svc.adjustStock(a),
    'scan:lookup': (a) => svc.scanLookup(a.barcode, a.userId),
    'scan:stockIn': (a) => svc.stockIn(a),
    'pos:sale': (a) => svc.createSale(a),
    'pos:return': (a) => svc.createReturn(a),
    'pos:held': (a) => svc.holdBill(a.data),
    'pos:heldList': () => svc.heldList(),
    'dashboard': () => svc.dashboard(),
    'customers:list': () => svc.listCustomers(),
    'customers:create': (a) => svc.createCustomer(a),
    'suppliers:list': () => svc.listSuppliers(),
    'purchases:create': (a) => svc.createPurchase(a),
    'reports:sales': (a) => svc.salesReport(a.from, a.to),
    'audit:list': () => svc.auditList(),
    'backup:create': () => svc.backup(),
    'settings:get': () => svc.getSettings(),
    'settings:set': (a) => svc.setSettings(a),
    'app:dbPath': () => dbPath,
    'app:pickDbFolder': async () => { const r = await dialog.showOpenDialog({ properties: ['openDirectory'] }); return r.filePaths[0] || null; },
  };
  for (const [ch, fn] of Object.entries(handlers)) ipcMain.handle(ch, async (_e, arg) => { try { return { ok: true, data: await fn(arg) }; } catch (err: any) { return { ok: false, error: err.message || String(err) }; } });
  ipcMain.handle('app:print', async (_e, arg) => { try { svc.printReceipt(arg); return { ok: true }; } catch (e: any) { return { ok: false, error: e.message }; } });
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { try { if (svc) svc.backup(); } catch {} });
export { dbPath };
