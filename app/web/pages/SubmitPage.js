import { ref, computed } from 'vue';
import { submitTask, showToast } from '/web/api.js';

const STYLES = [
    'dramatic before-after ad',
    'humor meme ad',
    'testimonial review ad',
    'lifestyle cinematic ad',
    'problem-solution demo ad',
    'creator UGC raw ad',
];

const PLATFORMS = ['TikTok', 'Instagram', 'YouTube Shorts'];

const TPL = [
    '<div>',
    '<div class="flex items-center gap-3 mb-4">',
    '<a href="#/" class="text-slate-400 hover:text-slate-200">← 返回</a>',
    '<h2 class="text-xl font-semibold">提交新广告任务</h2>',
    '</div>',
    '<form @submit.prevent="onSubmit" class="space-y-4">',
    '<div class="card">',
    '<h3 class="font-semibold text-slate-200 mb-3">Step 1 · 商品信息</h3>',
    '<div class="space-y-3">',
    '<div>',
    '<label class="text-sm text-slate-400">商品名称 *</label>',
    '<input v-model="productName" type="text" class="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 mt-1" :class="errors.product_name && \'border-rose-500\'" />',
    '<div v-if="errors.product_name" class="text-rose-400 text-xs mt-1">{{ errors.product_name }}</div>',
    '</div>',
    '<div>',
    '<label class="text-sm text-slate-400">目标用户 (选填)</label>',
    '<input v-model="targetUser" type="text" class="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 mt-1" />',
    '</div>',
    '<div>',
    '<label class="text-sm text-slate-400">核心卖点 * ({{ sellingPoints.length }} 个)</label>',
    '<div v-for="(p, i) in sellingPoints" :key="i" class="flex gap-2 mt-1">',
    '<input v-model="sellingPoints[i]" type="text" class="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2" />',
    '<button type="button" @click="removePoint(i)" :disabled="sellingPoints.length === 1" class="px-3 text-slate-400 hover:text-rose-400 disabled:opacity-30">×</button>',
    '</div>',
    '<button type="button" @click="addPoint" class="mt-2 text-sm text-sky-400 hover:underline">+ 添加卖点</button>',
    '<div v-if="errors.selling_points" class="text-rose-400 text-xs mt-1">{{ errors.selling_points }}</div>',
    '</div>',
    '</div>',
    '</div>',
    '<div class="card">',
    '<h3 class="font-semibold text-slate-200 mb-3">Step 2 · 投放参数</h3>',
    '<div class="grid grid-cols-1 md:grid-cols-3 gap-3">',
    '<div>',
    '<label class="text-sm text-slate-400">平台</label>',
    '<div class="flex gap-3 mt-1">',
    '<label v-for="p in PLATFORMS" :key="p" class="flex items-center gap-1 text-sm">',
    '<input type="radio" :value="p" v-model="platform" class="accent-sky-500" /> {{ p }}',
    '</label>',
    '</div>',
    '</div>',
    '<div>',
    '<label class="text-sm text-slate-400">风格</label>',
    '<select v-model="style" class="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 mt-1 text-sm">',
    '<option v-for="s in STYLES" :key="s" :value="s">{{ s }}</option>',
    '</select>',
    '</div>',
    '<div>',
    '<label class="text-sm text-slate-400">时长: {{ duration }}s</label>',
    '<input v-model.number="duration" type="range" min="5" max="60" class="w-full mt-2 accent-sky-500" />',
    '</div>',
    '</div>',
    '</div>',
    '<div class="flex justify-end gap-2">',
    '<a href="#/" class="px-4 py-2 border border-slate-700 rounded text-slate-300 hover:bg-slate-800">取消</a>',
    '<button type="submit" :disabled="!canSubmit || submitting" class="px-6 py-2 bg-sky-500 hover:bg-sky-400 text-slate-900 rounded font-medium disabled:opacity-40">{{ submitting ? \'提交中…\' : \'提交并生成 →\' }}</button>',
    '</div>',
    '</form>',
    '</div>',
].join('\n');

export const SubmitPage = {
    setup() {
        const productName = ref('');
        const targetUser = ref('');
        const sellingPoints = ref(['']);
        const platform = ref('TikTok');
        const style = ref(STYLES[0]);
        const duration = ref(15);
        const submitting = ref(false);
        const errors = ref({});

        const canSubmit = computed(() => {
            return productName.value.trim()
                && sellingPoints.value.some(p => p.trim());
        });

        function addPoint() {
            sellingPoints.value.push('');
        }
        function removePoint(i) {
            if (sellingPoints.value.length > 1) {
                sellingPoints.value.splice(i, 1);
            }
        }

        async function onSubmit() {
            errors.value = {};
            if (!productName.value.trim()) errors.value.product_name = '请填写商品名称';
            const points = sellingPoints.value.map(p => p.trim()).filter(Boolean);
            if (points.length === 0) errors.value.selling_points = '至少 1 个卖点';
            if (Object.keys(errors.value).length) return;

            submitting.value = true;
            try {
                const result = await submitTask({
                    product_name: productName.value.trim(),
                    target_user: targetUser.value.trim(),
                    selling_points: points,
                    platform: platform.value,
                    style: style.value,
                    duration: duration.value,
                });
                localStorage.setItem('recent_task_id', result.task_id);
                location.hash = '#/task/' + result.task_id;
            } catch (e) {
                showToast('提交失败: ' + e.message, 'error');
            } finally {
                submitting.value = false;
            }
        }

        return {
            productName, targetUser, sellingPoints, platform, style, duration,
            submitting, errors, canSubmit,
            STYLES, PLATFORMS,
            addPoint, removePoint, onSubmit,
        };
    },
    template: TPL,
};