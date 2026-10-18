/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#F4F3EF',
        card: '#FBFAF7',
        ink: '#14171C',
        muted: '#5F6670',
        line: '#D9D6CE',
        brand: { DEFAULT: '#1F3F94', soft: '#E3E8F4' },
        green: { DEFAULT: '#1E6B3A', soft: '#E1F0E5' },
        amber: { DEFAULT: '#9A5B00', soft: '#FBEFD6' },
        red: { DEFAULT: '#A8231B', soft: '#FBE4E1' },
      },
      fontFamily: {
        display: ['"Schibsted Grotesk"', 'system-ui', 'sans-serif'],
        sans: ['"Source Sans 3"', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"Source Code Pro"', 'ui-monospace', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
