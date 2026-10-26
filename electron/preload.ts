import { contextBridge, ipcRenderer } from 'electron';
const channels = ['auth:login','medicines:search','medicines:list','medicines:create','medicines:stock','inventory:alerts','inventory:adjust','scan:lookup','scan:stockIn','pos:sale','pos:return','pos:held','pos:heldList','dashboard','customers:list','customers:create','suppliers:list','purchases:create','reports:sales','audit:list','backup:create','settings:get','settings:set','app:dbPath','app:pickDbFolder','app:print'];
const api: Record<string, (a?: any) => Promise<any>> = {};
for (const ch of channels) api[ch] = (arg?: any) => ipcRenderer.invoke(ch, arg);
contextBridge.exposeInMainWorld('pharmacore', api);
declare global { interface Window { pharmacore?: Record<string, (a?: any) => Promise<any>> } }
