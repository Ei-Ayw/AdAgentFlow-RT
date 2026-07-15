import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { listTasks, isTerminal, showToast } from '../api.js';
import { StatusBadge } from '../components/StatusBadge.js';

const STATUS_LABELS = {
    queued: '排队中',
    running: '运行中',
    evaluating: '评估中',
    retrying: '重试中',
    success: '成功',
    failed: '失败',
    dead_letter: '死信',
    manual_review: '需审核',
};

const fmtTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { hour12: false });
};

export const TaskListPage = {
    components: { StatusBadge },
    setup() {
        const tasks = ref([]);
        const total = ref(0);
        const statusFilter = ref('');
        const search = ref('');
        const offset = ref(0);
        const limit = 20;
        const loading = ref(false);
        let pollTimer = null;

        const hasActive = computed(() =>
            tasks.value.some(t => !isTerminal(t.status))
        );

        const visibleTasks = computed(() => {
            const needle = search.value.trim().toLowerCase();
            if (!needle) return tasks.value;
            return tasks.value.filter(t =>
                t.product_name?.toLowerCase().includes(needle) ||
                t.task_id?.toLowerCase().includes(needle) ||
                t.platform?.toLowerCase().includes(needle)
            );
        });

        const activeCount = computed(() => tasks.value.filter(t => !isTerminal(t.status)).length);
        const failedCount = computed(() => tasks.value.filter(t => ['failed', 'dead_letter'].includes(t.status)).length);
        const successCount = computed(() => tasks.value.filter(t => t.status === 'success').length);
        const retryingCount = computed(() => tasks.value.filter(t => t.status === 'retrying').length);

        async function load() {
            loading.value = true;
            try {
                const params = { limit, offset: offset.value };
                if (statusFilter.value) params.status = statusFilter.value;
                const data = await listTasks(params);
                tasks.value = data.items || [];
                total.value = data.total;
            } catch (e) {
                showToast('加载任务失败: ' + e.message, 'error');
            } finally {
                loading.value = false;
            }
        }

        function startPolling() {
            stopPolling();
            if (hasActive.value) {
                pollTimer = setInterval(() => {
                    if (hasActive.value) load();
                    else stopPolling();
                }, 5000);
            }
        }

        function stopPolling() {
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        }

        watch(hasActive, (v) => { if (v) startPolling(); else stopPolling(); });
        watch(statusFilter, () => { offset.value = 0; load(); });
        watch(offset, load);

        onMounted(load);
        onUnmounted(stopPolling);

        return {
            tasks, visibleTasks, total, statusFilter, search, offset, limit, loading,
            hasActive, load, activeCount, failedCount, successCount, retryingCount,
            STATUS_LABELS,
            fmtTime,
            STATUSES: [
                { value: '', label: '全部状态' },
                { value: 'queued', label: '排队中' },
                { value: 'running', label: '运行中' },
                { value: 'evaluating', label: '评估中' },
                { value: 'retrying', label: '重试中' },
                { value: 'success', label: '成功' },
                { value: 'failed', label: '失败' },
                { value: 'dead_letter', label: '死信' },
                { value: 'manual_review', label: '需审核' },
            ],
        };
    },
    template: `
        <div class="space-y-4">
            <a-card class="ops-panel" :bordered="false">
                <div class="flex flex-wrap items-start justify-between gap-4">
                    <div class="max-w-2xl">
                        <div class="text-xs uppercase tracking-[0.28em] text-slate-500">运维视图</div>
                        <h2 class="mt-2 text-2xl font-semibold tracking-[-0.03em]">密集控制台</h2>
                        <p class="mt-2 text-slate-400 leading-6">
                            这里保留状态、筛选、重试和失败定位。布局更紧凑，目的是让你在更少滚动里看到更多信息。
                        </p>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        <a-button href="#/user">切回用户视角</a-button>
                        <a-button type="primary" href="#/submit">提交新任务</a-button>
                    </div>
                </div>
            </a-card>

            <a-card class="panel-card" :bordered="false">
                <div class="metric-strip">
                    <div class="metric">
                        <div class="metric__label">当前页任务</div>
                        <div class="metric__value">{{ tasks.length }}</div>
                        <div class="metric__note">总数 {{ total }}</div>
                    </div>
                    <div class="metric">
                        <div class="metric__label">活跃中</div>
                        <div class="metric__value">{{ activeCount }}</div>
                        <div class="metric__note">会自动轮询刷新</div>
                    </div>
                    <div class="metric">
                        <div class="metric__label">成功 / 重试</div>
                        <div class="metric__value">{{ successCount }} / {{ retryingCount }}</div>
                        <div class="metric__note">已完成与修复中的任务</div>
                    </div>
                    <div class="metric">
                        <div class="metric__label">失败</div>
                        <div class="metric__value">{{ failedCount }}</div>
                        <div class="metric__note">含 failed 与 dead_letter</div>
                    </div>
                </div>
            </a-card>

            <a-card class="panel-card" :bordered="false">
                <div class="flex flex-wrap items-center gap-3">
                    <a-select v-model="statusFilter" :options="STATUSES" class="min-w-[180px]" placeholder="筛选状态" />
                    <a-input-search v-model="search" allow-clear placeholder="搜索任务编号、商品名、平台" class="min-w-[240px] flex-1" />
                    <a-button @click="load" :loading="loading">刷新</a-button>
                    <span class="text-xs text-slate-500">共 {{ total }} 条，当前页 {{ visibleTasks.length }} 条</span>
                    <span v-if="hasActive" class="text-xs text-slate-300">自动刷新中</span>
                </div>
            </a-card>

            <div v-if="loading && tasks.length === 0" class="space-y-2" aria-label="正在加载任务">
                <a-card v-for="i in 3" :key="i" class="dense-row" :bordered="false">
                    <div class="h-12 animate-pulse rounded bg-white/5"></div>
                </a-card>
            </div>

            <div v-else-if="visibleTasks.length === 0" class="card text-center py-12">
                <p class="text-slate-300 font-medium mb-2">{{ search ? '没有匹配的任务' : '还没有任务' }}</p>
                <p v-if="search" class="text-sm text-slate-500 mb-4">试试其他关键词，搜索范围为当前页。</p>
                <a-button type="primary" href="#/submit">立即创建</a-button>
            </div>

            <div v-else class="dense-list">
                <a-card v-for="t in visibleTasks" :key="t.task_id" class="dense-row" :bordered="false">
                    <div class="dense-row__grid">
                        <div>
                            <div class="dense-row__title">{{ t.product_name }}</div>
                            <div class="dense-row__meta">
                                {{ t.task_id }} · {{ t.platform }} · {{ t.duration }}s · {{ fmtTime(t.created_at) }}
                            </div>
                        </div>

                        <div class="dense-row__pillset">
                            <StatusBadge :status="t.status" />
                            <a-tag color="gray" :bordered="false">{{ STATUS_LABELS[t.status] || t.status }}</a-tag>
                            <a-tag color="gray" :bordered="false" v-if="t.retry_count > 0">重试 {{ t.retry_count }}</a-tag>
                            <a-tag color="gray" :bordered="false" v-if="t.last_failure_reason">失败原因已记录</a-tag>
                        </div>

                        <div class="dense-row__actions">
                            <a-button size="small" type="outline" :href="'#/task/' + t.task_id">查看</a-button>
                        </div>
                    </div>
                </a-card>
            </div>

            <div v-if="total > limit" class="flex justify-center gap-2 pt-2">
                <a-button :disabled="offset === 0" @click="offset = Math.max(0, offset - limit)">上一页</a-button>
                <div class="px-3 py-2 text-sm text-slate-400">
                    {{ offset / limit + 1 }} / {{ Math.ceil(total / limit) }}
                </div>
                <a-button :disabled="offset + limit >= total" @click="offset = offset + limit">下一页</a-button>
            </div>
        </div>
    `,
};
