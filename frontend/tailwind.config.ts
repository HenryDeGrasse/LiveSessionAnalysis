import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        nerdy: {
          blue: '#0066FF',
          'blue-light': '#3385FF',
          'blue-dark': '#0052CC',
          navy: '#0A1628',
          orange: '#FF6B35',
          'orange-light': '#FF8C5A',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

export default config
