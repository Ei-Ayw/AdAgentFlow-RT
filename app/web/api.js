// AdAgentFlow 前端 API 客户端

const API_BASE = '/api/v1';

const TERMINAL = new Set(['success', 'failed', 'dead_letter', 'manual_review']);

export const isTerminal = (status) => TERMINAL.has(status);

let isOnline = true;
const onlineListeners = [];

export function onNetworkChange(fn) {
    onlineListeners.push(fn);
    return () => {
        const i = onlineListeners.indexOf(fn);
        if (i >= 0) onlineListeners.splice(i, 1);
    };
}

function setOnline(v) {
    if (v === isOnline) return;
    isOnline = v;
    onlineListeners.forEach(fn => fn(v));
}

function abortError() {
    return new DOMException('操作已取消', 'AbortError');
}

function delay(ms, signal) {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) return reject(abortError());
        const timer = setTimeout(resolve, ms);
        signal?.addEventListener('abort', () => {
            clearTimeout(timer);
            reject(abortError());
        }, { once: true });
    });
}

async function request(path, options = {}, { retry = 1 } = {}) {
    try {
        const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
        const res = await fetch(`${API_BASE}${path}`, {
            headers: isFormData ? {} : { 'Content-Type': 'application/json' },
            ...options,
        });
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            const err = new Error(`${res.status} ${res.statusText}: ${text}`);
            err.status = res.status;
            throw err;
        }
        setOnline(true);
        return res.json();
    } catch (e) {
        if (e.name === 'AbortError') throw e;
        const browserOffline = typeof navigator !== 'undefined' && !navigator.onLine;
        const networkFailure = !e.status;
        if (browserOffline || networkFailure) {
            setOnline(false);
        }
        if (retry > 0 && networkFailure) {
            await delay(1000, options.signal);
            return request(path, options, { retry: retry - 1 });
        }
        throw e;
    }
}

export const fetchTask = (taskId, options = {}) => request(`/tasks/${taskId}`, options);

export const listTasks = (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return request(`/tasks/${q ? '?' + q : ''}`);
};

export const submitTask = (product, idempotencyKey) =>
    request('/tasks/submit', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
        },
        body: JSON.stringify(product),
    });

export const uploadAsset = (file, kind = 'product') => {
    const form = new FormData();
    form.append('file', file);
    return request(`/assets/upload?kind=${encodeURIComponent(kind)}`, {
        method: 'POST',
        body: form,
    }, { retry: 0 });
};

export const fetchTimeline = (taskId, options = {}) =>
    request(`/traces/by-task/${taskId}/timeline`, options);

export async function pollTaskUntilDone(taskId, {
    intervalMs = 3000,
    timeoutMs = 300_000,
    signal,
    onUpdate,
} = {}) {
    const deadline = Date.now() + timeoutMs;
    while (true) {
        if (signal?.aborted) throw abortError();
        const task = await fetchTask(taskId, { signal });
        onUpdate?.(task);
        if (isTerminal(task.status)) {
            const timeline = await fetchTimeline(taskId, { signal }).catch((error) => {
                if (error.name === 'AbortError') throw error;
                return null;
            });
            return { task, timeline };
        }
        if (Date.now() > deadline) {
            throw new Error('轮询超时：任务长时间未完成');
        }
        await delay(intervalMs, signal);
    }
}

export function showToast(message, kind = 'warn', { durationMs = 4000 } = {}) {
    const container = document.getElementById('toast');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), durationMs);
}
