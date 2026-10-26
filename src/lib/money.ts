// Money is ALWAYS integer paisa. Never use floats for money in the app.
// PKR 1 = 100 paisa. Display helpers round only at render time.
export const toPaisa = (rupees: number): number => Math.round(rupees * 100);
export const fromPaisa = (paisa: number): number => paisa / 100;
export const fmtPKR = (paisa: number): string =>
  'Rs ' + (paisa / 100).toLocaleString('en-PK', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const roundBill = (paisa: number): { total: number; rounding: number } => {
  // Round to nearest rupee (100 paisa) — configurable in Settings in a later pass.
  const total = Math.round(paisa / 100) * 100;
  return { total, rounding: total - paisa };
};
export function calcLine(qtyBase: number, unitPricePaisa: number, discPct = 0, discAmtPaisa = 0): number {
  const gross = qtyBase * unitPricePaisa;
  const afterPct = gross - Math.round((gross * discPct) / 100);
  return Math.max(0, afterPct - discAmtPaisa);
}
export function calcBill(lines: { amount: number }[], billDiscPct = 0, billDiscAmt = 0, taxPct = 0) {
  const subtotal = lines.reduce((s, l) => s + l.amount, 0);
  const afterDisc = Math.max(0, subtotal - Math.round((subtotal * billDiscPct) / 100) - billDiscAmt);
  const tax = Math.round((afterDisc * taxPct) / 100);
  const { total, rounding } = roundBill(afterDisc + tax);
  return { subtotal, discount: subtotal - afterDisc, tax, rounding, total };
}
