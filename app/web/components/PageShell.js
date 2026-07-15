import {
    IconFileImage,
    IconHome,
    IconQuestionCircle,
    IconRobot,
    IconSettings,
    IconVideoCamera,
} from '@arco-design/web-vue/es/icon';

export const PageShell = {
    components: {
        IconFileImage,
        IconHome,
        IconQuestionCircle,
        IconRobot,
        IconSettings,
        IconVideoCamera,
    },
    props: {
        activeTab: { type: String, required: true },
        title: { type: String, required: true },
        description: { type: String, required: true },
    },
    template: `
        <div class="studio-shell">
            <aside class="studio-sidebar" aria-label="主导航">
                <a class="studio-logo" href="#/" aria-label="AdAgentFlow 首页">
                    <span class="studio-logo__mark">A</span>
                    <span>AdAgentFlow</span>
                </a>

                <nav class="studio-nav">
                    <a href="#/" :class="['studio-nav__item', activeTab === 'user' && 'is-active']">
                        <IconHome /><span>创作首页</span>
                    </a>
                    <a href="#/submit" :class="['studio-nav__item', activeTab === 'submit' && 'is-active']">
                        <IconVideoCamera /><span>新建视频</span><span class="studio-nav__badge">AI</span>
                    </a>
                    <a href="#/inspiration" :class="['studio-nav__item', activeTab === 'inspiration' && 'is-active']">
                        <IconFileImage /><span>灵感广场</span>
                    </a>
                    <a href="#/ops" :class="['studio-nav__item', activeTab === 'ops' && 'is-active']">
                        <IconRobot /><span>生成任务</span>
                    </a>
                </nav>

                <div class="studio-sidebar__bottom">
                    <a href="#/ops" class="studio-nav__item"><IconSettings /><span>运行控制台</span></a>
                    <button class="studio-nav__item studio-nav__button" type="button">
                        <IconQuestionCircle /><span>帮助与反馈</span>
                    </button>
                    <div class="studio-user">
                        <span class="studio-user__avatar">Z</span>
                        <span class="studio-user__meta"><strong>创作空间</strong><small>Free plan · 36</small></span>
                    </div>
                </div>
            </aside>

            <div class="studio-main">
                <header class="studio-topbar">
                    <div class="studio-topbar__actions">
                        <span class="studio-credit"><span class="studio-credit__dot"></span> 36 credits</span>
                        <a href="#/submit" class="studio-topbar__button">新建项目</a>
                    </div>
                </header>

                <main class="studio-content" id="main-content">
                    <div class="sr-only">{{ description }}</div>
                    <slot />
                </main>
            </div>
        </div>
    `,
};
