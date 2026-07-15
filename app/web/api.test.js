import { afterEach, describe, expect, it, vi } from 'vitest';
import { pollTaskUntilDone, submitTask, uploadAsset } from './api.js';

function jsonResponse(body) {
    return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    });
}

describe('pollTaskUntilDone', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('publishes progress before resolving the terminal task', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(jsonResponse({ task_id: 'task_1', status: 'running', steps: [] }))
            .mockResolvedValueOnce(jsonResponse({ task_id: 'task_1', status: 'success', steps: [] }))
            .mockResolvedValueOnce(jsonResponse({ events: [] }));
        vi.stubGlobal('fetch', fetchMock);
        const updates = [];

        const result = await pollTaskUntilDone('task_1', {
            intervalMs: 0,
            onUpdate: task => updates.push(task.status),
        });

        expect(updates).toEqual(['running', 'success']);
        expect(result.task.status).toBe('success');
        expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    it('stops immediately when its abort signal is cancelled', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        const controller = new AbortController();
        controller.abort();

        await expect(pollTaskUntilDone('task_1', {
            signal: controller.signal,
        })).rejects.toMatchObject({ name: 'AbortError' });
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('creation API', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('uploads binary assets without forcing a JSON content type', async () => {
        const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ url: '/uploads/asset.jpg' }));
        vi.stubGlobal('fetch', fetchMock);
        const file = new File(['image'], 'product.jpg', { type: 'image/jpeg' });

        await uploadAsset(file, 'product');

        const [, options] = fetchMock.mock.calls[0];
        expect(options.method).toBe('POST');
        expect(options.body).toBeInstanceOf(FormData);
        expect(options.headers).toEqual({});
    });

    it('sends an idempotency key when creating a task', async () => {
        const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ task_id: 'task_1' }));
        vi.stubGlobal('fetch', fetchMock);

        await submitTask({ product_name: 'Aero One' }, 'request-key-123');

        const [, options] = fetchMock.mock.calls[0];
        expect(options.headers['Idempotency-Key']).toBe('request-key-123');
    });
});
