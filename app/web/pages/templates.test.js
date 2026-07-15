import { describe, expect, it } from 'vitest';
import { compile } from 'vue';
import { PIPELINE, RELIABILITY_LAYERS, UserJourneyPage } from './UserJourneyPage.js';
import { TaskListPage } from './TaskListPage.js';
import { SubmitPage } from './SubmitPage.js';
import { TaskDetailPage } from './TaskDetailPage.js';
import { INSPIRATIONS, InspirationPage } from './InspirationPage.js';

describe('page templates', () => {
    it.each([
        ['user journey', UserJourneyPage],
        ['task list', TaskListPage],
        ['submit', SubmitPage],
        ['task detail', TaskDetailPage],
        ['inspiration', InspirationPage],
    ])('compiles the %s page', (_name, component) => {
        expect(() => compile(component.template)).not.toThrow();
    });

    it('offers a searchable inspiration gallery with a reusable creative brief', () => {
        expect(InspirationPage.template).toContain('灵感广场');
        expect(InspirationPage.template).toContain('搜索创意、平台或卖点');
        expect(InspirationPage.template).toContain('复用这个创意');
        expect(INSPIRATIONS).toHaveLength(8);
        expect(INSPIRATIONS.every((item) => item.hook && item.structure && item.style)).toBe(true);
    });

    it('presents the generation pipeline as the SaaS homepage', () => {
        expect(UserJourneyPage.template).toContain('一条可理解、');
        expect(UserJourneyPage.template).toContain('可干预的生成链路');
        expect(UserJourneyPage.template).toContain('开始生成视频');
        expect(RELIABILITY_LAYERS.map((layer) => layer.label)).toContain('事务级可靠投递');
        expect(RELIABILITY_LAYERS.map((layer) => layer.label)).toContain('幂等 Agent 集群');
        expect(RELIABILITY_LAYERS.map((layer) => layer.label)).toContain('质量评估门禁');
        expect(UserJourneyPage.template).toContain('architecture-map');
        expect(UserJourneyPage.template).not.toContain('上传商品素材');
        expect(PIPELINE.map((step) => step.label)).toEqual([
            '商品分析', '创意策略', '生成分镜', '生成图片', '生成视频', '合成成片',
        ]);
    });

    it('collects real product assets and creative settings before submission', () => {
        expect(SubmitPage.template).toContain('上传商品素材');
        expect(SubmitPage.template).toContain('参考视频');
        expect(SubmitPage.template).toContain('创作 Brief');
        expect(SubmitPage.template).toContain('目标平台');
        expect(SubmitPage.template).toContain('提交并开始生成');
    });
});
