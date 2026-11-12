import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
// POV_API_URL permite apontar o proxy para um backend de teste em outra porta
// (ex.: http://127.0.0.1:18100) sem tocar na porta da demo; padrão = 8100.
const apiTarget = process.env.POV_API_URL || 'http://localhost:8100';
const apiProxy = {
  '/api': apiTarget,
  '/media': apiTarget,
};

export default defineConfig({
  plugins: [react()],
  define: { global: 'globalThis' },
  resolve: {
    alias: {
      buffer: require.resolve('buffer/'),
      events: require.resolve('events/'),
      process: require.resolve('process/browser'),
      stream: require.resolve('stream-browserify'),
    },
  },
  server: { host: '127.0.0.1',
    port: 5190,
    strictPort: true,
    proxy: apiProxy,
  },
  preview: { host: '127.0.0.1', port: 5190, strictPort: true, proxy: apiProxy },
});
