import React from 'react';
export const Card = ({ children, className = '' }: any) => <div className={`bg-white dark:bg-slate-900 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-800 p-4 ${className}`}>{children}</div>;
export const Btn = ({ children, onClick, variant = 'primary', className = '', title }: any) => {
  const base = 'px-4 py-2.5 rounded-xl font-semibold text-sm transition active:scale-[.98] disabled:opacity-50';
  const v = variant === 'primary' ? 'bg-brand-500 hover:bg-brand-600 text-white' : variant === 'danger' ? 'bg-red-500 hover:bg-red-600 text-white' : 'bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-100';
  return <button onClick={onClick} title={title} className={`${base} ${v} ${className}`}>{children}</button>;
};
export const Input = (p: any) => <input {...p} className={`w-full px-3 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm ${p.className || ''}`} />;
export const Label = ({ children }: any) => <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{children}</label>;
export const Badge = ({ children, tone = 'slate' }: any) => {
  const tones: any = { red: 'bg-red-100 text-red-700', orange: 'bg-orange-100 text-orange-700', yellow: 'bg-yellow-100 text-yellow-800', green: 'bg-emerald-100 text-emerald-700', slate: 'bg-slate-100 text-slate-700' };
  return <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${tones[tone]}`}>{children}</span>;
};
export function Modal({ open, onClose, title, children }: any) {
  if (!open) return null;
  return <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}><div className="bg-white dark:bg-slate-900 rounded-2xl w-full max-w-lg p-5 shadow-xl" onClick={(e) => e.stopPropagation()}><div className="flex justify-between items-center mb-4"><h3 className="font-bold text-lg">{title}</h3><button onClick={onClose} className="text-2xl leading-none">×</button></div>{children}</div></div>;
}
export const Stat = ({ label, value, sub }: any) => <Card><div className="text-xs text-slate-500 font-semibold uppercase">{label}</div><div className="text-2xl font-extrabold mt-1">{value}</div>{sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}</Card>;
