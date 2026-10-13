module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx}',
    './components/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        'bg-base': 'var(--bg-base)',
        'bg-surface': 'var(--bg-surface)',
        'bg-subtle': 'var(--bg-subtle)',
        base:    'var(--bg-base)',
        surface: 'var(--bg-surface)',
        elevated:'var(--bg-elevated)',
        border: {
          subtle:  'var(--border-subtle)',
          default: 'var(--border-default)',
        },
        accent: {
          primary: '#3B82F6',
          success: '#22C55E',
          warning: '#F59E0B',
          danger:  '#EF4444',
        },
        text: {
          primary:   'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted:     'var(--text-muted)',
        },
      },
      fontFamily: {
        sans:  ['var(--font-ui)', 'DM Sans', 'sans-serif'],
        mono:  ['var(--font-mono)', 'JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.4s ease both',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
