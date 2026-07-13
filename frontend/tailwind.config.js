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
        display: [
          '"Space Grotesk"',
          '"Noto Sans JP"',
          '"Hiragino Sans"',
          '"Yu Gothic UI"',
          'system-ui',
          'sans-serif',
        ],
      },
      colors: {
        // Campus Signal: warm graphite elevation scale.
        ink: {
          base: '#0d0f0e',
          surface: '#131614',
          raised: '#1b1e1c',
          high: '#252925',
          paper: '#f0efe9',
        },
        edge: {
          DEFAULT: 'rgba(244, 243, 237, 0.09)',
          strong: 'rgba(244, 243, 237, 0.17)',
        },
        fill: {
          hover: 'rgba(244, 243, 237, 0.055)',
          active: 'rgba(244, 243, 237, 0.10)',
        },
        brand: {
          signal: '#ff7657',
          soft: '#ff9a80',
        },
      },
      backgroundImage: {
        'aurora-text': 'linear-gradient(105deg, #ff8f70 5%, #ffc46b 48%, #6fe8a8 96%)',
        'aurora-edge': 'linear-gradient(100deg, rgba(255,143,112,.72), rgba(255,196,107,.58), rgba(111,232,168,.68))',
      },
      borderRadius: {
        'ui-sm': 'var(--radius-sm)',
        ui: 'var(--radius-md)',
        'ui-lg': 'var(--radius-lg)',
        sheet: 'var(--radius-sheet)',
      },
      boxShadow: {
        glass: 'var(--shadow-overlay)',
        soft: 'var(--shadow-raised)',
        hairline: 'var(--shadow-hairline)',
      },
      transitionDuration: {
        fast: 'var(--motion-fast)',
        base: 'var(--motion-base)',
        slow: 'var(--motion-slow)',
      },
      transitionTimingFunction: {
        standard: 'var(--ease-standard)',
        expressive: 'var(--ease-expressive)',
      },
    },
  },
  plugins: [],
}
