/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"Noto Sans JP"',
          '"Hiragino Sans"',
          '"Yu Gothic UI"',
          'system-ui',
          'sans-serif',
        ],
      },
      colors: {
        // Dark elevation scale: base = page, surface = sidebar/cards, raised = inputs/menus.
        ink: {
          base: '#0b0d12',
          surface: '#12151c',
          raised: '#1a1e28',
        },
        // Hairline borders on dark surfaces.
        edge: {
          DEFAULT: 'rgba(255, 255, 255, 0.08)',
          strong: 'rgba(255, 255, 255, 0.16)',
        },
        // Interactive fills (hover / active) on dark surfaces.
        fill: {
          hover: 'rgba(255, 255, 255, 0.06)',
          active: 'rgba(255, 255, 255, 0.11)',
        },
        brand: {
          coral: '#FF8A65',
          sun: '#FFEB3B',
          mint: '#69F0AE',
        },
      },
      backgroundImage: {
        // The single brand thread: send button, active-thread bar, countdown chip, header hairline.
        'brand-line': 'linear-gradient(90deg, #FF8A65, #FFEB3B, #69F0AE)',
      },
      boxShadow: {
        glass: '0 24px 80px rgba(0, 0, 0, 0.42)',
        soft: '0 10px 30px rgba(0, 0, 0, 0.35)',
        'glow-mint': '0 0 0 1px rgba(105, 240, 174, 0.30), 0 4px 28px rgba(105, 240, 174, 0.13)',
      },
    },
  },
  plugins: [],
}
