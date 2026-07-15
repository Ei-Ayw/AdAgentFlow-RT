import {
    IconCheck,
    IconClockCircle,
    IconClose,
    IconMinus,
    IconRefresh,
} from '@arco-design/web-vue/es/icon';

const STATUS_LABEL = {
    pending: '等待中',
    running: '运行中…',
    success: '已完成',
    failed: '失败',
    retrying: '重试中',
    skipped: '已跳过',
};

export const AgentStepper = {
    components: { IconCheck, IconClockCircle, IconClose, IconMinus, IconRefresh },
    props: { steps: { type: Array, required: true } },
    template: `
        <div class="agent-stepper">
            <div v-for="(s, idx) in steps" :key="s.step_id"
                 data-testid="step-row"
                 :data-step-id="s.step_id"
                 :class="['agent-step', 'is-' + s.status]">
                <span class="agent-step__icon" aria-hidden="true">
                    <IconCheck v-if="s.status === 'success'" />
                    <IconClose v-else-if="s.status === 'failed'" />
                    <IconRefresh v-else-if="s.status === 'running' || s.status === 'retrying'" :class="(s.status === 'running' || s.status === 'retrying') && 'spin'" />
                    <IconMinus v-else-if="s.status === 'skipped'" />
                    <IconClockCircle v-else />
                </span>
                <span class="agent-step__index">{{ String(idx + 1).padStart(2, '0') }}</span>
                <div class="agent-step__body">
                    <div><strong>{{ s.step_name }}</strong><span v-if="s.retry_count > 0">重试 {{ s.retry_count }} 次</span></div>
                    <small v-if="s.error_message">{{ s.error_message }}</small>
                </div>
                <span class="agent-step__status">
                    {{ s.latency_ms && s.status === 'success' ? (s.latency_ms / 1000).toFixed(1) + 's' : STATUS_LABEL[s.status] || s.status }}
                </span>
            </div>
        </div>
    `,
    data() { return { STATUS_LABEL }; },
};
