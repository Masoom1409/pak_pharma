import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { Card, Btn, Input, Label } from '../components/ui';
export default function Settings() {
  const [s, setS] = useState<any>({}); const [dbPath, setDbPath] = useState(''); const [msg, setMsg] = useState('');
  useEffect(() => { api('settings:get').then(setS).catch(() => {}); api('app:dbPath').then(setDbPath).catch(() => {}); }, []);
  const save = async () => { await api('settings:set', s); setMsg('Settings saved ✓'); };
  const backup = async () => { const r = await api('backup:create'); setMsg(`Backup created: ${r.path}`); };
  return (<div className="space-y-4 max-w-2xl">
    <Card><h3 className="font-bold mb-3">Store profile</h3><div className="space-y-3"><div><Label>Store name</Label><Input value={s.store_name || ''} onChange={(e) => setS({ ...s, store_name: e.target.value })} /></div><div><Label>Currency</Label><Input value={s.currency || 'PKR'} onChange={(e) => setS({ ...s, currency: e.target.value })} /></div><div><Label>Tax % (0 = off)</Label><Input type="number" value={s.tax_pct || 0} onChange={(e) => setS({ ...s, tax_pct: e.target.value })} /></div><div><Label>Receipt size</Label><select value={s.receipt_size || '80mm'} onChange={(e) => setS({ ...s, receipt_size: e.target.value })} className="w-full px-3 py-2.5 rounded-xl border bg-white dark:bg-slate-900"><option>58mm</option><option>80mm</option><option>A4</option></select></div><Btn onClick={save}>Save settings</Btn></div></Card>
    <Card><h3 className="font-bold mb-2">Database</h3><p className="text-sm break-all bg-slate-100 dark:bg-slate-800 p-3 rounded-xl">{dbPath}</p><p className="text-sm text-slate-500 mt-2">In Electron this is %APPDATA%/PharmaCore/pharmacy.db (userData). WAL mode + foreign keys are on. Changing the folder is done via the folder picker in the Electron build (app:pickDbFolder); the app restarts against the new path.</p><Btn variant="ghost" onClick={backup} className="mt-3">Create backup now</Btn></Card>
    <Card><h3 className="font-bold mb-2">Users & roles</h3><p className="text-sm text-slate-500">Owner PIN 1234 • Cashier PIN 1111 (demo / first-run seed — change on first login in production). Cashiers cannot delete bills, change cost price, or discount above the manager limit without a manager PIN — enforced in the POS discount check in the full build.</p></Card>
    {msg && <p className="text-sm font-semibold">{msg}</p>}
  </div>);
}
