import { defineConfig } from 'vitest/config';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
    resolve: {
        alias: {
            '/web': fileURLToPath(new URL('.', import.meta.url)),
        },
    },
    test: {
        environment: 'happy-dom',
        include: ['./**/*.test.js'],
    },
});
