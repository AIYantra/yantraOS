/** @type {import('tailwindcss').Config} */
export default {
  // Purge unused classes from all source files
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],

  // Enable class-based dark mode so we can toggle programmatically
  darkMode: 'class',

  theme: {
    extend: {
      // ── YantraOS Design Tokens ───────────────────────────────────────────
      colors: {
        yantra: {
          50:  '#f0f4ff',
          100: '#dce6fe',
          200: '#b9ccfd',
          300: '#86a4fb',
          400: '#4d72f8',
          500: '#2548f0',  // primary brand
          600: '#1530d4',
          700: '#1226ab',
          800: '#14228b',
          900: '#15216d',
          950: '#0e1547',
        },
        surface: {
          DEFAULT: '#0d1117',
          raised:  '#161b22',
          border:  '#30363d',
          muted:   '#8b949e',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in':    'fadeIn 0.3s ease-out',
        'slide-up':   'slideUp 0.4s ease-out',
      },
      keyframes: {
        fadeIn:  { from: { opacity: '0' },                to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
    },
  },

  plugins: [],
}
