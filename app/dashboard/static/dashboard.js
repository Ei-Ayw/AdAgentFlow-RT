// AdAgentFlow Dashboard JS - 拉 API + 渲染 + 自动刷新

const API_BASE = '/api/v1';

async function fetchJSON(url, opts = {}) {
    try {
        const resp = await fetch(url, opts);
        if (!resp.ok) {
            return { error: `${resp.status} ${resp.statusText}`, detail: await resp.text() };
        }
        return await resp.json();
    } catch (e) {
        return { error: String(e) };
    }
}

function badge(text, status) {
    return `<span class="status-badge ${status}">${text}</span>`;
}

async function loadOverview() {
    const data = await fetchJSON(`${API_BASE}/dashboard/overview`);
    if (data.error) {
        console.error(data);
        return;
    }

    const ts = data.task_summary;
    document.getElementById('task-summary').innerHTML = `
        <div class="metric success">
            <div class="label">端到端成功率</div>
            <div class="value">${ts.end_to_end_success_rate}%</div>
        </div>
        <div class="metric info">
            <div class="label">总任务数</div>
            <div class="value">${ts.total_tasks}</div>
        </div>
        <div class="metric success">
            <div class="label">成功任务</div>
            <div class="value">${ts.success}</div>
        </div>
        <div class="metric failed">
            <div class="label">失败任务</div>
            <div class="value">${ts.failed}</div>
        </div>
        <div class="metric warning">
            <div class="label">死信任务</div>
            <div class="value">${ts.dead_letter}</div>
        </div>
        <div class="metric info">
            <div class="label">运行中</div>
            <div class="value">${ts.running}</div>
        </div>
    `;

    const p = data.performance;
    document.getElementById('performance-metrics').innerHTML = `
        <div class="metric info">
            <div class="label">平均任务耗时</div>
            <div class="value">${p.avg_latency_seconds}s</div>
        </div>
        <div class="metric warning">
            <div class="label">平均重试次数</div>
            <div class="value">${p.avg_retry_count}</div>
        </div>
        <div class="metric info">
            <div class="label">总 LLM 调用</div>
            <div class="value">${p.total_llm_calls}</div>
        </div>
        <div class="metric failed">
            <div class="label">JSON 解析失败率</div>
            <div class="value">${p.json_failure_rate}%</div>
        </div>
        <div class="metric failed">
            <div class="label">死信率</div>
            <div class="value">${p.dead_letter_rate}%</div>
        </div>
        <div class="metric success">
            <div class="label">平均质量分</div>
            <div class="value">${p.avg_quality_score}</div>
        </div>
        <div class="metric success">
            <div class="label">Judge 通过率</div>
            <div class="value">${p.judge_pass_rate}%</div>
        </div>
    `;

    // 节点成功率
    const nsr = document.querySelector('#node-success-table tbody');
    nsr.innerHTML = (data.node_success_rates || []).map(n => `
        <tr>
            <td>${n.step_id}</td>
            <td>${n.total_executions}</td>
            <td>${n.success_executions}</td>
            <td>${(n.success_rate * 100).toFixed(1)}%</td>
        </tr>
    `).join('');

    // 失败 Top 5
    const ft = document.querySelector('#failure-top-table tbody');
    ft.innerHTML = (data.failure_top_5 || []).map(f => `
        <tr>
            <td>${f.reason}</td>
            <td>${f.count}</td>
        </tr>
    `).join('');

    // 未处理死信
    const dl = document.querySelector('#dead-letter-table tbody');
    dl.innerHTML = (data.unresolved_dead_letters || []).map(d => `
        <tr>
            <td>${d.id}</td>
            <td><a href="/dashboard?task_id=${d.task_id}">${d.task_id}</a></td>
            <td>${d.step_id || ''}</td>
            <td>${d.failure_reason || ''}</td>
            <td>${(d.created_at || '').slice(0, 19)}</td>
            <td>
                <button class="action-btn" onclick="resumeDl('${d.task_id}')">重新派发</button>
            </td>
        </tr>
    `).join('');
}

async function resumeDl(taskId) {
    if (!confirm(`确认重新派发任务 ${taskId} 吗？`)) return;
    const resp = await fetchJSON(`${API_BASE}/dead-letters/${taskId}/resume`, { method: 'POST' });
    if (resp.error) {
        alert(`失败: ${resp.error}`);
    } else {
        alert(`已重新派发: ${taskId}`);
        loadAll();
    }
}

async function loadRecentTasks() {
    const data = await fetchJSON(`${API_BASE}/tasks/?limit=20`);
    if (data.error) return;
    const tb = document.querySelector('#recent-tasks-table tbody');
    tb.innerHTML = (data.items || []).map(t => `
        <tr>
            <td><a href="/dashboard?task_id=${t.task_id}" onclick="loadTaskDetail('${t.task_id}'); return false;">${t.task_id}</a></td>
            <td>${t.product_name || ''}</td>
            <td>${t.platform || ''}</td>
            <td>${badge(t.status, t.status)}</td>
            <td>${t.retry_count || 0}</td>
            <td>${t.last_failure_reason || '-'}</td>
            <td>${(t.created_at || '').slice(0, 19)}</td>
        </tr>
    `).join('');
}

document.getElementById('submit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
        product_name: fd.get('product_name'),
        target_user: fd.get('target_user'),
        selling_points: (fd.get('selling_points') || '').split(',').map(s => s.trim()).filter(Boolean),
        platform: fd.get('platform'),
        style: fd.get('style'),
        duration: parseInt(fd.get('duration'), 10),
    };
    const resultBox = document.getElementById('submit-result');
    resultBox.className = 'submit-result';
    resultBox.textContent = '提交中 ...';
    const resp = await fetchJSON(`${API_BASE}/tasks/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (resp.error) {
        resultBox.className = 'submit-result error';
        resultBox.textContent = `失败: ${resp.error} - ${resp.detail || ''}`;
    } else {
        resultBox.className = 'submit-result success';
        resultBox.textContent = `✅ 已提交, task_id=${resp.task_id}, trace_id=${resp.trace_id}`;
        loadAll();
    }
});

async function loadAll() {
    await Promise.all([loadOverview(), loadRecentTasks()]);
}

loadAll();
setInterval(loadAll, 10000);  // 10s 刷新
