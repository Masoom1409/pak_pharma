import React, { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { fmtPKR } from '../lib/money';
import { formatQty } from '../lib/units';
import { expiryBadge } from '../lib/fefo';
import { Card, Btn, Input, Badge, Modal } from '../components/ui';
import { useApp } from '../lib/store';
export default function Inventory() {
  const { user } = useApp();
  const [meds, setMeds] = useState<any[]>([]); const [q, setQ] = useState(''); const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: '', generic: '', company: '', form: 'Tablet', strength: '', barcode: '', sale_price: '', purchase_price: '', reorder_level: 20, rack: '' });
  const load = () => api('medicines:list').then(setMeds).catch(() => {});
  useEffect(() => { load(); }, []);
  const filtered = meds.filter((m) => !q || (m.name + m.generic + m.company).toLowerCase().includes(q.toLowerCase()));
  const submit = async (e: any) => { e.preventDefault(); await api('medicines:create', { ...form, sale_price_paisa: Math.round(Number(form.sale_price) * 100), purchase_price_paisa: Math.round(Number(form.purchase_price) * 100), reorder_level: Number(form.reorder_level) }); setShowAdd(false); load(); };
  return (<div className="space-y-4">
    <div className="flex gap-2"><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search inventory…" className="max-w-md" /><Btn onClick={() => setShowAdd(true)}>+ Add Medicine</Btn><Btn variant="ghost" onClick={() => { const rows = [['name','generic','company','form','strength','barcode','purchase_price','sale_price','reorder_level','rack'], ...meds.map((m: any) => [m.name, m.generic, m.company, m.form, m.strength, '', m.purchase_price_paisa / 100, m.sale_price_paisa / 100, m.reorder_level, m.rack])]; const csv = rows.map((r) => r.join(',')).join('\n'); const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'medicines-export.csv'; a.click(); }}>Export CSV</Btn></div>
    <Card><table className="w-full text-sm"><thead><tr className="text-left text-slate-500"><th className="py-2">Medicine</th><th>Generic</th><th>Stock</th><th>Price</th><th>Expiry</th><th>Rack</th></tr></thead><tbody>
      {filtered.map((m) => <tr key={m.id} className="border-t"><td className="py-2 font-semibold">{m.name} <span className="text-slate-500 font-normal">{m.strength} {m.form}</span></td><td>{m.generic}</td><td>{formatQty(m.stock || 0, 10, 10)} {m.stock <= m.reorder_level && <Badge tone="yellow">Low</Badge>}</td><td>{fmtPKR(m.sale_price_paisa)}</td><td>{m.nearest_expiry ? <Badge tone={expiryBadge(m.nearest_expiry) === 'red' ? 'red' : expiryBadge(m.nearest_expiry) === 'orange' ? 'orange' : 'green'}>{m.nearest_expiry}</Badge> : '—'}</td><td>{m.rack}</td></tr>)}
    </tbody></table>{filtered.length === 0 && <p className="text-slate-500 text-sm py-4">No medicines found.</p>}</Card>
    <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add Medicine"><form onSubmit={submit} className="space-y-3">
      <Input required placeholder="Brand name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      <Input placeholder="Generic / salt" value={form.generic} onChange={(e) => setForm({ ...form, generic: e.target.value })} />
      <Input placeholder="Company" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
      <div className="grid grid-cols-2 gap-2"><Input placeholder="Form (Tablet/Syrup…)" value={form.form} onChange={(e) => setForm({ ...form, form: e.target.value })} /><Input placeholder="Strength" value={form.strength} onChange={(e) => setForm({ ...form, strength: e.target.value })} /></div>
      <Input placeholder="Barcode (optional)" value={form.barcode} onChange={(e) => setForm({ ...form, barcode: e.target.value })} />
      <div className="grid grid-cols-2 gap-2"><Input type="number" placeholder="Purchase price Rs" value={form.purchase_price} onChange={(e) => setForm({ ...form, purchase_price: e.target.value })} /><Input type="number" placeholder="Sale price Rs" value={form.sale_price} onChange={(e) => setForm({ ...form, sale_price: e.target.value })} /></div>
      <Btn className="w-full">Save medicine</Btn></form></Modal>
  </div>);
}
