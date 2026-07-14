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

        const regenerating = ref(false);
        const doneSteps = computed(() => steps.value.filter(s => s.output_payload && s.status === 'success'));

        const scoreColor = computed(() => {
            const s = evalStep.value?.output_payload?.score;
            if (s == null) return 'text-slate-500';
            if (s >= 80) return 'text-emerald-400';
            if (s >= 60) return 'text-amber-400';
            return 'text-rose-400';
        });

        async function regenerateStyle() {
            regenerating.value = true;
            try {
                const { submitTask } = await import('/web/api.js');
                const newStyle = prompt('输入新风格:', 'humor meme ad') || task.value.style;
                const product = {
                    product_name: task.value.product_name,
                    target_user: task.value.target_user || '',
                    selling_points: task.value.selling_points || [],
                    platform: task.value.platform,
                    style: newStyle,
                    duration: task.value.duration,
                    feedback_for_task_id: task.value.task_id,
                    style_override: newStyle,
                };
                const result = await submitTask(product);
                location.hash = '#/task/' + result.task_id;
            } catch (e) {
                showToast('重生失败: ' + e.message, 'error');
            } finally {
                regenerating.value = false;
            }
        }

        async function regenerateWithFeedback() {
            regenerating.value = true;
            try {
                const { submitTask } = await import('/web/api.js');
                const product = {
                    product_name: task.value.product_name,
                    target_user: task.value.target_user || '',
                    selling_points: task.value.selling_points || [],
                    platform: task.value.platform,
                    style: task.value.style,
                    duration: task.value.duration,
                    feedback_for_task_id: task.value.task_id,
                };
                const result = await submitTask(product);
                location.hash = '#/task/' + result.task_id;
            } catch (e) {
                showToast('反馈重生失败: ' + e.message, 'error');
            } finally {
                regenerating.value = false;
            }
        }

        function copyAll() {
            const lines = [];
            lines.push(`# ${task.value.product_name} · ${task.value.platform} · ${task.value.duration}s`);
            for (const s of doneSteps.value) {
                lines.push(`\n## ${s.step_name}`);
                lines.push(JSON.stringify(s.output_payload, null, 2));
            }
            navigator.clipboard.writeText(lines.join('\n'))
                .then(() => showToast('已复制到剪贴板', 'success'))
                .catch(e => showToast('复制失败: ' + e.message, 'error'));
        }

        return {
            task, steps, error, polling, currentStep, banner, isDone, evalStep,
            getCancelPolling,
            doneSteps, scoreColor, regenerating,
            regenerateStyle, regenerateWithFeedback, copyAll,
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

            <div v-if="isDone" class="mt-4 space-y-4">
                <!-- 评分卡 -->
                <div v-if="evalStep" class="card">
                    <div class="flex items-center gap-4">
                        <div :class="['text-4xl font-bold', scoreColor]">
                            {{ evalStep.output_payload.score ?? '—' }}
                        </div>
                        <div class="text-slate-400">/ 100</div>
                        <div class="flex-1">
                            <div class="text-sm">
                                <span v-if="evalStep.output_payload.passed" class="text-emerald-400">✅ 通过</span>
                                <span v-else class="text-rose-400">❌ 未通过</span>
                                <span class="text-slate-500 ml-2">· 风险 {{ evalStep.output_payload.risk_level }}</span>
                            </div>
                            <div v-if="evalStep.output_payload.suggested_fix" class="text-xs text-slate-400 mt-1">
                                改进建议: {{ evalStep.output_payload.suggested_fix }}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 4 张结果卡: 脚本 / 分镜 / 素材 / 评价 -->
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <StepOutputCard v-for="s in doneSteps" :key="s.step_id" :step="s" />
                </div>

                <!-- 操作栏 -->
                <div class="card flex flex-wrap items-center justify-between gap-3">
                    <div class="text-sm text-slate-400">对这个结果满意吗？</div>
                    <div class="flex flex-wrap gap-2">
                        <button @click="regenerateStyle"
                                :disabled="regenerating"
                                class="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-slate-900 rounded text-sm font-medium disabled:opacity-40">
                            🔁 换个风格重生
                        </button>
                        <button @click="regenerateWithFeedback"
                                :disabled="regenerating"
                                class="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-900 rounded text-sm font-medium disabled:opacity-40">
                            💬 反馈重生
                        </button>
                        <button @click="copyAll"
                                class="px-4 py-2 border border-slate-700 hover:bg-slate-800 rounded text-sm text-slate-200">
                            📋 复制全部
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `,
};