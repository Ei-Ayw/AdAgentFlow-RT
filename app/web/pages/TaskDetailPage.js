import { ref, computed, onMounted, onUnmounted } from 'vue';
import { pollTaskUntilDone, fetchTask, showToast } from '/web/api.js';
import { AgentStepper } from '/web/components/AgentStepper.js';
import { StepOutputCard } from '/web/components/StepOutputCard.js';
import { StatusBadge } from '/web/components/StatusBadge.js';

const BANNER = {
    running:     { txt: '生成中…', cls: 'bg-sky-500/20 border-sky-500/40 text-sky-200' },
    evaluating:  { txt: '质量评估中…', cls: 'bg-violet-500/20 border-violet-500/40 text-violet-200' },
    retrying:    { txt: '重试中…', cls: 'bg-amber-500/20 border-amber-500/40 text-amber-200' },
    queued:      { txt: '排队中…', cls: 'bg-slate-500/20 border-slate-500/40 text-slate-200' },
    success:     { txt: '生成成功', cls: 'bg-emerald-500/20 border-emerald-500/40 text-emerald-200' },
    manual_review: { txt: '请人工审阅', cls: 'bg-amber-500/20 border-amber-500/40 text-amber-200' },
    failed:      { txt: '生成失败', cls: 'bg-rose-500/20 border-rose-500/40 text-rose-200' },
    dead_letter: { txt: '已多次失败', cls: 'bg-rose-700/30 border-rose-700/60 text-rose-200' },
};

export const TaskDetailPage = {
    components: { AgentStepper, StepOutputCard, StatusBadge },
    props: { taskId: { type: String, required: true } },
    setup(props) {
        const task = ref(null);
        const steps = ref([]);
        const error = ref(null);
        const polling = ref(true);
        let cancelPoll = null;

        function getCancelPolling() {
            return cancelPoll;
        }

        async function startPolling() {
            cancelPoll = null;
            const ctrl = new AbortController();
            cancelPoll = () => ctrl.abort();
            try {
                const { task: t } = await pollTaskUntilDone(props.taskId);
                task.value = t;
                steps.value = t.steps || [];
            } catch (e) {
                if (e.name !== 'AbortError') {
                    error.value = e.message;
                    showToast('轮询失败: ' + e.message, 'error');
                }
            } finally {
                polling.value = false;
            }
        }

        onMounted(() => { startPolling(); });
        onUnmounted(() => { if (cancelPoll) cancelPoll(); });

        const currentStep = computed(() => {
            return steps.value.find(s => s.status === 'running')
                || steps.value.find(s => s.status === 'failed' && s.error_message)
                || steps.value[steps.value.length - 1];
        });

        const banner = computed(() => BANNER[task.value?.status] || BANNER.queued);
        const isDone = computed(() => task.value && ['success','failed','dead_letter','manual_review'].includes(task.value.status));
        const evalStep = computed(() => steps.value.find(s => s.step_id === 'quality_evaluation' && s.output_payload));

        return {
            task, steps, error, polling, currentStep, banner, isDone, evalStep,
        };
    },
    template: `
        <div v-if="error" class="card text-center py-12">
            <p class="text-rose-400 mb-4">{{ error }}</p>
            <a href="#/" class="text-sky-400">← 返回列表</a>
        </div>

        <div v-else-if="!task" class="card text-center py-12">
            <p class="text-slate-400">加载中…</p>
        </div>

        <div v-else>
            <div class="flex items-center gap-3 mb-4">
                <a href="#/" class="text-slate-400 hover:text-slate-200">← 返回</a>
                <h2 class="text-xl font-semibold">
                    {{ task.product_name }} · {{ task.platform }} · {{ task.duration }}s
                </h2>
            </div>

            <div :class="['border rounded p-3 mb-4 text-sm', banner.cls]">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <StatusBadge :status="task.status" />
                        <span>{{ banner.txt }}</span>
                        <span v-if="task.retry_count > 0" class="text-xs">· 重试 {{ task.retry_count }} 次</span>
                    </div>
                    <button v-if="polling" @click="polling = false; if (getCancelPolling()) getCancelPolling()"
                            class="text-xs text-slate-400 hover:text-slate-200">
                        取消轮询
                    </button>
                </div>
                <div v-if="task.last_failure_reason" class="text-xs mt-1">
                    失败原因: {{ task.last_failure_reason }}
                </div>
            </div>

            <div class="card">
                <h3 class="font-semibold text-slate-200 mb-3">▣ Agent 进度</h3>
                <AgentStepper :steps="steps" />
            </div>

            <div v-if="currentStep" class="mt-4">
                <StepOutputCard :step="currentStep" />
            </div>

            <div v-if="isDone" class="mt-4">
                <div class="card">
                    <h3 class="font-semibold text-slate-200 mb-3">▣ 最终结果</h3>
                    <p class="text-slate-400 text-sm mb-3">
                        任务已完成, 下方为各节点输出。完整结果按节点分类, 可单独复制。
                    </p>
                    <div class="flex gap-2">
                        <a :href="'/dashboard/trace.html?task_id=' + taskId"
                           target="_blank" class="text-sky-400 text-sm hover:underline">
                            📊 查看完整 Trace 时间线 →
                        </a>
                    </div>
                </div>
            </div>
        </div>
    `,
};
