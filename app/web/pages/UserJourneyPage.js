import { computed, ref } from 'vue';
import {
    IconArrowRight,
    IconCheck,
    IconClose,
    IconImage,
    IconPlayArrowFill,
    IconSearch,
} from '@arco-design/web-vue/es/icon';
import headphonesDetail from '../assets/studio/headphones-detail.jpg';
import headphonesFilm from '../assets/studio/headphones-film.jpg';
import headphonesHero from '../assets/studio/headphones-hero.jpg';
import headphonesLifestyle from '../assets/studio/headphones-lifestyle.jpg';
import backendSystemMap from '../assets/studio/backend-system-map.png';

export const PIPELINE = [
    { key: 'analysis', label: '商品分析', note: '从商品图与事实中提取卖点、受众与场景', meta: 'FACT LAYER', image: headphonesDetail },
    { key: 'strategy', label: '创意策略', note: '同时形成多条可验证、可对比的创意假设', meta: 'IDEA LAYER', image: headphonesHero },
    { key: 'storyboard', label: '生成分镜', note: '把脚本、镜头语言和素材需求映射到时间轴', meta: 'STORY LAYER', image: headphonesLifestyle },
    { key: 'image', label: '生成图片', note: '在商品事实约束下补齐场景、角度和关键帧', meta: 'VISUAL LAYER', image: headphonesHero },
    { key: 'clips', label: '生成视频', note: '逐镜头生成动态片段，并保留每次生成版本', meta: 'MOTION LAYER', image: headphonesLifestyle },
    { key: 'compose', label: '合成成片', note: '完成旁白、字幕、音乐、平台规则与事实审核', meta: 'REVIEW LAYER', image: headphonesFilm },
];

export const RELIABILITY_LAYERS = [
    { key: 'intake', index: '01', label: '持久化任务入口', tech: 'FastAPI · Schema validation', note: '请求进入系统后立即生成 Task ID 与 Trace ID，输入、执行状态和每个步骤都拥有持久化记录。' },
    { key: 'outbox', index: '02', label: '事务级可靠投递', tech: 'PostgreSQL · Transactional Outbox', note: '任务状态与下一步事件在同一事务提交，服务重启也不会丢失生成进度。' },
    { key: 'workers', index: '03', label: '幂等 Agent 集群', tech: 'Redis lease · RabbitMQ workers', note: '重复消息会被执行租约拦截，已成功步骤不会被旧消息再次消费，Worker 可以独立扩展。' },
    { key: 'quality', index: '04', label: '质量评估门禁', tech: 'LLM-as-Judge · Feedback loop', note: '评估不通过时携带问题与修改建议回流，让下一轮生成基于证据改进。' },
    { key: 'recovery', index: '05', label: '自动修复与恢复', tech: 'Backoff · Repair Agent · DLQ', note: '异常输出先自动修复，失败按退避策略重试，最终仍可从死信队列人工接管。' },
];

const CREATIVE_CARDS = [
    { id: 'film', title: '静默降噪 · 产品英雄片', type: '成片', duration: '00:24', image: headphonesFilm, status: '已完成', ratio: 'tall' },
    { id: 'lifestyle', title: '通勤场景 · Lifestyle', type: '视频片段', duration: '00:08', image: headphonesLifestyle, status: '已完成', ratio: 'wide' },
    { id: 'hero', title: 'Aero One · 商品主视觉', type: '关键帧', duration: '4K', image: headphonesHero, status: '已审核', ratio: 'medium' },
    { id: 'detail', title: '材质细节 · 微距镜头', type: '分镜素材', duration: 'Shot 04', image: headphonesDetail, status: '已完成', ratio: 'medium' },
];

