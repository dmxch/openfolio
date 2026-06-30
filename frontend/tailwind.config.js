/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      screens: {
        // Desktop-Chrome (Sidebar) nur bei genug Breite UND Hoehe.
        // Verhindert, dass ein Handy im Querformat (breit, aber niedrig)
        // als Desktop gilt und die Sidebar die Chart-Breite frisst.
        desk: { raw: '(min-width: 768px) and (min-height: 500px)' },
      },
      colors: {
        // --- Surfaces ---
        body: '#0a0d12',
        sidebar: '#0c0f15',
        card: '#11151d',
        'card-2': '#0f141c',       // nested / inner panel
        'card-hover': '#131925',
        surface: '#10151d',        // buttons / inputs / secondary chrome
        'table-head': '#0e131b',
        hover: '#141a23',          // row / element hover
        modal: '#121821',
        'active-tint': '#15203a',  // active nav / filter tint
        'card-alt': '#141a23',     // legacy alias → hover tone

        // --- Borders ---
        border: '#222a36',         // primary card border (legacy name kept)
        'border-soft': '#1a212c',  // header / sidebar dividers
        'border-2': '#1c2331',     // inner dividers
        'border-row': '#161d27',   // table row divider
        'border-row2': '#181f2a',
        'border-chip': '#232c39',  // ticker chip
        'border-hover': '#2c3645',
        'border-active': '#2f4470',

        // --- Text ---
        'text-primary': '#e9eef5',
        'text-secondary': '#9aa6b6', // legacy "secondary" role → muted body
        'text-muted': '#7a8698',     // legacy "muted" → dim
        'text-bright': '#cbd4e0',    // emphasized secondary
        'text-label': '#626d7d',     // mono micro-labels
        'text-faint': '#5f6d7d',

        // --- Accents / semantic ---
        primary: '#5b8def',
        'primary-btn': '#1d4ed8',
        'primary-btn-border': '#2f5fe0',
        link: '#9bb4e8',
        success: '#45c08a',
        danger: '#e8625a',
        warning: '#e0a64b',
        etf: {
          DEFAULT: '#29c3b1',
          light: '#29c3b1',
        },

        // --- Asset-class accents ---
        'cls-stock': '#5b8def',
        'cls-etf': '#29c3b1',
        'cls-crypto': '#b06ee8',
        'cls-metal': '#e0a64b',
        'cls-realestate': '#6b8aa0',
        'cls-pe': '#8a7de0',
        'cls-cash': '#7a8698',
        'cls-pension': '#45c08a',
      },
      borderRadius: {
        card: '11px',
      },
      fontFamily: {
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
