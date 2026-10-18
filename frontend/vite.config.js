import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [react()],
  base: '/static/mindmaps/',
  build: {
    outDir: '../static/mindmaps',
    emptyOutDir: true,
    rollupOptions: {
      input: { mindmaps: resolve(__dirname, 'index.html'), wiki: resolve(__dirname, 'wiki.html') },
      output: {
        entryFileNames: 'assets/[name].js', assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
});
