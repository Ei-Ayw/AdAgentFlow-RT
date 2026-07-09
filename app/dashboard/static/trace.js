// =============================================================
// Trace 时间线 - 拉接口 → 画甘特图 → 渲染 step 卡 / 事件表
// =============================================================

const API_BASE = '/api/v1/traces';

const $ = (id) => document.getElementById(id);
const taskInput = $('task-input');
const loadBtn = $('load-btn');
const errBox = $('error-box');

// -------------------------------------------------------------
// Utilities
// -------------------------------------------------------------
function formatDuration(ms) {
    if (ms == null || isNaN(ms)) return '-';
    if (ms < 0) ms = 0;
    if (ms < 1000) return `${ms}ms`;
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(1)}s`;
    const m = Math.floor(s / 60);
    const r = Math.round(s % 60);
    return `${m}m ${r}s`;
}

function formatTime(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${hh}:${mm}:${ss}.${ms}`;
}

function showError(msg) {
    errBox.textContent = msg;
    errBox.style.display = 'block';
}

function clearError() {
    errBox.style.display = 'none';
    errBox.textContent = '';
}

function statusBadge(status) {
    const s = (status || 'unknown').toLowerCase();
    const cls = ['success', 'failed', 'running', 'queued', 'pending', 'retrying', 'dead_letter', 'evaluating', 'passed'].includes(s)
        ? s : 'pending';
    const label = status || 'unknown';
    return `<span class="status-badge ${cls}">${label}</span>`;
}

// -------------------------------------------------------------
// Load + render
// -------------------------------------------------------------
async function loadTimeline(taskId) {
    if (!taskId) {
        showError('请输入 task_id');
        return;
    }
    clearError();
    loadBtn.disabled = true;
    loadBtn.textContent = '加载中...';

    try {
        const resp = await fetch(`${API_BASE}/by-task/${encodeURIComponent(taskId)}/timeline`);
        if (resp.status === 404) {
            throw new Error(`task "${taskId}" 未找到`);
        }
        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
        }
        const data = await resp.json();
        renderAll(data);
        // URL 不带参的情况下也同步上去，方便刷新和分享
        const u = new URL(window.location.href);
        u.searchParams.set('task_id', taskId);
        history.replaceState(null, '', u);
    } catch (err) {
        showError(`加载失败: ${err.message}`);
        clearCards();
    } finally {
        loadBtn.disabled = false;
        loadBtn.textContent = '加载时间线';
    }
}

function clearCards() {
    ['task-card', 'gantt-card', 'steps-card', 'events-card'].forEach(id => $(id).style.display = 'none');
    $('empty-tip').style.display = 'block';
    $('task-info').innerHTML = '';
    $('step-list').innerHTML = '';
    $('event-tbody').innerHTML = '';
    $('gantt-svg').innerHTML = '';
}

function renderAll(data) {
    if (!data || !data.task) {
        clearCards();
        return;
    }
    $('empty-tip').style.display = 'none';

    renderTaskInfo(data.task);
    renderGantt(data.steps || []);
    renderStepCards(data.steps || [], data.evaluations || []);
    renderEventTable(data.traces || [], data.evaluations || []);

    ['task-card', 'gantt-card', 'steps-card', 'events-card'].forEach(id => $(id).style.display = 'block');
}

// -------------------------------------------------------------
// Task info card
// -------------------------------------------------------------
function renderTaskInfo(task) {
    const items = [
        ['task_id', task.task_id, 'mono'],
        ['状态', statusBadge(task.status), 'badge'],
        ['商品', task.product_name || '-'],
        ['平台', task.platform || '-'],
        ['风格', task.style || '-'],
        ['时长(秒)', task.duration ?? '-'],
        ['retry', `${task.retry_count} / ${task.max_retry || '-'}`],
        ['失败原因', task.last_failure_reason || '-'],
        ['创建时间', formatTime(task.created_at)],
        ['完成时间', formatTime(task.finished_at)],
    ];

    if (task.status === 'dead_letter' || task.status === 'failed') {
        items.push(['⚠️', '失败任务 — 查看下方错误事件', 'warn']);
    }

    $('task-info').innerHTML = items.map(([label, value, type]) => {
        let v = value;
        if (type === 'mono') v = `<span class="mono" style="font-family:monospace;font-size:13px;">${escapeHtml(value)}</span>`;
        return `<div class="item">
            <div class="label">${escapeHtml(String(label))}</div>
            <div class="value">${v}</div>
        </div>`;
    }).join('');
}

