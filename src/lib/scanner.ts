// USB/Bluetooth keyboard-wedge scanner detection.
// A scan = a burst of keystrokes ending in Enter, faster than a human types.
// Normal typing is never treated as a scan.
export interface ScannerOptions { maxIntervalMs?: number; minLength?: number; }
export function isScanTiming(intervalsMs: number[], opts: ScannerOptions = {}): boolean {
  const max = opts.maxIntervalMs ?? 60;
  const min = opts.minLength ?? 3;
  if (intervalsMs.length + 1 < min) return false;
  return intervalsMs.every((i) => i <= max);
}
export class ScannerBuffer {
  private buf = ''; private last = 0; private intervals: number[] = [];
  constructor(private opts: ScannerOptions = {}) {}
  /** Returns the scanned code on Enter, otherwise null. */
  key(ch: string, now = Date.now()): string | null {
    if (ch === 'Enter') {
      const code = this.buf; const intervals = this.intervals; this.buf = ''; this.intervals = [];
      return code.length >= (this.opts.minLength ?? 3) && isScanTiming(intervals, this.opts) ? code : null;
    }
    if (ch.length !== 1) return null;
    if (this.last) this.intervals.push(now - this.last);
    this.last = now; this.buf += ch; return null;
  }
  reset() { this.buf = ''; this.intervals = []; this.last = 0; }
}
// GS1: (01) GTIN (10) batch (17) expiry YYMMDD. Also handles plain EAN-13/UPC/Code128/QR passthrough.
export function parseGS1(code: string): { barcode: string; batch?: string; expiry?: string } {
  const m = code.match(/\(01\)(\d+).*?\(10\)([^\x1d(]+).*?\(17\)(\d{6})/);
  if (m) {
    const yy = m[3].slice(0, 2), mm = m[3].slice(2, 4), dd = m[3].slice(4, 6);
    return { barcode: m[1], batch: m[2], expiry: `20${yy}-${mm}-${dd}` };
  }
  const plain = code.match(/^(01)?(\d{8,14})/);
  return { barcode: plain ? plain[2] : code.replace(/[^A-Za-z0-9-]/g, '') };
}
export function beep(ok: boolean) {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const o = ctx.createOscillator(); const g = ctx.createGain();
    o.frequency.value = ok ? 880 : 220; o.connect(g); g.connect(ctx.destination);
    g.gain.setValueAtTime(0.08, ctx.currentTime); o.start(); o.stop(ctx.currentTime + (ok ? 0.08 : 0.2));
  } catch { /* audio unavailable in Electron headless tests */ }
}
