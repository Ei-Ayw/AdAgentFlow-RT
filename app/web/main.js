// 简版 hash 路由 + 页面调度器
import { TaskListPage } from '/web/pages/TaskListPage.js';
import { SubmitPage } from '/web/pages/SubmitPage.js';
import { TaskDetailPage } from '/web/pages/TaskDetailPage.js';

const { createApp, h, ref, onMounted, onUnmounted } = Vue;

const routes = [
    { pattern: /^#\/submit\/?$/, render: () => h(SubmitPage) },
    { pattern: /^#\/task\/([^/]+)\/?$/, render: (m) => h(TaskDetailPage, { taskId: m[1] }) },
    { pattern: /^#\/?$/, render: () => h(TaskListPage) },
];

function dispatch() {
    const hash = location.hash || '#/';
    for (const r of routes) {
        const m = hash.match(r.pattern);
        if (m) {
            const view = document.getElementById('view');
            view.innerHTML = '';
            const app = createApp({ render: () => r.render(m) });
            app.mount(view);
            return;
        }
    }
    location.hash = '#/';
}

window.addEventListener('hashchange', dispatch);
window.addEventListener('DOMContentLoaded', dispatch);
dispatch();

import { onNetworkChange } from '/web/api.js';

const banner = document.createElement('div');
banner.id = 'offline-banner';
banner.style.cssText = 'display:none;position:fixed;top:0;left:0;right:0;background:#ef4444;color:white;text-align:center;padding:8px;font-size:14px;z-index:100;';
banner.textContent = '⚠️ 网络中断, 正在尝试恢复…';
document.body.prepend(banner);

onNetworkChange((online) => {
    banner.style.display = online ? 'none' : 'block';
});

window.addEventListener('online', () => location.reload());