// -------------------------------------------------------------
// Gantt chart (native SVG)
// -------------------------------------------------------------
function renderGantt(steps) {
    const svg = $('gantt-svg');
    svg.innerHTML = '';

    if (!steps.length) {
        svg.setAttribute('width', '600');
        svg.setAttribute('height', '80');
        svg.innerHTML = '<text x="20" y="40" fill="#64748b" font-size="13">无 step 数据</text>';
        return;
    }

    // 收集所有 step 的 started_at / finished_at，找全局时间窗
    const visible = steps.filter(s => s.started_at);
    let tMin, tMax;
    if (visible.length) {
        const starts = visible.map(s => new Date(s.started_at).getTime());
        const ends = visible.map(s => new Date(s.finished_at || s.started_at).getTime());
        tMin = Math.min(...starts);
        tMax = Math.max(...ends);
        if (tMax === tMin) tMax = tMin + 1000;
        // 在两端各留 3% padding
        const pad = Math.max(200, (tMax - tMin) * 0.05);
        tMin -= pad;
        tMax += pad;
    } else {
        // 没有任何 started_at，用 created_at
        const created = steps.map(s => new Date(s.created_at).getTime());
        tMin = Math.min(...created);
        tMax = Math.max(...created) + 1000;
    }

    const ROW_H = 36;
    const LEFT_PAD = 200;
    const RIGHT_PAD = 30;
    const WIDTH = Math.max(900, 1280 - LEFT_PAD - RIGHT_PAD);
    const HEIGHT = ROW_H * steps.length + 50;

    svg.setAttribute('width', WIDTH + LEFT_PAD + RIGHT_PAD);
    svg.setAttribute('height', HEIGHT);
    svg.setAttribute('viewBox', `0 0 ${WIDTH + LEFT_PAD + RIGHT_PAD} ${HEIGHT}`);

    const xFor = (t) => LEFT_PAD + ((t - tMin) / (tMax - tMin)) * WIDTH;
    const ns = 'http://www.w3.org/2000/svg';
    const tag = (name, attrs = {}, text) => {
        const el = document.createElementNS(ns, name);
        for (const k in attrs) el.setAttribute(k, attrs[k]);
        if (text != null) el.textContent = text;
        return el;
    };

    // 时间轴 (顶部)
    const ticks = 6;
    for (let i = 0; i <= ticks; i++) {
        const t = tMin + (i / ticks) * (tMax - tMin);
        const x = xFor(t);
        const y = 18;
        svg.appendChild(tag('line', { x1: x, y1: y, x2: x, y2: HEIGHT - 6, stroke: 'rgba(148,163,184,0.12)', 'stroke-width': 1 }));
        const label = new Date(t).toISOString().substr(11, 8);
        svg.appendChild(tag('text', { x, y: 12, fill: '#94a3b8', 'font-size': 10, 'text-anchor': 'middle' }, label));
    }

    // 每行 step
    steps.forEach((step, idx) => {
        const rowY = 28 + idx * ROW_H;

        // step 名称 (左侧)
        svg.appendChild(tag('text', {
            x: 10,
            y: rowY + ROW_H / 2 + 4,
            fill: '#e2e8f0',
            'font-size': 12,
            'font-weight': 600,
        }, `${step.step_name || step.step_id}${step.retry_count > 0 ? `  ↻${step.retry_count}` : ''}`));

        // 行背景
        svg.appendChild(tag('rect', {
            x: LEFT_PAD,
            y: rowY + 4,
            width: WIDTH,
            height: ROW_H - 12,
            fill: 'rgba(15,23,42,0.4)',
            rx: 4,
        }));

        if (!step.started_at) {
            // 未开始
            svg.appendChild(tag('text', {
                x: LEFT_PAD + 8,
                y: rowY + ROW_H / 2 + 4,
                fill: '#64748b',
                'font-size': 11,
            }, '未开始'));
            return;
        }

        const s = new Date(step.started_at).getTime();
        const e = new Date(step.finished_at || new Date().toISOString()).getTime();
        const x1 = xFor(s);
        const x2 = xFor(Math.max(e, s + 50));   // 至少给 50ms 视觉宽度
        const w = Math.max(6, x2 - x1);

        // 状态判定
        const st = (step.status || '').toLowerCase();
        let fill = '#3b82f6';   // running default
        if (st === 'success' || st === 'succeeded' || st === 'completed') fill = '#22c55e';
        else if (st === 'failed' || st === 'dead_letter') fill = '#ef4444';
        else if (st === 'pending') fill = '#94a3b8';

        const barY = rowY + 6;
        const barH = ROW_H - 14;

        // 主条
        svg.appendChild(tag('rect', {
            x: x1,
            y: barY,
            width: w,
            height: barH,
            fill,
            rx: 4,
            opacity: 0.85,
        }));

        // retry 高亮 - 黄色描边
        if ((step.retry_count || 0) > 0) {
            svg.appendChild(tag('rect', {
                x: x1 - 1,
                y: barY - 1,
                width: w + 2,
                height: barH + 2,
                fill: 'none',
                stroke: '#f59e0b',
                'stroke-width': 2,
                rx: 4,
            }));
        }

        // 文字：耗时 / token（在条内）
        const inside = w > 100;
        if (inside) {
            const text = `${formatDuration(step.latency_ms)} · ${step.token_cost || 0} tok`;
            svg.appendChild(tag('text', {
                x: x1 + 6,
                y: barY + barH / 2 + 4,
                fill: '#0f172a',
                'font-size': 11,
                'font-weight': 600,
            }, text));
        } else {
            // 条太窄，文字放外面
            svg.appendChild(tag('text', {
                x: x2 + 6,
                y: barY + barH / 2 + 4,
                fill: '#cbd5e1',
                'font-size': 11,
            }, `${formatDuration(step.latency_ms)} · ${step.token_cost || 0} tok`));
        }
    });
}

