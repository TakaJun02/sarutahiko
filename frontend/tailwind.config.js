/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'sans-serif',
        ],
      },
      colors: {
        brand: {
          coral: '#FF8A65',
          sun: '#FFEB3B',
          mint: '#69F0AE',
        },
      },
      boxShadow: {
        glass: '0 24px 80px rgba(0, 0, 0, 0.42)',
      },
    },
  },
  plugins: [],
}
