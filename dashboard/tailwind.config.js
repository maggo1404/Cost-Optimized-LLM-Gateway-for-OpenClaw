export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        github: {
          bg: '#0d1117',
          card: '#161b22',
          border: '#30363d',
          text: '#c9d1d9',
          muted: '#8b949e',
          accent: '#58a6ff',
          success: '#3fb950',
          warning: '#d29922',
          danger: '#f85149'
        }
      }
    }
  },
  plugins: []
}