// -------------------------------------------------------------
// Step cards
// -------------------------------------------------------------
function renderStepCards(steps, evals) {
    if (!steps.length) {
        $('step-list').innerHTML = '<div class="empty">暂无 step</div>';
        return;
    }

    // 把 evaluations 按 step_id 索引
    const evalByStep = {};
    evals.forEach(e => {
        if (!e.step_id) return;
        if (!evalByStep[e.step_id]) evalByStep[e.step_id] = [];
        evalByStep[e.step_id].push(e);
    });

    $('step-list').innerHTML = steps.map(s => {
        const st = (s.status || '').toLowerCase();
        const isFailed = st === 'failed' || st === 'dead_letter';
        const isRunning = st === 'running' || st === 'started' || st === 'evaluating';
        const isSuccess = st === 'success' || st === 'succeeded' || st === 'completed';
        const hasRetry = (s.retry_count || 0) > 0;

        const cls = ['step-card'];
        if (isFailed) cls.push('failed');
        else if (isSuccess) cls.push('success');
        if (hasRetry) cls.push('retry');
        if (isRunning) cls.push('running');

        const evs = evalByStep[s.step_id] || [];
        const evalBadges = evs.map(e => {
            const passedCls = e.passed === true ? 'passed' : (e.passed === false ? 'failed' : 'pending');
            const label = e.passed === true ? `通过 ${e.score ?? ''}` :
                          e.passed === false ? `未通过 ${e.score ?? ''}` :
                          `评分 ${e.score ?? '-'}`;
            return `<span class="status-badge ${passedCls}">${escapeHtml(label)}</span>`;
        }).join(' ');

        return `<div class="${cls.join(' ')}">
            <div class="step-name">${escapeHtml(s.step_name || s.step_id)} ${statusBadge(s.status)}</div>
            <div class="meta-row">
                <span>step_id: ${escapeHtml(s.step_id)}</span>
                ${(s.retry_count || 0) > 0 ? `<span>retry: ${s.retry_count}</span>` : ''}
                ${s.latency_ms ? `<span>耗时: ${formatDuration(s.latency_ms)}</span>` : ''}
                ${(s.token_cost || 0) > 0 ? `<span>tokens: ${s.token_cost}</span>` : ''}
                ${s.model_name ? `<span>model: ${escapeHtml(s.model_name)}</span>` : ''}
                ${s.prompt_version ? `<span>prompt: ${escapeHtml(s.prompt_version)}</span>` : ''}
                <span>起: ${formatTime(s.started_at)}</span>
                <span>止: ${formatTime(s.finished_at)}</span>
            </div>
            ${s.failure_reason ? `<div class="meta-row"><span>failure_reason: ${escapeHtml(s.failure_reason)}</span></div>` : ''}
            ${evalBadges ? `<div class="meta-row" style="margin-top:6px;">评估: ${evalBadges}</div>` : ''}
            ${s.error_message ? `<div class="error">${escapeHtml(s.error_message)}</div>` : ''}
        </div>`;
    }).join('');
}

