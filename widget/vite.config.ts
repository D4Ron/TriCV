import { defineConfig } from 'vite'

// One self-contained file, no framework runtime, no hashed filename — the embed
// snippet has to keep working after every rebuild.
export default defineConfig({
  build: {
    lib: {
      entry: 'src/index.ts',
      name: 'TriCVWidget',
      formats: ['iife'],
      fileName: () => 'widget.js',
    },
    rollupOptions: {
      output: { extend: true },
    },
    minify: 'esbuild',
    target: 'es2018',
    emptyOutDir: true,
  },
})
