/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#f6f7f9',
          100: '#eceef2',
          200: '#d7dce2',
          300: '#b4bdc8',
          400: '#8b98a8',
          500: '#6b7280',
          600: '#4b5563',
          700: '#374151',
          800: '#252f3b',
          900: '#1f2933',
        },
        brand: {
          50: '#eff7ff',
          100: '#dbeeff',
          200: '#bfe1ff',
          300: '#93cdff',
          400: '#60b0ff',
          500: '#3b8fef',
          600: '#2f7fb8',
          700: '#245f8b',
          800: '#1e4c6f',
          900: '#1c3f5b',
        },
        fit: {
          strong: '#1f7a4d',
          good: '#2f7fb8',
          maybe: '#b8860b',
          no: '#a83232',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(31, 41, 51, 0.06), 0 4px 12px rgba(31, 41, 51, 0.05)',
        drawer: '-8px 0 32px rgba(31, 41, 51, 0.12)',
      },
    },
  },
  plugins: [],
}
