import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import {
    IconArrowRight,
    IconClose,
    IconHeart,
    IconHeartFill,
    IconPlayArrowFill,
    IconSearch,
} from '@arco-design/web-vue/es/icon';
import detailImage from '../assets/studio/headphones-detail.jpg';
import filmImage from '../assets/studio/headphones-film.jpg';
import heroImage from '../assets/studio/headphones-hero.jpg';
import lifestyleImage from '../assets/studio/headphones-lifestyle.jpg';

export const INSPIRATIONS = [
    {
        id: 'quiet-commute', title: '把通勤噪声，留在画面之外', category: '电影感', platform: 'TikTok',
        duration: 24, image: filmImage, ratio: 'portrait', saves: 1284, trend: '本周热门',
        style: 'lifestyle cinematic ad', audience: '城市通勤与轻办公人群，22–35 岁',
        sellingPoint: '用拥挤通勤与安静聆听的强烈反差，突出主动降噪和舒适佩戴。',
        hook: '0–3 秒用环境噪声制造冲突', structure: '冲突 → 戴上产品 → 世界安静 → 产品特写',
    },
    {
        id: 'macro-craft', title: '一毫米，也值得一个镜头', category: '产品展示', platform: 'Instagram',
        duration: 15, image: detailImage, ratio: 'square', saves: 967, trend: '编辑精选',
        style: 'problem-solution demo ad', audience: '注重设计、材质与长期使用体验的品质用户',
        sellingPoint: '通过微距镜头展示材质、转轴和耳罩细节，建立高端工艺感。',
        hook: '从极近的材质纹理开始', structure: '材质微距 → 结构运动 → 完整产品 → 品牌收束',
    },
    {
        id: 'day-in-life', title: '一副耳机，接住一整天', category: '达人 UGC', platform: 'TikTok',
        duration: 30, image: lifestyleImage, ratio: 'landscape', saves: 1856, trend: '高收藏',
        style: 'creator UGC raw ad', audience: '需要通勤、办公和运动多场景切换的年轻用户',
        sellingPoint: '用第一人称日常记录证明续航、便携和多场景稳定连接。',
        hook: '“今天不带充电线出门”', structure: '出门 → 通勤 → 办公 → 运动 → 电量结尾',
    },
    {
        id: 'before-after', title: '戴上之前 / 戴上之后', category: '高转化', platform: 'YouTube Shorts',
        duration: 20, image: heroImage, ratio: 'portrait', saves: 2410, trend: '转化标杆',
        style: 'dramatic before-after ad', audience: '被通勤、办公室和居家噪音困扰的用户',
        sellingPoint: '前后对比直观呈现降噪价值，并用产品参数完成购买说服。',
        hook: '一秒切换嘈杂与安静', structure: '使用前 → 产品动作 → 使用后 → 三项事实 → CTA',
    },
    {
        id: 'honest-review', title: '连续佩戴 8 小时之后', category: '真人测评', platform: 'TikTok',
        duration: 30, image: lifestyleImage, ratio: 'portrait', saves: 1533, trend: '信任增长',
        style: 'testimonial review ad', audience: '购买前会认真查看长期体验和真实测评的用户',
        sellingPoint: '用长期佩戴后的真实感受验证舒适度、续航与连接稳定性。',
        hook: '先说一个真实使用结论', structure: '结论先行 → 三个体验证据 → 小缺点 → 推荐人群',
    },
    {
        id: 'single-light', title: '一束光，讲清产品轮廓', category: '产品展示', platform: 'Instagram',
        duration: 15, image: filmImage, ratio: 'landscape', saves: 742, trend: '新作',
        style: 'lifestyle cinematic ad', audience: '偏好极简审美与高质感数码产品的用户',
        sellingPoint: '单色光影和克制运镜塑造旗舰产品的视觉价值。',
        hook: '黑场中只出现一道产品轮廓', structure: '轮廓 → 材质 → 佩戴 → 英雄镜头 → Logo',
    },
    {
        id: 'three-problems', title: '三个通勤痛点，20 秒解决', category: '高转化', platform: 'TikTok',
        duration: 20, image: detailImage, ratio: 'landscape', saves: 1169, trend: '高完播',
        style: 'problem-solution demo ad', audience: '追求高效率、希望快速理解产品价值的通勤用户',
        sellingPoint: '用三个真实痛点逐条对应产品功能，缩短用户决策路径。',
        hook: '“通勤最烦的三件事”', structure: '痛点清单 → 功能逐条回应 → 参数证明 → CTA',
    },
    {
        id: 'desk-reset', title: '让工位重新安静下来', category: '电影感', platform: 'YouTube Shorts',
        duration: 24, image: heroImage, ratio: 'square', saves: 894, trend: '编辑精选',
        style: 'lifestyle cinematic ad', audience: '需要深度专注的办公室与居家工作人群',
        sellingPoint: '以桌面秩序和声音空间的变化，表达专注体验与产品设计感。',
        hook: '混乱桌面与消息声快速叠加', structure: '干扰累积 → 戴上耳机 → 空间重置 → 专注工作',
    },
];

const FILTERS = ['全部', '高转化', '达人 UGC', '电影感', '产品展示', '真人测评'];

