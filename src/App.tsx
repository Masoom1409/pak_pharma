import React, { useState } from 'react';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import POS from './pages/POS';
import Inventory from './pages/Inventory';
import ScanToAdd from './pages/ScanToAdd';
import Purchases from './pages/Purchases';
import Reports from './pages/Reports';
import Settings from './pages/Settings';
import { useApp } from './lib/store';
import { api } from './lib/api';
import { Card, Btn, Input } from './components/ui';

function Login() {
  const setUser = useApp((s) => s.setUser); const [pin, setPin] = useState(''); const [err, setErr] = useState('');
  const go = async (e: any) => { e.preventDefault(); try { const u = await api('auth:login', { pin }); setUser(u); } catch (e: any) { setErr(e.message); } };
  return (<div className="min-h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-950 p-4"><Card className="w-full max-w-sm text-center"><div className="text-4xl mb-2">💊</div><h1 className="font-extrabold text-2xl text-brand-600">PharmaCore</h1><p className="text-slate-500 text-sm mb-4">Offline Medical Store • Pakistan</p><form onSubmit={go} className="space-y-3"><Input type="password" inputMode="numeric" autoFocus placeholder="Enter PIN" value={pin} onChange={(e) => setPin(e.target.value)} className="text-center text-xl tracking-widest" /><Btn className="w-full">Login</Btn></form>{err && <p className="text-red-500 text-sm mt-2">{err}</p>}<p className="text-xs text-slate-400 mt-3">Demo: Owner 1234 • Cashier 1111 (change after first login)</p></Card></div>);
}
export default function App() {
  const user = useApp((s) => s.user); const [page, setPage] = useState('dashboard');
  if (!user) return <Login />;
  return (<Layout page={page} setPage={setPage}>
    {page === 'dashboard' && <Dashboard />}{page === 'pos' && <POS />}{page === 'inventory' && <Inventory />}{page === 'scan' && <ScanToAdd />}{page === 'purchases' && <Purchases />}{page === 'customers' && <Purchases />}{page === 'reports' && <Reports />}{page === 'settings' && <Settings />}
  </Layout>);
}
