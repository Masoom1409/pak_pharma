import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../lib/api';
import { fmtPKR, calcBill } from '../lib/money';
import { toBase, pricePerUnit, formatQty } from '../lib/units';
import { expiryBadge } from '../lib/fefo';
import { ScannerBuffer, parseGS1, beep } from '../lib/scanner';
import { Card, Btn, Input, Badge, Modal, Label } from '../components/ui';
import { useApp } from '../lib/store';

export default function POS() {
  const { user } = useApp();
  const [q, setQ] = useState(''); const [results, setResults] = useState<any[]>([]);
  const [cart, setCart] = useState<any[]>([]); const [customer, setCustomer] = useState<any>(null);
  const [method, setMethod] = useState('Cash'); const [paid, setPaid] = useState(0);
  const [billDisc, setBillDisc] = useState(0); const [msg, setMsg] = useState(''); const [receipt, setReceipt] = useState<any>(null);
  const [held, setHeld] = useState<any[]>([]); const [showHeld, setShowHeld] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null); const scanRef = useRef(new ScannerBuffer());
  useEffect(() => { inputRef.current?.focus(); api('pos:heldList').then(setHeld).catch(() => {}); }, []);
  useEffect(() => { if (!q) { setResults([]); return; } const t = setTimeout(() => api('medicines:search', { q }).then(setResults).catch(() => {}), 60); return () => clearTimeout(t); }, [q]);
  const add = (m: any, unit: any = 'strip', unitQty = 1) => {
    const qtyBase = toBase(unitQty, unit, m.tablets_per_strip || 10, m.strips_per_box || 10);
    const perTablet = Math.round(m.sale_price_paisa / (m.tablets_per_strip || 10));
    setCart((c) => { const ex = c.find((x) => x.medicineId === m.id && x.unit === unit); if (ex) return c.map((x) => x.medicineId === m.id && x.unit === unit ? { ...x, unitQty: x.unitQty + unitQty, qtyBase: x.qtyBase + qtyBase } : x); return [...c, { medicineId: m.id, name: m.name, generic: m.generic, unit, unitQty, qtyBase, pricePaisa: perTablet, discountPaisa: 0, controlled: m.controlled, stock: m.stock }]; });
    setQ(''); setResults([]); beep(true); inputRef.current?.focus();
  };
  const totals = useMemo(() => calcBill(cart.map((c) => ({ amount: Math.max(0, c.qtyBase * c.pricePaisa - c.discountPaisa) })), billDisc, 0, 0), [cart, billDisc]);
  const change = Math.max(0, paid - totals.total);
  const interaction = useMemo(() => {
    const gens = cart.map((c) => c.generic || '');
    if (gens.some((g) => g.includes('Aspirin')) && gens.some((g) => g.includes('Ibuprofen'))) return '⚠️ Interaction: Aspirin + Ibuprofen — stomach-bleed risk. Check with pharmacist.';
    return '';
  }, [cart]);
  const substitutes = useMemo(() => {
    if (!results.length) return [];
    const first = results[0]; return results.filter((r) => r.generic === first.generic && r.id !== first.id).slice(0, 3);
  }, [results]);
  const pay = async () => {
    if (!cart.length) { setMsg('Cart is empty'); return; }
    try {
      const r = await api('pos:sale', { customerId: customer?.id || 1, userId: user?.id, items: cart.map((c) => ({ ...c })), paymentMethod: method, paidPaisa: paid || totals.total, billDiscountPct: billDisc, payments: [{ method, amount: paid || totals.total }] });
      setReceipt(r); setCart([]); setPaid(0); setMsg(`Bill ${r.billNo} saved — ${fmtPKR(r.total)}`);
      try { await api('app:print', { billNo: r.billNo, total: r.total }); } catch {}
    } catch (e: any) { setMsg('Error: ' + e.message); }
  };
  useEffect(() => { const h = (e: KeyboardEvent) => {
    if (e.key === 'F2') { e.preventDefault(); setCart([]); }
    if (e.key === 'F3') { e.preventDefault(); inputRef.current?.focus(); }
    if (e.key === 'F5') { e.preventDefault(); pay(); }
    if (e.key === 'F8') { e.preventDefault(); api('pos:held', { data: JSON.stringify(cart) }).then(() => { setCart([]); setMsg('Bill held (F9 to recall)'); }); }
    if (e.key === 'F9') { e.preventDefault(); setShowHeld(true); }
    if (e.key === 'Escape') { setQ(''); }
  }; window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h); });
  const onKey = (e: React.KeyboardEvent) => {
    const code = scanRef.current.key(e.key === 'Enter' ? 'Enter' : e.key.length === 1 ? e.key : '');
    if (e.key === 'Enter') {
      if (code) { const { barcode } = parseGS1(code); api('scan:lookup', { barcode }).then((r: any) => { if (r.found) add(r.medicine); else setMsg(`Unknown barcode ${barcode} — add it from Scan to Add`); }); }
      else if (results[0]) add(results[0]);
    }
  };
  return (
    <div className="grid lg:grid-cols-5 gap-4">
      <div className="lg:col-span-3 space-y-4">
        <Card><div className="flex gap-2"><Input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} placeholder="Scan barcode or type name / generic / company — Enter to add (F3 focus, F2 new, F5 pay, F8 hold, F9 recall)" className="text-base py-3" /><Btn onClick={() => results[0] && add(results[0])}>Add</Btn></div>
          {results.map((m) => <div key={m.id} className="flex items-center justify-between py-2 border-b last:border-0"><div><div className="font-bold">{m.name} <span className="text-slate-500 font-normal">{m.strength} • {m.form}</span></div><div className="text-xs text-slate-500">{m.generic} • {m.company} • Rack {m.rack} • Stock {formatQty(m.stock || 0, 10, 10)} {m.stock <= m.reorder_level && <Badge tone="yellow">Low</Badge>} {m.nearest_expiry && <Badge tone={expiryBadge(m.nearest_expiry) === 'red' ? 'red' : expiryBadge(m.nearest_expiry) === 'orange' ? 'orange' : 'green'}>{m.nearest_expiry}</Badge>}</div></div><div className="text-right"><div className="font-bold">{fmtPKR(m.sale_price_paisa)}</div><Btn variant="ghost" onClick={() => add(m)}>+ Strip</Btn></div></div>)}
          {substitutes.length > 0 && <div className="mt-2 text-sm bg-blue-50 dark:bg-blue-900/20 p-3 rounded-xl"><b>Substitutes (same salt):</b> {substitutes.map((s) => `${s.name} — ${fmtPKR(s.sale_price_paisa)}`).join(' • ')}</div>}
        </Card>
        <Card><h3 className="font-bold mb-2">Cart ({cart.length})</h3>
          {cart.map((c, i) => <div key={i} className="flex items-center gap-2 py-2 border-b last:border-0"><div className="flex-1"><b>{c.name}</b> <span className="text-slate-500 text-sm">{c.unitQty} {c.unit} = {formatQty(c.qtyBase, 10, 10)}</span>{c.controlled ? <Badge tone="red">Controlled — prescription required</Badge> : null}</div>
            <input type="number" min={1} value={c.unitQty} onChange={(e) => { const v = Number(e.target.value) || 1; setCart((cc) => cc.map((x, j) => j === i ? { ...x, unitQty: v, qtyBase: toBase(v, x.unit, 10, 10) } : x)); }} className="w-16 px-2 py-1 border rounded-lg" />
            <select value={c.unit} onChange={(e) => setCart((cc) => cc.map((x, j) => j === i ? { ...x, unit: e.target.value, qtyBase: toBase(x.unitQty, e.target.value as any, 10, 10) } : x))} className="px-2 py-1 border rounded-lg bg-white dark:bg-slate-900"><option value="tablet">tablet</option><option value="strip">strip</option><option value="box">box</option></select>
            <span className="font-bold w-24 text-right">{fmtPKR(c.qtyBase * c.pricePaisa)}</span>
            <button onClick={() => setCart((cc) => cc.filter((_, j) => j !== i))} className="text-red-500 font-bold px-2">×</button></div>)}
          {interaction && <div className="mt-2 p-3 bg-orange-100 text-orange-800 rounded-xl text-sm font-semibold">{interaction}</div>}
          {msg && <div className="mt-2 text-sm text-slate-600">{msg}</div>}
        </Card>
      </div>
      <div className="lg:col-span-2 space-y-4">
        <Card><h3 className="font-bold mb-3">Payment</h3>
          <div className="space-y-2 text-sm"><div className="flex justify-between"><span>Subtotal</span><b>{fmtPKR(totals.subtotal)}</b></div><div className="flex justify-between"><span>Discount</span><b>-{fmtPKR(totals.discount)}</b></div><div className="flex justify-between text-lg"><span>Total</span><b>{fmtPKR(totals.total)}</b></div></div>
          <div className="mt-3 space-y-2"><Label>Bill discount %</Label><Input type="number" value={billDisc} onChange={(e) => setBillDisc(Number(e.target.value))} />
          <Label>Payment method</Label><select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full px-3 py-2.5 rounded-xl border bg-white dark:bg-slate-900">{['Cash', 'Card', 'EasyPaisa', 'JazzCash', 'Bank Transfer', 'Credit'].map((m) => <option key={m}>{m}</option>)}</select>
          <Label>Amount paid (paisa in Rs)</Label><Input type="number" value={paid ? paid / 100 : ''} placeholder={String(totals.total / 100)} onChange={(e) => setPaid(Math.round(Number(e.target.value) * 100))} />
          <div className="flex justify-between text-sm"><span>Change</span><b>{fmtPKR(change)}</b></div>
          <Btn className="w-full" onClick={pay}>Pay — F5</Btn>
          <div className="grid grid-cols-2 gap-2"><Btn variant="ghost" onClick={() => api('pos:held', { data: JSON.stringify(cart) }).then(() => { setCart([]); setMsg('Bill held'); })}>Hold — F8</Btn><Btn variant="ghost" onClick={() => setShowHeld(true)}>Recall — F9</Btn></div>
          {receipt && <div className="text-sm bg-emerald-50 p-3 rounded-xl">Receipt saved: {receipt.billNo}. WhatsApp share: <a className="text-brand-600 font-bold" href={`https://wa.me/?text=${encodeURIComponent(`PharmaCore bill ${receipt.billNo}: ${fmtPKR(receipt.total)}`)}`} target="_blank" rel="noreferrer">wa.me link →</a></div>}
          </div>
        </Card>
      </div>
      <Modal open={showHeld} onClose={() => setShowHeld(false)} title="Held bills">{held.map((h: any) => <div key={h.id} className="py-2 border-b flex justify-between"><span>Held #{h.id} — {h.created_at}</span><Btn variant="ghost" onClick={() => { try { setCart(JSON.parse(h.data)); } catch {} setShowHeld(false); }}>Recall</Btn></div>)}{held.length === 0 && <p className="text-slate-500">No held bills.</p>}</Modal>
    </div>
  );
}
