import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { listTasks, isTerminal, showToast } from '/web/api.js';
import { TaskCard } from '/web/components/TaskCard.js';

export const TaskListPage = {
    components: { TaskCard },
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

        async function load() {
            loading.value = true;
            try {
                const params = { limit, offset: offset.value };
                if (statusFilter.value) params.status = statusFilter.value;
                const data = await listTasks(params);
                let items = data.items || [];
                if (search.value) {
                    const s = search.value.toLowerCase();
                    items = items.filter(t =>
                        t.product_name?.toLowerCase().includes(s) ||
                        t.task_id?.toLowerCase().includes(s)
                    );
                }
                tasks.value = items;
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
        watch([statusFilter, search], () => { offset.value = 0; load(); });
        watch(offset, load);

        onMounted(() => { load(); startPolling(); });
        onUnmounted(stopPolling);

        return {
            tasks, total, statusFilter, search, offset, limit, loading,
            hasActive, load,
            STATUSES: ['', 'queued', 'running', 'evaluating', 'retrying', 'success', 'failed', 'dead_letter', 'manual_review'],
        };
    },
    template: `
        <div>
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-xl font-semibold">我的广告任务</h2>
                <a href="#/submit" class="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-slate-900 rounded font-medium text-sm">
                    + 提交新任务
                </a>
            </div>

            <div class="card flex flex-wrap items-center gap-3">
                <label class="text-sm text-slate-400">状态:</label>
                <select v-model="statusFilter" class="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm">
                    <option v-for="s in STATUSES" :key="s" :value="s">{{ s || '全部' }}</option>
                </select>
                <input v-model="search" type="text" placeholder="搜索 task_id / 商品名"
                       class="flex-1 min-w-[200px] bg-slate-800 border border-slate-700 rounded px-3 py-1 text-sm" />
                <span class="text-xs text-slate-500">共 {{ total }} 条</span>
                <span v-if="hasActive" class="text-xs text-sky-400 animate-pulse">● 自动刷新中</span>
            </div>

            <div v-if="tasks.length === 0 && !loading" class="card text-center py-12">
                <div class="text-5xl mb-3">📭</div>
                <p class="text-slate-400 mb-4">还没有任务</p>
                <a href="#/submit" class="text-sky-400 hover:underline">立即创建 →</a>
            </div>

            <div v-else class="space-y-3">
                <TaskCard v-for="t in tasks" :key="t.task_id" :task="t" />
            </div>

            <div v-if="total > limit" class="flex justify-center gap-2 mt-4 text-sm">
                <button :disabled="offset === 0" @click="offset = Math.max(0, offset - limit)"
                        class="px-3 py-1 bg-slate-800 border border-slate-700 rounded disabled:opacity-40">
                    ← 上一页
                </button>
                <span class="px-3 py-1 text-slate-400">{{ offset / limit + 1 }} / {{ Math.ceil(total / limit) }}</span>
                <button :disabled="offset + limit >= total" @click="offset = offset + limit"
                        class="px-3 py-1 bg-slate-800 border border-slate-700 rounded disabled:opacity-40">
                    下一页 →
                </button>
            </div>
        </div>
    `,
};