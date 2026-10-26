import { create } from 'zustand';
export type Lang = 'en' | 'ur';
interface State {
  user: { id: number; name: string; role: string } | null;
  lang: Lang; dark: boolean; shiftOpen: boolean;
  setUser: (u: State['user']) => void; setLang: (l: Lang) => void; toggleDark: () => void; setShift: (b: boolean) => void;
}
export const useApp = create<State>((set) => ({
  user: null, lang: 'en', dark: false, shiftOpen: false,
  setUser: (user) => set({ user }), setLang: (lang) => set({ lang }),
  toggleDark: () => set((s) => { document.documentElement.classList.toggle('dark', !s.dark); return { dark: !s.dark }; }),
  setShift: (shiftOpen) => set({ shiftOpen }),
}));
export const t = (lang: Lang, en: string, ur: string) => (lang === 'ur' ? ur : en);
