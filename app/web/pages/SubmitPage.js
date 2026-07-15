import { computed, ref } from 'vue';
import {
    IconCheck,
    IconClose,
    IconFileVideo,
    IconLoading,
    IconPlus,
    IconRefresh,
    IconSend,
    IconUpload,
} from '@arco-design/web-vue/es/icon';
import { showToast, submitTask, uploadAsset } from '../api.js';
import demoDetail from '../assets/studio/headphones-detail.jpg';
import demoHero from '../assets/studio/headphones-hero.jpg';

export const AD_STYLES = [
    { value: 'dramatic before-after ad', label: '前后对比 · 强转化' },
    { value: 'humor meme ad', label: '幽默梗图 · 高传播' },
    { value: 'testimonial review ad', label: '真人测评 · 强信任' },
    { value: 'lifestyle cinematic ad', label: '生活方式 · 电影感' },
    { value: 'problem-solution demo ad', label: '痛点解决 · 产品演示' },
    { value: 'creator UGC raw ad', label: '达人 UGC · 原生感' },
];

export const PLATFORMS = [
    { value: 'TikTok', label: 'TikTok Shop' },
    { value: 'Instagram', label: 'Instagram Reels' },
    { value: 'YouTube Shorts', label: 'YouTube Shorts' },
];

