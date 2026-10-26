import React, { useRef, useState } from 'react';
import { api } from '../lib/api';
import { ScannerBuffer, parseGS1, beep } from '../lib/scanner';
import { Card, Btn, Input, Modal } from '../components/ui';
import { useApp } from '../lib/store';
export default function ScanToAdd() {
  const { user } = useApp();
  const [lines, setLines] = useState<any[]>([]); const [msg, setMsg] = useState(''); const [unknown, setUnknown] = useState<string | null>(null);
  const [newMed, setNewMed] = useState({ name: '', generic: '', company: '', form: 'Tablet', strength: '' });
  const buf = useRef(new ScannerBuffer());
  const onKey = (e: React.KeyboardEvent) => {
    const code = buf.current.key(e.key === 'Enter' ? 'Enter' : e.key.length === 1 ? e.key : '');
    if (e.key === 'Enter' && code) {
      const { barcode, batch, expiry } = parseGS1(code);
      api('scan:lookup', { barcode, userId: user?.id }).then((r: any) => {
        if (!r.found) { setUnknown(barcode); beep(false); setMsg(`Unknown barcode ${barcode}`); return; }
        beep(true);
        setLines((ls) => { const ex = ls.find((l) => l.medicineId === r.medicine.id); if (ex) return ls.map((l) => l.medicineId === r.medicine.id ? { ...l, qtyBase: l.qtyBase + 10 } : l); return [...ls, { medicineId: r.medicine.id, name: r.medicine.name, qtyBase: 10, batchNo: batch || 'B-NEW', expiry: expiry || '2027-06-30', costPaisa: r.medicine.purchase_price_paisa, salePaisa: r.medicine.sale_price_paisa }]; });
        setMsg(`Scanned: ${r.medicine.name}`);
      });
    }
  };
  const confirm = async () => { await api('scan:stockIn', { lines, userId: user?.id }); setLines([]); setMsg('Stock-in committed in one transaction ✓'); };
  const saveNew = async () => { const r = await api('medicines:create', { ...newMed, barcode: unknown }); setLines((ls) => [...ls, { medicineId: r.id, name: newMed.name, qtyBase: 10, batchNo: 'B-NEW', expiry: '2027-06-30', costPaisa: 0, salePaisa: 0 }]); setUnknown(null); setMsg('New medicine saved, scanning continues'); };
  return (<div className="space-y-4" onKeyDown={onKey}>
    <Card><h3 className="font-bold">Scan to Add — continuous scan mode</h3><p className="text-sm text-slate-500">Focus here and scan. A fast scan burst ending in Enter is detected automatically; normal typing is not treated as a scan. Scanning the same item again adds 1 strip.</p>
    <Input autoFocus placeholder="Click here, then scan a barcode…" className="mt-3 text-lg py-3" />
    {msg && <p className="mt-2 text-sm font-semibold">{msg}</p>}</Card>
    <Card><table className="w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Medicine</th><th>Batch</th><th>Expiry</th><th>Qty (base)</th><th></th></tr></thead><tbody>
      {lines.map((l, i) => <tr key={i} className="border-t"><td className="py-2 font-semibold">{l.name}</td><td><Input value={l.batchNo} onChange={(e) => setLines((ls) => ls.map((x, j) => j === i ? { ...x, batchNo: e.target.value } : x))} /></td><td><Input type="date" value={l.expiry} onChange={(e) => setLines((ls) => ls.map((x, j) => j === i ? { ...x, expiry: e.target.value } : x))} /></td><td><Input type="number" value={l.qtyBase} onChange={(e) => setLines((ls) => ls.map((x, j) => j === i ? { ...x, qtyBase: Number(e.target.value) } : x))} /></td><td><button className="text-red-500 font-bold" onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}>×</button></td></tr>)}
    </tbody></table>
    <div className="flex gap-2 mt-3"><Btn onClick={confirm} disabled={!lines.length}>Confirm Stock In (one transaction)</Btn><Btn variant="ghost" onClick={() => setLines((ls) => ls.slice(0, -1))}>Undo last scan</Btn></div></Card>
    <Modal open={!!unknown} onClose={() => setUnknown(null)} title="New medicine — add now?"><p className="text-sm mb-3">Barcode <b>{unknown}</b> is not in the system. It is prefilled below.</p>
      <div className="space-y-2"><Input placeholder="Name *" value={newMed.name} onChange={(e) => setNewMed({ ...newMed, name: e.target.value })} /><Input placeholder="Generic / salt" value={newMed.generic} onChange={(e) => setNewMed({ ...newMed, generic: e.target.value })} /><Input placeholder="Company" value={newMed.company} onChange={(e) => setNewMed({ ...newMed, company: e.target.value })} /><Btn className="w-full" onClick={saveNew}>Save & continue scanning</Btn></div></Modal>
  </div>);
}