// -------------------------------------------------------------
// Event table - merges traces + evaluations
// -------------------------------------------------------------
function renderEventTable(traces, evals) {
    const rows = [];

    traces.forEach(t => rows.push({
        kind: 'trace',
        ts: t.created_at,
        type: t.event_type,
        step: t.step_id,
        status: t.event_status,
        latency: t.latency_ms,
        model: t.model_name,
        prompt: t.prompt_version,
        token: t.token_cost,
        note: t.error_message || '',
    }));

    evals.forEach(e => rows.push({
        kind: 'eval',
        ts: e.created_at,
        type: 'evaluation',
        step: e.step_id,
        status: e.passed === true ? 'passed' : (e.passed === false ? 'failed' : 'info'),
        latency: null,
        model: e.evaluator_model,
        prompt: e.prompt_version,
        token: null,
        note: `score=${e.score ?? '-'} risk=${e.risk_level ?? '-'} ${e.suggested_fix || ''}`.trim(),
    }));

    rows.sort((a, b) => {
        const ta = a.ts ? new Date(a.ts).getTime() : 0;
        const tb = b.ts ? new Date(b.ts).getTime() : 0;
        return ta - tb;
    });

    if (!rows.length) {
        $('event-tbody').innerHTML = '<tr><td colspan="9" class="empty">暂无事件</td></tr>';
        return;
    }

    $('event-tbody').innerHTML = rows.map(r => `<tr>
        <td class="mono">${escapeHtml(formatTime(r.ts))}</td>
        <td>${escapeHtml(r.type || '-')}</td>
        <td class="mono">${escapeHtml(r.step || '-')}</td>
        <td>${statusBadge(r.status)}</td>
        <td class="mono">${r.latency ? formatDuration(r.latency) : '-'}</td>
        <td class="mono">${escapeHtml(r.model || '-')}</td>
        <td class="mono">${escapeHtml(r.prompt || '-')}</td>
        <td class="mono">${r.token ?? '-'}</td>
        <td class="${r.note && (r.status === 'failed' || r.status === 'failed') ? 'error-cell' : ''}">${escapeHtml(r.note || '')}</td>
    </tr>`).join('');
}

// -------------------------------------------------------------
// HTML escaping
// -------------------------------------------------------------
function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

// -------------------------------------------------------------
// Wire up
// -------------------------------------------------------------
loadBtn.addEventListener('click', () => loadTimeline(taskInput.value.trim()));
taskInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadTimeline(taskInput.value.trim());
});

// 自动从 URL ?task_id=xxx 加载
(function autoLoad() {
    const params = new URLSearchParams(window.location.search);
    const tid = params.get('task_id');
    if (tid) {
        taskInput.value = tid;
        loadTimeline(tid);
    }
})();
