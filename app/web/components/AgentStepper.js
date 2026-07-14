const ICON = {
    pending: { icon: '○', cls: 'text-slate-500 border-slate-600' },
    running: { icon: '⟳', cls: 'text-sky-400 border-sky-500 animate-spin' },
    success: { icon: '✓', cls: 'text-emerald-400 border-emerald-500' },
    failed: { icon: '✗', cls: 'text-rose-400 border-rose-500' },
    retrying: { icon: '⟳', cls: 'text-amber-400 border-amber-500 animate-spin' },
    skipped: { icon: '—', cls: 'text-slate-600 border-slate-700' },
};

const STATUS_LABEL = {
    pending: '等待中',
    running: '运行中…',
    success: '',
    failed: '失败',
    retrying: '重试中',
    skipped: '已跳过',
};

export const AgentStepper = {
    props: {
        steps: { type: Array, required: true },
    },
    template: `
        <div class="space-y-2">
            <div v-for="(s, idx) in steps" :key="s.step_id"
                 :data-testid="'step-row'"
                 :data-step-id="s.step_id"
                 class="flex items-center gap-3 p-3 rounded border border-slate-700 bg-slate-800/50">
                <div :class="['w-7 h-7 rounded-full border-2 flex items-center justify-center font-bold', iconOf(s).cls]">
                    {{ iconOf(s).icon }}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 text-sm">
                        <span class="text-slate-400">{{ idx + 1 }}.</span>
                        <span class="text-slate-100">{{ s.step_name }}</span>
                        <span v-if="s.retry_count > 0" class="text-xs text-amber-400">
                            (重试 {{ s.retry_count }} 次)
                        </span>
                    </div>
                    <div v-if="s.error_message" class="text-xs text-rose-400 mt-1 truncate">
                        {{ s.error_message }}
                    </div>
                </div>
                <div class="text-xs text-slate-500 shrink-0">
                    <span v-if="s.status === 'running'">{{ STATUS_LABEL[s.status] }}</span>
                    <span v-else-if="s.latency_ms">{{ (s.latency_ms / 1000).toFixed(1) }}s</span>
                    <span v-else-if="s.status === 'pending'">等待中</span>
                </div>
            </div>
        </div>
    `,
    methods: {
        iconOf(s) {
            return ICON[s.status] || ICON.pending;
        },
    },
};
