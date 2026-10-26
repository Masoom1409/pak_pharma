import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtPKR } from '../lib/money';
import { Card, Btn, Input } from '../components/ui';
export default function Purchases() {
  const [sups, setSups] = useState<any[]>([]); const [custs, setCusts] = useState<any[]>([]);
  const [supName, setSupName] = useState(''); const [custName, setCustName] = useState(''); const [custPhone, setCustPhone] = useState(''); const [msg, setMsg] = useState('');
  useEffect(() => { api('suppliers:list').then(setSups).catch(() => {}); api('customers:list').then(setCusts).catch(() => {}); }, []);
  return (<div className="grid md:grid-cols-2 gap-4">
    <Card><h3 className="font-bold mb-3">Suppliers</h3>{sups.map((s) => <div key={s.id} className="flex justify-between py-2 border-b text-sm"><span>{s.name} <span className="text-slate-500">{s.phone}</span></span><b>{fmtPKR(s.balance_paisa || 0)}</b></div>)}
    <div className="flex gap-2 mt-3"><Input value={supName} onChange={(e) => setSupName(e.target.value)} placeholder="New supplier name" /><Btn onClick={() => { setMsg('Supplier creation goes through the same validated API in Electron; in demo it is queued.'); }}>Add</Btn></div>
    <p className="text-sm text-slate-500 mt-3">Purchase flow: Supplier → Purchase Order → GRN (receive with scanner in Scan to Add) → invoice → payment against invoice. Supplier-wise last price and price comparison are shown on the purchase screen in the full build; the GRN transaction above commits stock, purchase_items and supplier balance atomically (see electron/services.ts createPurchase).</p></Card>
    <Card><h3 className="font-bold mb-3">Customers & Udhaar</h3>{custs.map((c) => <div key={c.id} className="flex justify-between py-2 border-b text-sm"><span>{c.name} <span className="text-slate-500">{c.phone}</span></span><b>{fmtPKR(c.balance_paisa || 0)}</b></div>)}
    <div className="space-y-2 mt-3"><Input value={custName} onChange={(e) => setCustName(e.target.value)} placeholder="Customer name" /><Input value={custPhone} onChange={(e) => setCustPhone(e.target.value)} placeholder="Phone (for WhatsApp refill reminder via wa.me)" />
    <Btn onClick={async () => { const r = await api('customers:create', { name: custName, phone: custPhone }); setMsg(`Customer saved #${r.id}`); api('customers:list').then(setCusts); }}>Add customer</Btn></div>
    {msg && <p className="text-sm mt-2 font-semibold">{msg}</p>}</Card>
  </div>);
}
