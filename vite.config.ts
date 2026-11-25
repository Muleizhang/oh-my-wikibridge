import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { reasoningApi } from './server/reasoning';

export default defineConfig({
  plugins: [react(), reasoningApi()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
});
