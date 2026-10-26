import { describe, it, expect } from 'vitest';
import { allocateFEFO, isExpired, expiryBadge } from '../src/lib/fefo';
import { toBase, fromBase, formatQty, pricePerUnit } from '../src/lib/units';
import { calcBill, calcLine, fmtPKR, toPaisa } from '../src/lib/money';
import { ScannerBuffer, parseGS1, isScanTiming } from '../src/lib/scanner';

describe('FEFO', () => {
  const batches = [{ id: 1, batch_no: 'LATE', expiry: '2027-06-30', qty_base: 500 }, { id: 2, batch_no: 'SOON', expiry: '2026-12-15', qty_base: 200 }, { id: 3, batch_no: 'DEAD', expiry: '2025-01-01', qty_base: 999 }];
  it('picks earliest non-expired batch first and never expired', () => {
    expect(allocateFEFO(batches, 250, '2026-10-26')).toEqual([{ batch_id: 2, batch_no: 'SOON', qty: 200 }, { batch_id: 1, batch_no: 'LATE', qty: 50 }]);
  });
  it('throws when only expired stock exists', () => { expect(() => allocateFEFO([{ id: 9, batch_no: 'X', expiry: '2025-01-01', qty_base: 10 }], 1, '2026-10-26')).toThrow(); });
  it('expiry badges', () => { expect(isExpired('2025-01-01', '2026-10-26')).toBe(true); expect(expiryBadge('2026-11-10')).toBe('red'); expect(expiryBadge('2027-06-30')).toBe('ok'); });
});
describe('units', () => {
  it('box/strip/tablet conversion', () => { expect(toBase(1, 'box', 10, 10)).toBe(100); expect(toBase(2, 'strip', 10, 10)).toBe(20); expect(fromBase(100, 'box', 10, 10)).toBe(1); expect(formatQty(125, 10, 10)).toBe('1 box + 2 strip + 5 tab'); expect(pricePerUnit(1500, 'strip', 10, 10)).toBe(15000); });
});
describe('money (integer paisa)', () => {
  it('no float drift', () => { expect(toPaisa(19.99)).toBe(1999); expect(calcLine(10, 1500, 10, 0)).toBe(13500); expect(calcBill([{ amount: 10000 }], 10, 0, 0).total).toBe(9000); expect(fmtPKR(1999)).toContain('19.99'); });
});
describe('scanner', () => {
  it('fast burst = scan, slow typing = not scan', () => { expect(isScanTiming([10, 12, 8, 15])).toBe(true); expect(isScanTiming([200, 300])).toBe(false); const b = new ScannerBuffer(); expect(b.key('1', 1000)).toBeNull(); expect(b.key('2', 1010)).toBeNull(); expect(b.key('3', 1020)).toBeNull(); expect(b.key('Enter', 1030)).toBe('123'); });
  it('GS1 batch/expiry parse', () => { const r = parseGS1('(01)08901112223333(10)B123(17)270630'); expect(r.batch).toBe('B123'); expect(r.expiry).toBe('2027-06-30'); });
});
