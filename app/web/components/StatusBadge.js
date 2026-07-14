const STATUS_MAP = {
    success: { label: '成功', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' },
    failed: { label: '失败', cls: 'bg-rose-500/20 text-rose-300 border-rose-500/40' },
    running: { label: '运行中', cls: 'bg-sky-500/20 text-sky-300 border-sky-500/40' },
    pending: { label: '等待中', cls: 'bg-slate-500/20 text-slate-300 border-slate-500/40' },
    retrying: { label: '重试中', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/40' },
    evaluating: { label: '评估中', cls: 'bg-violet-500/20 text-violet-300 border-violet-500/40' },
    queued: { label: '排队中', cls: 'bg-slate-500/20 text-slate-300 border-slate-500/40' },
    dead_letter: { label: '死信', cls: 'bg-rose-700/30 text-rose-200 border-rose-700/60' },
    manual_review: { label: '需审核', cls: 'bg-amber-500/20 text-amber-200 border-amber-500/40' },
    skipped: { label: '已跳过', cls: 'bg-slate-600/20 text-slate-400 border-slate-600/40' },
};

export const StatusBadge = {
    props: { status: { type: String, required: true } },
    template: `
        <span :class="['inline-flex items-center px-2 py-0.5 text-xs rounded border', meta.cls]">
            {{ meta.label }}
        </span>
    `,
    computed: {
        meta() {
            return STATUS_MAP[this.status] || {
                label: this.status,
                cls: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
            };
        },
    },
};
