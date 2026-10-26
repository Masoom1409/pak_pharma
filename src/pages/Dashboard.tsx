import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtPKR } from '../lib/money';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { Card, Stat } from '../components/ui';
export default function Dashboard() {
  const [d, setD] = useState<any>(null);
  useEffect(() => { api('dashboard').then(setD).catch(() => setD({ salesToday: 0, profit: 0, bills: 0, stockValue: 0, customerDues: 0, supplierDues: 0, lowCount: 0, expiringCount: 0, expiredCount: 0, trend: [], top: [], alerts: { expiring: [], expired: [], low: [] } })); }, []);
  if (!d) return <div>Loading…</div>;
  return (<div className="space-y-4">
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Stat label="Today's sales" value={fmtPKR(d.salesToday)} /><Stat label="Today's profit" value={fmtPKR(d.profit)} /><Stat label="Bills today" value={d.bills} /><Stat label="Stock value" value={fmtPKR(d.stockValue)} />
      <Stat label="Low stock" value={d.lowCount} /><Stat label="Expiring soon" value={d.expiringCount} /><Stat label="Expired batches" value={d.expiredCount} /><Stat label="Customer dues" value={fmtPKR(d.customerDues)} />
    </div>
    <div className="grid md:grid-cols-2 gap-4">
      <Card><h3 className="font-bold mb-2">Sales trend (7 days)</h3><div className="h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={d.trend.map((t: any) => ({ d: t.d, total: t.total / 100 }))}><XAxis dataKey="d" /><YAxis /><Tooltip /><Bar dataKey="total" fill="#0f9d8a" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>{d.trend.length === 0 && <p className="text-sm text-slate-500">No sales yet today — make your first bill in POS.</p>}</Card>
      <Card><h3 className="font-bold mb-2">Top selling medicines</h3>{d.top.map((t: any) => <div key={t.name} className="flex justify-between py-1 border-b last:border-0 text-sm"><span>{t.name}</span><span>{t.qty} units • {fmtPKR(t.amt)}</span></div>)}{d.top.length === 0 && <p className="text-sm text-slate-500">Top sellers appear after sales.</p>}</Card>
    </div>
    <Card><h3 className="font-bold mb-2">Alerts</h3>
      {d.alerts.expiring.map((a: any, i: number) => <div key={i} className="text-sm py-1">⏰ {a.name} — batch {a.batch_no} expires {a.expiry}</div>)}
      {d.alerts.expired.map((a: any, i: number) => <div key={i} className="text-sm py-1 text-red-600">⛔ {a.name} — batch {a.batch_no} EXPIRED {a.expiry} (blocked from sale)</div>)}
      {d.alerts.low.map((a: any, i: number) => <div key={i} className="text-sm py-1">📦 {a.name} — low stock ({a.stock} ≤ reorder {a.reorder_level})</div>)}
      {d.alerts.expiring.length + d.alerts.expired.length + d.alerts.low.length === 0 && <p className="text-sm text-slate-500">No alerts.</p>}
    </Card>
  </div>);
}
