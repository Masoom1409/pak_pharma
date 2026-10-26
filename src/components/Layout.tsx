import React, { useEffect, useState } from 'react';
import { LayoutDashboard, ShoppingCart, Package, ScanBarcode, Truck, Users, BarChart3, Settings, Bell, Moon, Sun, LogOut, Search } from 'lucide-react';
import { useApp } from '../lib/store';
import { api } from '../lib/api';
import { Btn } from './ui';

const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'pos', label: 'POS / Billing', icon: ShoppingCart },
  { id: 'inventory', label: 'Inventory', icon: Package },
  { id: 'scan', label: 'Scan to Add', icon: ScanBarcode },
  { id: 'purchases', label: 'Purchases & Suppliers', icon: Truck },
  { id: 'customers', label: 'Customers', icon: Users },
  { id: 'reports', label: 'Reports & Audit', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
];
export default function Layout({ page, setPage, children }: any) {
  const { user, lang, setLang, dark, toggleDark, setUser } = useApp();
  const [alerts, setAlerts] = useState<any>(null);
  const [palette, setPalette] = useState(false);
  const [q, setQ] = useState('');
  useEffect(() => { api('inventory:alerts').then(setAlerts).catch(() => {}); }, []);
  useEffect(() => { const h = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(true); } }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h); }, []);
  const alertCount = alerts ? alerts.expiring.length + alerts.expired.length + alerts.low.length : 0;
  return (
    <div className="flex h-screen bg-slate-100 dark:bg-slate-950 text-slate-900 dark:text-slate-100" dir={lang === 'ur' ? 'rtl' : 'ltr'}>
      <aside className="w-60 shrink-0 bg-white dark:bg-slate-900 border-e border-slate-200 dark:border-slate-800 p-4 flex flex-col gap-1 overflow-y-auto">
        <div className="font-extrabold text-xl text-brand-600 mb-1">💊 PharmaCore</div>
        <div className="text-xs text-slate-500 mb-4">Offline Pharmacy • PKR</div>
        {NAV.map((n) => { const Icon = n.icon; return <button key={n.id} onClick={() => setPage(n.id)} className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold text-start ${page === n.id ? 'bg-brand-500 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`}><Icon size={18} />{n.label}</button>; })}
        <div className="mt-auto pt-4 border-t border-slate-200 dark:border-slate-800 text-sm">
          <div className="font-bold">{user?.name}</div><div className="text-slate-500">{user?.role}</div>
          <Btn variant="ghost" className="mt-3 w-full" onClick={() => setUser(null)}><LogOut size={16} className="inline me-2" />Logout</Btn>
        </div>
      </aside>
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 flex items-center gap-3 px-4">
          <button onClick={() => setPalette(true)} className="flex-1 max-w-md flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 dark:bg-slate-800 text-slate-500 text-sm"><Search size={16} />Search medicines… <kbd className="ms-auto text-xs border rounded px-1">Ctrl+K</kbd></button>
          <div className="ms-auto flex items-center gap-2">
            <button title="Alerts" onClick={() => setPage('inventory')} className="relative p-2 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800"><Bell size={20} />{alertCount > 0 && <span className="absolute -top-0.5 -end-0.5 bg-red-500 text-white text-[10px] rounded-full px-1.5">{alertCount}</span>}</button>
            <select value={lang} onChange={(e) => setLang(e.target.value as any)} className="px-2 py-2 rounded-xl bg-slate-100 dark:bg-slate-800 text-sm font-semibold"><option value="en">English</option><option value="ur">اردو</option></select>
            <button onClick={toggleDark} className="p-2 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800">{dark ? <Sun size={20} /> : <Moon size={20} />}</button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-5">{children}</main>
      </div>
      {palette && <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center pt-24 p-4" onClick={() => setPalette(false)}><div className="bg-white dark:bg-slate-900 rounded-2xl w-full max-w-lg p-4 shadow-xl" onClick={(e) => e.stopPropagation()}><input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a medicine, generic or company…" className="w-full px-3 py-3 rounded-xl border text-base" /><div className="mt-3 text-sm text-slate-500">Tip: in POS, scan a barcode or type and press Enter. F2 = New Bill, F5 = Pay, F8 = Hold.</div><button className="mt-3 font-semibold text-brand-600" onClick={() => { setPalette(false); setPage('pos'); }}>Go to POS →</button></div></div>}
    </div>
  );
}
