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

async function request(path, options = {}, { retry = 1 } = {}) {
    try {
        const res = await fetch(`${API_BASE}${path}`, {
            headers: { 'Content-Type': 'application/json' },
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
        if (!navigator.onLine || e.message.includes('Failed to fetch')) {
            setOnline(false);
        }
        if (retry > 0 && !navigator.onLine) {
            await new Promise(r => setTimeout(r, 1000));
            return request(path, options, { retry: retry - 1 });
        }
        throw e;
    }
}

export const fetchTask = (taskId) => request(`/tasks/${taskId}`);

export const listTasks = (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return request(`/tasks/${q ? '?' + q : ''}`);
};

export const submitTask = (product) =>
    request('/tasks/submit', { method: 'POST', body: JSON.stringify(product) });

export const fetchTimeline = (taskId) =>
    request(`/traces/by-task/${taskId}/timeline`);

export function pollTaskUntilDone(taskId, { intervalMs = 3000, timeoutMs = 300_000 } = {}) {
    return new Promise((resolve, reject) => {
        const deadline = Date.now() + timeoutMs;
        const tick = async () => {
            try {
                const task = await fetchTask(taskId);
                if (isTerminal(task.status)) {
                    const timeline = await fetchTimeline(taskId).catch(() => null);
                    return resolve({ task, timeline });
                }
                if (Date.now() > deadline) {
                    return reject(new Error('轮询超时: 任务长时间未完成'));
                }
                setTimeout(tick, intervalMs);
            } catch (e) {
                reject(e);
            }
        };
        tick();
    });
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