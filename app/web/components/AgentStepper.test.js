import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { AgentStepper } from './AgentStepper.js';

const sampleSteps = [
    { step_id: 'product_analysis', step_name: '商品理解', status: 'success', retry_count: 0, latency_ms: 800 },
    { step_id: 'script_generation', step_name: '广告脚本', status: 'running', retry_count: 0, latency_ms: null },
    { step_id: 'storyboard_planning', step_name: '分镜规划', status: 'pending', retry_count: 0, latency_ms: null },
    { step_id: 'material_suggestion', step_name: '素材建议', status: 'pending', retry_count: 0, latency_ms: null },
    { step_id: 'quality_evaluation', step_name: '质量评估', status: 'pending', retry_count: 0, latency_ms: null },
];

describe('AgentStepper', () => {
    it('renders 5 rows', () => {
        const w = mount(AgentStepper, { props: { steps: sampleSteps } });
        const rows = w.findAll('[data-testid="step-row"]');
        expect(rows.length).toBe(5);
    });

    it('shows success check for completed steps', () => {
        const w = mount(AgentStepper, { props: { steps: sampleSteps } });
        expect(w.text()).toContain('✓');
        expect(w.text()).toContain('商品理解');
    });

    it('shows running indicator on the running step', () => {
        const w = mount(AgentStepper, { props: { steps: sampleSteps } });
        const runningRow = w.find('[data-step-id="script_generation"]');
        expect(runningRow.text()).toContain('运行中');
    });

    it('shows retry count when retry_count > 0', () => {
        const steps = [{ ...sampleSteps[0], retry_count: 2 }];
        const w = mount(AgentStepper, { props: { steps } });
        expect(w.text()).toContain('重试 2 次');
    });
});
