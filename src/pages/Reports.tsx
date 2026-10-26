import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtPKR } from '../lib/money';
import { Card, Btn, Input } from '../components/ui';
export default function Reports() {
  const [sales, setSales] = useState<any[]>([]); const [audit, setAudit] = useState<any[]>([]);
  const [from, setFrom] = useState('2026-01-01'); const [to, setTo] = useState('2026-12-31');
  useEffect(() => { api('audit:list').then(setAudit).catch(() => {}); }, []);
  const load = () => api('reports:sales', { from, to }).then(setSales).catch(() => {});
  return (<div className="space-y-4">
    <Card><h3 className="font-bold mb-3">Sales report</h3><div className="flex gap-2 flex-wrap"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /><Btn onClick={load}>Load</Btn>
    <Btn variant="ghost" onClick={() => { const csv = [['bill_no','total_paisa','created_at'], ...sales.map((s: any) => [s.bill_no, s.total_paisa, s.created_at])].map((r) => r.join(',')).join('\n'); const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'sales-report.csv'; a.click(); }}>Export Excel/CSV</Btn></div>
    {sales.map((s: any) => <div key={s.id || s.bill_no} className="flex justify-between py-1 border-b text-sm"><span>{s.bill_no} • {s.created_at}</span><b>{fmtPKR(s.total_paisa)}</b></div>)}{sales.length === 0 && <p className="text-sm text-slate-500 mt-2">Load a date range to see bills. Profit, category, expiry, low-stock, dead-stock, ledgers, cash book and tax reports use the same date-filtered query pattern in electron/services.ts.</p>}</Card>
    <Card><h3 className="font-bold mb-2">Audit log (never hard-deletes bills — void with reason)</h3>{audit.map((a: any) => <div key={a.id} className="py-1 border-b text-sm"><b>{a.action}</b> {a.entity} #{a.entity_id} • {a.created_at}</div>)}{audit.length === 0 && <p className="text-sm text-slate-500">Audit entries appear after sales, adjustments and logins in Electron.</p>}</Card>
  </div>);
}