export const InspirationPage = {
    components: { IconArrowRight, IconClose, IconHeart, IconHeartFill, IconPlayArrowFill, IconSearch },
    setup() {
        const activeFilter = ref('全部');
        const search = ref('');
        const sort = ref('热门优先');
        const selected = ref(null);
        const savedIds = ref(new Set(JSON.parse(localStorage.getItem('saved_inspirations') || '[]')));

        const visibleItems = computed(() => {
            const keyword = search.value.trim().toLowerCase();
            const result = INSPIRATIONS.filter((item) => (
                (activeFilter.value === '全部' || item.category === activeFilter.value)
                && (!keyword || [item.title, item.category, item.platform, item.sellingPoint].join(' ').toLowerCase().includes(keyword))
            ));
            return sort.value === '收藏最多' ? [...result].sort((a, b) => b.saves - a.saves) : result;
        });

        function toggleSaved(item) {
            const next = new Set(savedIds.value);
            next.has(item.id) ? next.delete(item.id) : next.add(item.id);
            savedIds.value = next;
            localStorage.setItem('saved_inspirations', JSON.stringify([...next]));
        }

        function useInspiration(item) {
            localStorage.setItem('inspiration_template', JSON.stringify({
                title: item.title,
                style: item.style,
                platform: item.platform,
                duration: item.duration,
                targetUser: item.audience,
                sellingPoint: item.sellingPoint,
            }));
            location.hash = '#/submit';
        }

        function onKeydown(event) {
            if (event.key === 'Escape') selected.value = null;
        }

        onMounted(() => window.addEventListener('keydown', onKeydown));
        onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));

        return { FILTERS, activeFilter, search, sort, selected, savedIds, visibleItems, toggleSaved, useInspiration };
    },
    template: `
        <section class="inspiration-page" aria-labelledby="inspiration-title">
            <h1 id="inspiration-title" class="sr-only">灵感广场</h1>

            <div class="inspiration-toolbar">
                <label class="inspiration-search"><IconSearch /><span class="sr-only">搜索灵感</span><input v-model="search" type="search" placeholder="搜索创意、平台或卖点" /></label>
                <div class="inspiration-filters" aria-label="创意类型">
                    <button v-for="filter in FILTERS" :key="filter" type="button" :class="activeFilter === filter && 'is-active'" @click="activeFilter = filter">{{ filter }}</button>
                </div>
                <label class="inspiration-sort"><span class="sr-only">排序方式</span><select v-model="sort"><option>热门优先</option><option>收藏最多</option></select></label>
            </div>

            <div class="inspiration-result-meta"><span>{{ visibleItems.length }} 个创意方向</span><span>每个创意都可直接复用为生成 Brief</span></div>

            <div v-if="visibleItems.length" class="inspiration-grid">
                <article v-for="item in visibleItems" :key="item.id" :class="['inspiration-card', 'is-' + item.ratio]">
                    <button class="inspiration-card__media" type="button" @click="selected = item" :aria-label="'预览创意：' + item.title">
                        <img :src="item.image" :alt="item.title" />
                        <span class="inspiration-card__trend">{{ item.trend }}</span>
                        <span class="inspiration-card__play"><IconPlayArrowFill /></span>
                        <span class="inspiration-card__duration">00:{{ item.duration }}</span>
                    </button>
                    <div class="inspiration-card__body">
                        <div class="inspiration-card__meta"><span>{{ item.category }}</span><span>{{ item.platform }}</span></div>
                        <div class="inspiration-card__title-row">
                            <button type="button" @click="selected = item">{{ item.title }}</button>
                            <button class="inspiration-save" type="button" @click="toggleSaved(item)" :aria-label="savedIds.has(item.id) ? '取消收藏' : '收藏创意'">
                                <IconHeartFill v-if="savedIds.has(item.id)" /><IconHeart v-else />
                            </button>
                        </div>
                    </div>
                </article>
            </div>
            <div v-else class="inspiration-empty"><strong>没有找到匹配的创意</strong><span>换个关键词或查看全部类型。</span><button type="button" @click="search = ''; activeFilter = '全部'">清除筛选</button></div>

            <div v-if="selected" class="inspiration-modal" role="dialog" aria-modal="true" :aria-label="selected.title" @click.self="selected = null">
                <div class="inspiration-modal__panel">
                    <button class="inspiration-modal__close" type="button" @click="selected = null" aria-label="关闭创意预览"><IconClose /></button>
                    <div class="inspiration-modal__visual"><img :src="selected.image" :alt="selected.title" /><span><IconPlayArrowFill /></span></div>
                    <div class="inspiration-modal__content">
                        <div class="inspiration-eyebrow">{{ selected.category }} · {{ selected.platform }} · {{ selected.duration }}s</div>
                        <h2>{{ selected.title }}</h2>
                        <p>{{ selected.sellingPoint }}</p>
                        <dl class="inspiration-breakdown">
                            <div><dt>开场钩子</dt><dd>{{ selected.hook }}</dd></div>
                            <div><dt>镜头结构</dt><dd>{{ selected.structure }}</dd></div>
                            <div><dt>目标人群</dt><dd>{{ selected.audience }}</dd></div>
                        </dl>
                        <div class="inspiration-modal__actions">
                            <button type="button" @click="toggleSaved(selected)"><IconHeartFill v-if="savedIds.has(selected.id)" /><IconHeart v-else /> {{ savedIds.has(selected.id) ? '已收藏' : '收藏创意' }}</button>
                            <button class="is-primary" type="button" @click="useInspiration(selected)">复用这个创意 <IconArrowRight /></button>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    `,
};
