// 简版 hash 路由 + 页面调度器
import ArcoVue from '@arco-design/web-vue';
import '@arco-design/web-vue/dist/arco.css';
import './tailwind.css';
import './style.css';
import { PageShell } from './components/PageShell.js';
import { UserJourneyPage } from './pages/UserJourneyPage.js';
import { TaskListPage } from './pages/TaskListPage.js';
import { SubmitPage } from './pages/SubmitPage.js';
import { TaskDetailPage } from './pages/TaskDetailPage.js';
import { InspirationPage } from './pages/InspirationPage.js';
import { createApp, h } from 'vue';
import { onNetworkChange } from './api.js';

let currentApp = null;

const routes = [
    {
        pattern: /^#\/inspiration\/?$/,
        render: () => h(PageShell, {
            activeTab: 'inspiration',
            title: '灵感广场',
            description: '浏览、筛选并复用经过拆解的商品视频创意。',
        }, { default: () => h(InspirationPage) }),
    },
    {
        pattern: /^#\/submit\/?$/,
        render: () => h(PageShell, {
            activeTab: 'submit',
            title: '新建商品视频项目',
            description: '补充商品和投放信息，生成策略、分镜和成片。',
        }, { default: () => h(SubmitPage) }),
    },
    {
        pattern: /^#\/task\/([^/]+)\/?$/,
        render: (m) => h(PageShell, {
            activeTab: 'user',
            title: '任务详情',
            description: '查看这个任务从输入到产出的全过程，包括每个节点的输出、评分和失败原因。',
        }, { default: () => h(TaskDetailPage, { taskId: m[1] }) }),
    },
    {
        pattern: /^#\/ops\/?$/,
        render: () => h(PageShell, {
            activeTab: 'ops',
            title: '生成任务',
            description: '密集查看任务状态、生成节点、失败定位和重试操作。',
        }, { default: () => h(TaskListPage) }),
    },
    {
        pattern: /^#\/user\/?$/,
        render: () => h(PageShell, {
            activeTab: 'user',
            title: '商品视频工作台',
            description: '上传商品和参考素材，从分析、分镜到成片一次完成。',
        }, { default: () => h(UserJourneyPage) }),
    },
    {
        pattern: /^#\/?$/,
        render: () => h(PageShell, {
            activeTab: 'user',
            title: '商品视频工作台',
            description: '上传商品和参考素材，从分析、分镜到成片一次完成。',
        }, { default: () => h(UserJourneyPage) }),
    },
];

function dispatch() {
    const hash = location.hash || '#/';
    for (const r of routes) {
        const m = hash.match(r.pattern);
        if (m) {
            const view = document.getElementById('view');
            currentApp?.unmount();
            currentApp = createApp({ render: () => r.render(m) });
            currentApp.use(ArcoVue);
            currentApp.mount(view);
            return;
        }
    }
    location.hash = '#/';
}

window.addEventListener('hashchange', dispatch);
dispatch();

const banner = document.createElement('div');
banner.id = 'offline-banner';
banner.className = 'offline-banner';
banner.setAttribute('role', 'status');
banner.setAttribute('aria-live', 'polite');
banner.textContent = '网络连接已中断，恢复后将继续刷新';
document.body.prepend(banner);

onNetworkChange((online) => {
    banner.style.display = online ? 'none' : 'block';
});

window.addEventListener('offline', () => { banner.style.display = 'block'; });
window.addEventListener('online', () => {
    banner.style.display = 'none';
    dispatch();
});
