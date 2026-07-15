const STATUS_MAP = {
    success: { label: '成功', cls: 'is-success' },
    failed: { label: '失败', cls: 'is-failed' },
    running: { label: '运行中', cls: 'is-running' },
    pending: { label: '等待中', cls: 'is-pending' },
    retrying: { label: '重试中', cls: 'is-retrying' },
    evaluating: { label: '评估中', cls: 'is-evaluating' },
    queued: { label: '排队中', cls: 'is-queued' },
    dead_letter: { label: '死信', cls: 'is-dead-letter' },
    manual_review: { label: '需审核', cls: 'is-manual-review' },
    skipped: { label: '已跳过', cls: 'is-skipped' },
};

export const StatusBadge = {
    props: { status: { type: String, required: true } },
    template: `
        <span :class="['status-badge', meta.cls]">
            {{ meta.label }}
        </span>
    `,
    computed: {
        meta() {
            return STATUS_MAP[this.status] || {
                label: this.status,
                cls: 'is-unknown',
            };
        },
    },
};
