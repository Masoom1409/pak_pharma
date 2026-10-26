/** @type {import('tailwindcss').Config} */
export default { content: ['./index.html', './src/**/*.{ts,tsx}'], darkMode: 'class', theme: { extend: { colors: { brand: { 50: '#eefaf7', 100: '#d7f2ec', 500: '#0f9d8a', 600: '#0d8777', 700: '#0b6e61' } }, fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] } } }, plugins: [] };
