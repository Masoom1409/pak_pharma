// FEFO: First-Expired, First-Out. Expired batches are NEVER selectable.
export interface Batch { id: number; batch_no: string; expiry: string; qty_base: number; }
export const todayISO = (): string => new Date().toISOString().slice(0, 10);
export const isExpired = (expiry: string, today = todayISO()): boolean => expiry < today;
export const daysToExpiry = (expiry: string, today = todayISO()): number =>
  Math.round((new Date(expiry).getTime() - new Date(today).getTime()) / 86400000);
export function expiryBadge(expiry: string): 'expired' | 'red' | 'orange' | 'ok' {
  const d = daysToExpiry(expiry);
  if (d < 0) return 'expired';
  if (d <= 30) return 'red';
  if (d <= 90) return 'orange';
  return 'ok';
}
/** Allocate `qty` across non-expired batches, earliest expiry first. Throws if short. */
export function allocateFEFO(batches: Batch[], qty: number, today = todayISO()): { batch_id: number; batch_no: string; qty: number }[] {
  const usable = batches.filter((b) => b.qty_base > 0 && !isExpired(b.expiry, today)).sort((a, b) => a.expiry.localeCompare(b.expiry));
  const out: { batch_id: number; batch_no: string; qty: number }[] = [];
  let remaining = qty;
  for (const b of usable) {
    if (remaining <= 0) break;
    const take = Math.min(b.qty_base, remaining);
    out.push({ batch_id: b.id, batch_no: b.batch_no, qty: take });
    remaining -= take;
  }
  if (remaining > 0) throw new Error(`Insufficient non-expired stock: short by ${remaining} units`);
  return out;
}