export const UserJourneyPage = {
    components: {
        IconArrowRight,
        IconCheck,
        IconClose,
        IconImage,
        IconPlayArrowFill,
        IconSearch,
    },
    setup() {
        const activeStage = ref(0);
        const activeFilter = ref('全部');
        const search = ref('');
        const selectedCard = ref(null);
        const activeReliability = ref('outbox');

        const selectedStage = computed(() => PIPELINE[activeStage.value]);
        const selectedReliability = computed(() => RELIABILITY_LAYERS.find((layer) => layer.key === activeReliability.value) || RELIABILITY_LAYERS[0]);
        const filteredCards = computed(() => {
            const needle = search.value.trim().toLowerCase();
            return CREATIVE_CARDS.filter((card) => {
                const filterMatch = activeFilter.value === '全部'
                    || (activeFilter.value === '图片' && ['关键帧', '分镜素材'].includes(card.type))
                    || (activeFilter.value === '视频' && ['成片', '视频片段'].includes(card.type));
                return filterMatch && (!needle || card.title.toLowerCase().includes(needle));
            });
        });

        return {
            PIPELINE,
            RELIABILITY_LAYERS,
            backendSystemMap,
            activeStage,
            selectedStage,
            activeReliability,
            selectedReliability,
            activeFilter,
            search,
            selectedCard,
            filteredCards,
        };
    },
    template: `
        <div class="saas-home">
            <section class="saas-hero" aria-labelledby="saas-title">
                <div class="saas-hero__copy">
                    <span class="creation-kicker">AdAgentFlow · Creative operating system</span>
                    <h1 id="saas-title">一条可理解、<br />可干预的生成链路。</h1>
                    <p>从商品事实到最终成片，每一步都有输入、产出与 Review。让 AI 创作不再是黑盒，而是一套团队可以复用的生产系统。</p>
                    <div class="saas-hero__actions">
                        <a href="#/submit">开始生成视频 <IconArrowRight /></a>
                        <a href="#/ops" class="secondary">查看运行链路</a>
                    </div>
                    <div class="saas-hero__proof" aria-label="产品能力数据">
                        <span><strong>06</strong><small>可追踪阶段</small></span>
                        <span><strong>100%</strong><small>中间产物可回看</small></span>
                        <span><strong>3–5m</strong><small>完成首轮创意</small></span>
                    </div>
                </div>

                <div class="saas-hero__art" aria-label="商品视频生成结果示意">
                    <figure class="saas-frame saas-frame--back"><img :src="PIPELINE[2].image" alt="通勤场景视频关键帧" /></figure>
                    <figure class="saas-frame saas-frame--front">
                        <img :src="PIPELINE[5].image" alt="无线耳机产品成片画面" />
                        <figcaption><span><IconPlayArrowFill /></span><strong>Final cut · 00:24</strong><small>9:16 · Review passed</small></figcaption>
                    </figure>
                    <div class="saas-artifact saas-artifact--analysis"><span>01</span><strong>商品事实已锁定</strong><small>12 facts · 0 conflict</small></div>
                    <div class="saas-artifact saas-artifact--review"><IconCheck /><span><strong>平台预审通过</strong><small>TikTok Shop · 94/100</small></span></div>
                </div>
            </section>

            <section id="workflow" class="saas-pipeline" aria-labelledby="pipeline-title">
                <div class="saas-section-head">
                    <div><span class="creation-kicker">The system, not the magic</span><h2 id="pipeline-title">每一个创意决策，都有迹可循。</h2></div>
                    <p>点击任意阶段，查看这一步如何消费上游数据、产出可编辑资产，并进入下一轮 Review。</p>
                </div>

                <div class="saas-stage-tabs" role="tablist" aria-label="视频生成阶段">
                    <button v-for="(step, index) in PIPELINE" :key="step.key" type="button" :class="activeStage === index && 'is-active'" @click="activeStage = index" role="tab" :aria-selected="activeStage === index">
                        <span>{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ step.label }}</strong>
                    </button>
                </div>

                <div class="saas-stage-detail">
                    <div class="saas-stage-detail__copy">
                        <span>{{ selectedStage.meta }}</span>
                        <h3>{{ selectedStage.label }}</h3>
                        <p>{{ selectedStage.note }}</p>
                        <ul>
                            <li><IconCheck /> 输入与输出均保留版本</li>
                            <li><IconCheck /> 支持人工修改后继续生成</li>
                            <li><IconCheck /> 失败可定位、可重试、可审计</li>
                        </ul>
                        <a href="#/submit">用我的商品体验这一流程 <IconArrowRight /></a>
                    </div>
                    <div class="saas-stage-detail__visual">
                        <img :src="selectedStage.image" :alt="selectedStage.label + ' 阶段视觉产物'" />
                        <span>{{ String(activeStage + 1).padStart(2, '0') }} / {{ String(PIPELINE.length).padStart(2, '0') }}</span>
                        <div><small>Current output</small><strong>{{ selectedStage.label }}</strong><em>Ready for review</em></div>
                    </div>
                </div>
            </section>

            <section class="saas-foundation" aria-labelledby="foundation-title">
                <div class="saas-foundation__intro">
                    <div><span class="creation-kicker">Reliability is the product</span><h2 id="foundation-title">一张持续流动的可靠性地图。</h2></div>
                    <p>AdAgentFlow 不是一次性的 Prompt 拼接。它是一套面向长任务的多 Agent 执行系统：消息不丢、步骤不重、失败可恢复、结果可审计。</p>
                    <div class="architecture-live"><IconCheck /><span><strong>Distributed system online</strong><small>Queue · Workers · Trace</small></span></div>
                </div>

                <div class="architecture-map" aria-label="AdAgentFlow 后端可靠性架构图">
                    <img :src="backendSystemMap" alt="由任务入口、事务消息、Agent 集群、质量门禁和恢复中心组成的等距后端架构图" />
                    <div class="architecture-flow" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
                    <button v-for="layer in RELIABILITY_LAYERS" :key="layer.key" type="button" :class="['architecture-callout', 'architecture-callout--' + layer.key, activeReliability === layer.key && 'is-active']" @click="activeReliability = layer.key">
                        <span>{{ layer.index }}</span><strong>{{ layer.label }}</strong><small>{{ layer.tech }}</small>
                    </button>
                </div>

                <div class="architecture-readout" aria-live="polite">
                    <div :key="selectedReliability.key"><span>{{ selectedReliability.index }} / SYSTEM NODE</span><h3>{{ selectedReliability.label }}</h3><p>{{ selectedReliability.note }}</p></div>
                    <div class="architecture-readout__facts">
                        <span><small>STACK</small><strong>{{ selectedReliability.tech }}</strong></span>
                        <span><small>TRACE</small><strong>task · step · model · prompt</strong></span>
                        <span><small>TELEMETRY</small><strong>tokens · latency · retries</strong></span>
                    </div>
                    <a href="#/ops" class="architecture-readout__link">Open console <IconArrowRight /></a>
                </div>
            </section>

            <section id="projects" class="inspiration-panel saas-creations" aria-labelledby="projects-title">
                <div class="section-heading section-heading--projects">
                    <div><div class="creation-kicker">Recent creations</div><h2 id="projects-title">从一个商品，长出一组创意。</h2><p>分镜、关键帧、视频片段与成片都保留上下文，可持续迭代和复用。</p></div>
                    <label class="studio-search"><IconSearch /><input v-model="search" type="search" placeholder="搜索项目或素材" /></label>
                </div>
                <div class="filter-tabs" role="tablist" aria-label="作品类型">
                    <button v-for="filter in ['全部', '图片', '视频']" :key="filter" type="button" :class="activeFilter === filter && 'is-active'" @click="activeFilter = filter">{{ filter }}</button>
                </div>
                <div id="assets" class="masonry-grid">
                    <button v-for="card in filteredCards" :key="card.id" :class="['creative-card', 'creative-card--' + card.ratio]" type="button" @click="selectedCard = card">
                        <img :src="card.image" :alt="card.title" loading="lazy" />
                        <span class="creative-card__type">{{ card.type }}</span>
                        <span class="creative-card__play" v-if="card.type === '成片' || card.type === '视频片段'"><IconPlayArrowFill /></span>
                        <span class="creative-card__overlay"><span><strong>{{ card.title }}</strong><small>{{ card.status }}</small></span><small>{{ card.duration }}</small></span>
                    </button>
                </div>
                <div v-if="!filteredCards.length" class="empty-state"><IconImage /><strong>没有匹配的作品</strong><span>换个关键词或查看全部类型。</span></div>
            </section>

            <div v-if="selectedCard" class="preview-backdrop" @click.self="selectedCard = null">
                <section class="preview-modal" role="dialog" aria-modal="true" :aria-label="selectedCard.title">
                    <button class="preview-modal__close" type="button" @click="selectedCard = null" aria-label="关闭预览"><IconClose /></button>
                    <div class="preview-modal__media"><img :src="selectedCard.image" :alt="selectedCard.title" /><span v-if="selectedCard.type.includes('视频') || selectedCard.type === '成片'"><IconPlayArrowFill /></span></div>
                    <div class="preview-modal__content"><div class="creation-kicker">{{ selectedCard.type }} · {{ selectedCard.duration }}</div><h3>{{ selectedCard.title }}</h3><p>该产物保留了商品事实、创意假设、分镜和 Review 记录，可继续编辑或导出。</p><div class="preview-modal__actions"><button type="button">进入编辑</button><button type="button" class="secondary">导出</button></div></div>
                </section>
            </div>
        </div>
    `,
};
