import { StatusBadge } from './StatusBadge.js';

const fmtTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { hour12: false });
};

export const TaskCard = {
    components: { StatusBadge },
    props: { task: { type: Object, required: true } },
    template: `
        <a :href="'#/task/' + task.task_id"
           class="block card hover:border-sky-500/50 transition-colors">
            <div class="flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        <h3 class="font-medium text-slate-100 truncate">{{ task.product_name }}</h3>
                        <span class="text-xs text-slate-400">· {{ task.platform }} · {{ task.duration }}s</span>
                    </div>
                    <div class="flex items-center gap-2 text-sm text-slate-400 mb-2">
                        <StatusBadge :status="task.status" />
                        <span v-if="task.retry_count > 0">· 重试 {{ task.retry_count }} 次</span>
                        <span v-if="task.last_failure_reason">· 失败: {{ task.last_failure_reason }}</span>
                    </div>
                    <div class="text-xs text-slate-500 font-mono">
                        {{ task.task_id }} · {{ fmtTime(task.created_at) }}
                    </div>
                </div>
                <span class="text-sky-400 text-sm shrink-0">查看 →</span>
            </div>
        </a>
    `,
    methods: { fmtTime },
};
