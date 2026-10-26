// Unit conversion. All stock is stored in BASE units (smallest unit, usually tablets).
// Example: 1 box = 10 strips, 1 strip = 10 tablets  => 1 box = 100 base.
export interface UnitConv { box: number; strip: number; } // units per base? No: tablets per strip, strips per box
export type Unit = 'box' | 'strip' | 'tablet';
export function toBase(qty: number, unit: Unit, tabletsPerStrip: number, stripsPerBox: number): number {
  if (unit === 'tablet') return qty;
  if (unit === 'strip') return qty * tabletsPerStrip;
  return qty * stripsPerBox * tabletsPerStrip;
}
export function fromBase(baseQty: number, unit: Unit, tabletsPerStrip: number, stripsPerBox: number): number {
  if (unit === 'tablet') return baseQty;
  if (unit === 'strip') return baseQty / tabletsPerStrip;
  return baseQty / (stripsPerBox * tabletsPerStrip);
}
export function formatQty(baseQty: number, tabletsPerStrip: number, stripsPerBox: number): string {
  const perBox = stripsPerBox * tabletsPerStrip;
  const boxes = Math.floor(baseQty / perBox);
  const rem = baseQty % perBox;
  const strips = Math.floor(rem / tabletsPerStrip);
  const tabs = rem % tabletsPerStrip;
  const parts: string[] = [];
  if (boxes) parts.push(`${boxes} box`);
  if (strips) parts.push(`${strips} strip`);
  if (tabs || parts.length === 0) parts.push(`${tabs} tab`);
  return parts.join(' + ');
}
export function pricePerUnit(salePricePaisaPerTablet: number, unit: Unit, tabletsPerStrip: number, stripsPerBox: number): number {
  return salePricePaisaPerTablet * toBase(1, unit, tabletsPerStrip, stripsPerBox);
}
