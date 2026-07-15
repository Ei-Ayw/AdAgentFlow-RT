module.exports = {
  content: [
    './*.html',
    './*.js',
    './components/**/*.js',
    './pages/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        black: '#000000',
        white: '#ffffff',
      },
      boxShadow: {
        soft: '0 18px 50px rgba(0, 0, 0, 0.35)',
      },
    },
  },
  corePlugins: {
    preflight: false,
  },
};
