export const StepOutputCard = {
    props: { step: { type: Object, required: true } },
    template: `
        <div class="card">
            <h3 class="text-sm font-semibold text-slate-300 mb-3">
                {{ step.step_name }} · 输出预览
            </h3>

            <!-- product_analysis -->
            <div v-if="step.step_id === 'product_analysis' && step.output_payload" class="space-y-2 text-sm">
                <div><span class="text-slate-500">痛点:</span> {{ joinOrDash(step.output_payload.pain_points) }}</div>
                <div><span class="text-slate-500">目标用户:</span> {{ joinOrDash(step.output_payload.target_users) }}</div>
                <div><span class="text-slate-500">核心卖点:</span> {{ joinOrDash(step.output_payload.core_selling_points) }}</div>
                <div><span class="text-slate-500">切入角度:</span> {{ step.output_payload.ad_angle || '—' }}</div>
                <div><span class="text-slate-500">目标情绪:</span> {{ step.output_payload.target_emotion || '—' }}</div>
            </div>

            <!-- script_generation -->
            <div v-else-if="step.step_id === 'script_generation' && step.output_payload" class="space-y-2 text-sm">
                <div><span class="text-slate-500">钩子 (3s):</span> {{ step.output_payload.hook || '—' }}</div>
                <div><span class="text-slate-500">痛点:</span> {{ step.output_payload.problem || '—' }}</div>
                <div><span class="text-slate-500">方案:</span> {{ step.output_payload.solution || '—' }}</div>
                <div><span class="text-slate-500">信任:</span> {{ step.output_payload.proof || '—' }}</div>
                <div><span class="text-slate-500">CTA:</span> {{ step.output_payload.cta || '—' }}</div>
            </div>

            <!-- storyboard_planning -->
            <div v-else-if="step.step_id === 'storyboard_planning' && step.output_payload?.storyboard" class="space-y-2 text-sm">
                <div v-if="step.output_payload.storyboard.length === 0" class="text-slate-500">
                    分镜生成失败, 可反馈重生
                </div>
                <div v-else>
                    <div class="flex gap-1 mb-2">
                        <div v-for="sc in step.output_payload.storyboard" :key="sc.scene_id"
                             class="flex-1 text-center text-xs py-1 rounded bg-sky-500/20 text-sky-200 border border-sky-500/30">
                            #{{ sc.scene_id }} · {{ sc.duration }}s
                        </div>
                    </div>
                    <details v-for="sc in step.output_payload.storyboard" :key="sc.scene_id" class="border border-slate-700 rounded p-2">
                        <summary class="cursor-pointer text-slate-300">镜 {{ sc.scene_id }}: {{ sc.visual }}</summary>
                        <div class="mt-2 space-y-1 text-xs text-slate-400">
                            <div>字幕: {{ sc.subtitle }}</div>
                            <div>配音: {{ sc.voiceover }}</div>
                            <div>镜头: {{ sc.camera_shot }} · 类型: {{ sc.material_type }}</div>
                        </div>
                    </details>
                </div>
            </div>

            <!-- material_suggestion -->
            <div v-else-if="step.step_id === 'material_suggestion' && step.output_payload?.materials" class="space-y-1 text-sm">
                <div v-if="step.output_payload.materials.length === 0" class="text-slate-500">
                    素材建议为空
                </div>
                <div v-for="m in step.output_payload.materials" :key="m.scene_id + '-' + m.material_keyword"
                     class="flex items-center gap-2 text-xs">
                    <span class="text-slate-500 w-12">镜 {{ m.scene_id }}</span>
                    <span class="text-slate-300">→</span>
                    <span class="text-sky-300 font-mono">{{ m.material_keyword }}</span>
                    <span class="text-slate-500">({{ m.material_type }})</span>
                </div>
            </div>

            <!-- quality_evaluation -->
            <div v-else-if="step.step_id === 'quality_evaluation' && step.output_payload" class="space-y-2 text-sm">
                <div class="flex items-center gap-3">
                    <span :class="['text-2xl font-bold', scoreColor]">{{ step.output_payload.score ?? '—' }}</span>
                    <span class="text-slate-400">/ 100</span>
                    <span v-if="step.output_payload.passed" class="text-emerald-400">通过</span>
                    <span v-else class="text-rose-400">未通过</span>
                </div>
                <div><span class="text-slate-500">风险:</span> {{ step.output_payload.risk_level || '—' }}</div>
                <div v-if="step.output_payload.issues?.length">
                    <div class="text-slate-500">问题:</div>
                    <ul class="list-disc list-inside text-rose-300 text-xs">
                        <li v-for="(iss, i) in step.output_payload.issues" :key="i">
                            {{ typeof iss === 'string' ? iss : iss.detail }}
                        </li>
                    </ul>
                </div>
                <div v-if="step.output_payload.suggested_fix">
                    <span class="text-slate-500">建议:</span> {{ step.output_payload.suggested_fix }}
                </div>
            </div>

            <!-- fallback / pending -->
            <div v-else class="text-slate-500 text-sm">暂无输出</div>
        </div>
    `,
    methods: {
        joinOrDash(arr) {
            if (!arr || arr.length === 0) return '—';
            return arr.join('、');
        },
    },
    computed: {
        scoreColor() {
            const s = this.step.output_payload?.score;
            if (s == null) return 'text-slate-500';
            if (s >= 80) return 'text-emerald-400';
            if (s >= 60) return 'text-amber-400';
            return 'text-rose-400';
        },
    },
};
