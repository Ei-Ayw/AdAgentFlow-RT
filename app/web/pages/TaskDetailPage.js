import { ref, computed, onMounted, onUnmounted } from 'vue';
import { pollTaskUntilDone, showToast } from '../api.js';
import { AgentStepper } from '../components/AgentStepper.js';
import { StepOutputCard } from '../components/StepOutputCard.js';
import { StatusBadge } from '../components/StatusBadge.js';

const BANNER = {
    running:     { txt: '生成中…' },
    evaluating:  { txt: '质量评估中…' },
    retrying:    { txt: '重试中…' },
    queued:      { txt: '排队中…' },
    success:     { txt: '生成成功' },
    manual_review: { txt: '请人工审阅' },
    failed:      { txt: '生成失败' },
    dead_letter: { txt: '已多次失败' },
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
            const ctrl = new AbortController();
            cancelPoll = () => {
                ctrl.abort();
                polling.value = false;
            };
            try {
                const { task: t } = await pollTaskUntilDone(props.taskId, {
                    signal: ctrl.signal,
                    onUpdate(latest) {
                        task.value = latest;
                        steps.value = latest.steps || [];
                    },
                });
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
        const finalOutput = computed(() => steps.value.find(s => s.step_id === 'composition')?.output_payload || null);

        const regenerating = ref(false);
        const doneSteps = computed(() => steps.value.filter(s => s.output_payload && s.status === 'success'));

        const scoreColor = computed(() => {
            const s = evalStep.value?.output_payload?.score;
            if (s == null) return 'text-slate-500';
            if (s >= 80) return 'is-strong';
            if (s >= 60) return 'is-mid';
            return 'is-low';
        });

        async function regenerateStyle() {
            regenerating.value = true;
            try {
                const { submitTask } = await import('../api.js');
                const newStyle = prompt('输入新风格:', 'humor meme ad') || task.value.style;
                const product = {
                    product_name: task.value.product_name,
                    target_user: task.value.target_user || '',
                    selling_points: task.value.selling_points || [],
                    platform: task.value.platform,
                    style: newStyle,
                    duration: task.value.duration,
                    product_assets: task.value.product_assets || [],
                    reference_video: task.value.reference_video || null,
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
                const { submitTask } = await import('../api.js');
                const product = {
                    product_name: task.value.product_name,
                    target_user: task.value.target_user || '',
                    selling_points: task.value.selling_points || [],
                    platform: task.value.platform,
                    style: task.value.style,
                    duration: task.value.duration,
                    product_assets: task.value.product_assets || [],
                    reference_video: task.value.reference_video || null,
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
            task, steps, error, polling, currentStep, banner, isDone, evalStep, finalOutput,
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

            <div :class="['task-status-banner', 'is-' + task.status]">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <StatusBadge :status="task.status" />
                        <span>{{ banner.txt }}</span>
                        <span v-if="task.retry_count > 0" class="text-xs">· 重试 {{ task.retry_count }} 次</span>
                    </div>
                    <button v-if="polling" @click="getCancelPolling()?.()"
                            class="min-h-11 px-2 text-xs text-slate-300 hover:text-white">
                        取消轮询
                    </button>
                </div>
                <div v-if="task.last_failure_reason" class="task-status-banner__reason">
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
                <div v-if="finalOutput?.final_video_url" class="card production-result">
                    <div class="production-result__head">
                        <div><span>FINAL OUTPUT</span><h3>成片已完成</h3></div>
                        <a :href="finalOutput.final_video_url" download>下载 MP4</a>
                    </div>
                    <video controls playsinline :poster="finalOutput.poster_url || ''" :src="finalOutput.final_video_url"></video>
                    <div class="production-result__meta"><span>{{ finalOutput.format }} · {{ finalOutput.codec }}</span><span>{{ finalOutput.duration_seconds }} 秒</span><span>{{ Math.round((finalOutput.size_bytes || 0) / 1024) }} KB</span></div>
                </div>

                <!-- 评分卡 -->
                <div v-if="evalStep" class="card">
                    <div class="flex items-center gap-4">
                        <div :class="['task-score', scoreColor]">
                            {{ evalStep.output_payload.score ?? '—' }}
                        </div>
                        <div class="text-slate-400">/ 100</div>
                        <div class="flex-1">
                            <div class="text-sm">
                                <span v-if="evalStep.output_payload.passed" class="text-emerald-400">通过</span>
                                <span v-else class="text-rose-400">未通过</span>
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
                                class="task-action is-primary">
                            换个风格重生
                        </button>
                        <button @click="regenerateWithFeedback"
                                :disabled="regenerating"
                                class="task-action">
                            反馈重生
                        </button>
                        <button @click="copyAll"
                                class="task-action">
                            复制全部
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `,
};