function makeRequestKey() {
    return globalThis.crypto?.randomUUID?.() || `request-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export const SubmitPage = {
    components: { IconCheck, IconClose, IconFileVideo, IconLoading, IconPlus, IconRefresh, IconSend, IconUpload },
    setup() {
        const productName = ref('');
        const targetUser = ref('城市通勤人群，22–35 岁');
        const sellingPoints = ref(['']);
        const platform = ref('TikTok');
        const style = ref(AD_STYLES[3].value);
        const duration = ref(20);
        const productAssets = ref([]);
        const referenceVideo = ref(null);
        const uploadingCount = ref(0);
        const submitting = ref(false);
        const dragActive = ref(false);
        const errors = ref({});
        const requestKey = ref(makeRequestKey());
        const appliedInspiration = ref('');

        try {
            const rawTemplate = localStorage.getItem('inspiration_template');
            if (rawTemplate) {
                const template = JSON.parse(rawTemplate);
                appliedInspiration.value = template.title || '';
                targetUser.value = template.targetUser || targetUser.value;
                sellingPoints.value = [template.sellingPoint || ''];
                platform.value = PLATFORMS.some((item) => item.value === template.platform) ? template.platform : platform.value;
                style.value = AD_STYLES.some((item) => item.value === template.style) ? template.style : style.value;
                duration.value = [15, 20, 30, 45].includes(template.duration) ? template.duration : duration.value;
                localStorage.removeItem('inspiration_template');
            }
        } catch {
            localStorage.removeItem('inspiration_template');
        }

        const canSubmit = computed(() => productName.value.trim()
            && sellingPoints.value.some((point) => point.trim())
            && productAssets.value.length > 0
            && uploadingCount.value === 0);

        function addPoint() {
            if (sellingPoints.value.length < 6) sellingPoints.value.push('');
        }

        function removePoint(index) {
            if (sellingPoints.value.length > 1) sellingPoints.value.splice(index, 1);
        }

        function removeAsset(index) {
            productAssets.value.splice(index, 1);
        }

        async function uploadProductFiles(fileList) {
            const remaining = Math.max(0, 12 - productAssets.value.length);
            const files = Array.from(fileList || []).slice(0, remaining);
            if (!files.length) return;
            errors.value = { ...errors.value, product_assets: '' };
            uploadingCount.value += files.length;
            const results = await Promise.allSettled(files.map((file) => uploadAsset(file, 'product')));
            uploadingCount.value -= files.length;
            productAssets.value.push(...results.filter((result) => result.status === 'fulfilled').map((result) => result.value));
            const failed = results.find((result) => result.status === 'rejected');
            if (failed) {
                errors.value.product_assets = failed.reason?.message || '素材上传失败';
                showToast('部分素材上传失败，请检查格式或大小', 'error');
            }
        }

        async function addProductFiles(event) {
            const input = event.target;
            const files = input.files;
            input.value = '';
            await uploadProductFiles(files);
        }

        async function onDrop(event) {
            dragActive.value = false;
            await uploadProductFiles(event.dataTransfer?.files);
        }

        async function addReferenceVideo(event) {
            const input = event.target;
            const file = input.files?.[0];
            input.value = '';
            if (!file) return;
            uploadingCount.value += 1;
            try {
                referenceVideo.value = await uploadAsset(file, 'reference');
            } catch (error) {
                showToast(error.message || '参考视频上传失败', 'error');
            } finally {
                uploadingCount.value -= 1;
            }
        }

        function loadDemo() {
            productName.value = 'Aero One 无线降噪耳机';
            targetUser.value = '城市通勤与轻办公人群，22–35 岁';
            sellingPoints.value = ['全天候舒适佩戴', '通勤场景主动降噪', '30 小时续航'];
            productAssets.value = [
                { asset_id: 'demo-hero', name: 'aero-one-front.jpg', url: demoHero, kind: 'product' },
                { asset_id: 'demo-detail', name: 'aero-one-detail.jpg', url: demoDetail, kind: 'product' },
            ];
            referenceVideo.value = null;
            errors.value = {};
        }

        async function onSubmit() {
            const points = sellingPoints.value.map((point) => point.trim()).filter(Boolean);
            const nextErrors = {};
            if (!productName.value.trim()) nextErrors.product_name = '请填写商品名称';
            if (!productAssets.value.length) nextErrors.product_assets = '请至少上传 1 张商品图片';
            if (!points.length) nextErrors.selling_points = '请至少填写 1 个核心卖点';
            errors.value = nextErrors;
            if (Object.keys(nextErrors).length || uploadingCount.value > 0) return;

            submitting.value = true;
            try {
                const result = await submitTask({
                    product_name: productName.value.trim(),
                    target_user: targetUser.value.trim(),
                    selling_points: points,
                    platform: platform.value,
                    style: style.value,
                    duration: duration.value,
                    product_assets: productAssets.value.map((asset) => asset.url),
                    reference_video: referenceVideo.value?.url || null,
                }, requestKey.value);
                localStorage.setItem('recent_task_id', result.task_id);
                showToast('项目已创建，正在分析商品素材', 'success');
                location.hash = `#/task/${result.task_id}`;
            } catch (error) {
                requestKey.value = makeRequestKey();
                showToast(`创建失败：${error.message}`, 'error');
            } finally {
                submitting.value = false;
            }
        }

        return {
            AD_STYLES, PLATFORMS,
            productName, targetUser, sellingPoints, platform, style, duration,
            productAssets, referenceVideo, uploadingCount, submitting, dragActive, errors, canSubmit, appliedInspiration,
            addPoint, removePoint, removeAsset, addProductFiles, onDrop, addReferenceVideo, loadDemo, onSubmit,
        };
    },
    template: `
        <div class="new-video-page">
            <form class="creation-hero new-video-studio" @submit.prevent="onSubmit" novalidate aria-labelledby="creation-title">
                <div class="creation-hero__intro">
                    <div>
                        <div class="creation-kicker">AI product video studio</div>
                        <h1 id="creation-title">从商品素材，到可发布成片。</h1>
                        <p>上传商品与参考视频，系统会自动理解卖点、生成分镜、补齐图片和视频片段，并完成最终合成与预审。</p>
                    </div>
                    <button class="text-button" type="button" @click="loadDemo"><IconRefresh /> 使用示例商品</button>
                </div>
                <div v-if="appliedInspiration" class="applied-inspiration" role="status"><IconCheck /> 已带入灵感「{{ appliedInspiration }}」的受众、卖点与创意参数</div>

                <div class="creation-workspace">
                    <div class="upload-zone-wrap">
                        <div
                            :class="['upload-zone', dragActive && 'is-dragging', productAssets.length && 'has-assets']"
                            @dragenter.prevent="dragActive = true"
                            @dragover.prevent="dragActive = true"
                            @dragleave.prevent="dragActive = false"
                            @drop.prevent="onDrop"
                        >
                            <input id="product-files" class="sr-only" type="file" accept="image/jpeg,image/png,image/webp" multiple @change="addProductFiles" />
                            <template v-if="!productAssets.length">
                                <span class="upload-zone__icon"><IconUpload /></span>
                                <strong>上传商品素材</strong>
                                <span>拖入商品主图、细节图或包装图</span>
                                <label for="product-files" class="upload-zone__button">选择图片</label>
                                <small>PNG、JPG、WEBP · 最多 12 张</small>
                            </template>
                            <div v-else class="asset-grid">
                                <div class="asset-thumb" v-for="(asset, index) in productAssets" :key="asset.asset_id || asset.url">
                                    <img :src="asset.url" :alt="asset.name" />
                                    <button type="button" @click="removeAsset(index)" :aria-label="'移除 ' + asset.name"><IconClose /></button>
                                </div>
                                <label v-if="productAssets.length < 12" for="product-files" class="asset-thumb asset-thumb--add"><IconPlus /><span>继续添加</span></label>
                            </div>
                            <div v-if="uploadingCount" class="submit-uploading"><IconLoading class="spin" /> 正在上传 {{ uploadingCount }} 个素材</div>
                        </div>
                        <p v-if="errors.product_assets" class="submit-error" role="alert">{{ errors.product_assets }}</p>

                        <div class="reference-row">
                            <div class="reference-row__copy"><span class="reference-row__icon"><IconFileVideo /></span><span><strong>参考视频</strong><small>{{ referenceVideo ? referenceVideo.name : '可选，用于理解节奏、镜头和风格' }}</small></span></div>
                            <input id="reference-video" class="sr-only" type="file" accept="video/mp4,video/quicktime,video/webm" @change="addReferenceVideo" />
                            <button v-if="referenceVideo" type="button" class="reference-row__remove" @click="referenceVideo = null"><IconClose /></button>
                            <label v-else for="reference-video" class="reference-row__action">添加视频</label>
                        </div>
                    </div>

                    <div class="brief-panel">
                        <div class="brief-panel__head"><span>创作 Brief</span><span class="brief-panel__step">01 / INPUT</span></div>
                        <label class="studio-field"><span>商品名称 *</span><input v-model="productName" type="text" maxlength="255" placeholder="例如：Aero One 无线耳机" :aria-invalid="Boolean(errors.product_name)" /><small v-if="errors.product_name" class="submit-error">{{ errors.product_name }}</small></label>
                        <div class="studio-field-row">
                            <label class="studio-field"><span>目标平台</span><select v-model="platform"><option v-for="item in PLATFORMS" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                            <label class="studio-field"><span>成片时长</span><select v-model.number="duration"><option :value="15">15 秒</option><option :value="20">20 秒</option><option :value="30">30 秒</option><option :value="45">45 秒</option></select></label>
                        </div>
                        <label class="studio-field"><span>目标受众</span><input v-model="targetUser" type="text" maxlength="255" placeholder="用户年龄、场景与核心需求" /></label>
                        <label class="studio-field"><span>核心卖点 *</span><textarea v-model="sellingPoints[0]" rows="2" maxlength="200" placeholder="例如：舒适佩戴、通勤降噪、30 小时续航"></textarea><small v-if="errors.selling_points" class="submit-error">{{ errors.selling_points }}</small></label>
                        <div v-if="sellingPoints.length > 1" class="brief-points"><span v-for="(point, index) in sellingPoints.slice(1)" :key="index">{{ point }}<button type="button" @click="removePoint(index + 1)"><IconClose /></button></span></div>
                        <button v-if="sellingPoints.length < 6" type="button" class="brief-add-point" @click="addPoint"><IconPlus /> 添加卖点</button>
                        <div class="brief-panel__tip"><IconCheck /> 商品参数会作为事实源，生成内容不会越过已确认信息。</div>
                    </div>
                </div>

                <div class="composer new-video-composer">
                    <span class="composer__add"><IconPlus /></span>
                    <div class="new-video-composer__copy"><strong>生成 3 条 9:16 竖屏短视频</strong><small>系统将基于商品事实、目标人群与所选风格生成</small></div>
                    <label class="composer-style"><span class="sr-only">创意风格</span><select v-model="style"><option v-for="item in AD_STYLES" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
                    <div class="composer__meta"><span>3 variants</span><span>9:16</span><span>{{ duration }}s</span></div>
                    <button type="submit" :disabled="!canSubmit || submitting" aria-label="提交并开始生成"><IconLoading v-if="submitting" class="spin" /><IconSend v-else /></button>
                </div>
            </form>
        </div>
    `,
};
