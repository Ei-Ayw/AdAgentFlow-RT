import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { StatusBadge } from './StatusBadge.js';

describe('StatusBadge', () => {
    it('renders success status with neutral styling', () => {
        const wrapper = mount(StatusBadge, { props: { status: 'success' } });
        expect(wrapper.text()).toContain('成功');
        expect(wrapper.classes().join(' ')).toMatch(/is-success/);
    });

    it('renders failed status with neutral styling', () => {
        const wrapper = mount(StatusBadge, { props: { status: 'failed' } });
        expect(wrapper.text()).toContain('失败');
        expect(wrapper.classes().join(' ')).toMatch(/is-failed/);
    });

    it('renders running status', () => {
        const wrapper = mount(StatusBadge, { props: { status: 'running' } });
        expect(wrapper.text()).toContain('运行中');
    });

    it('handles unknown status gracefully', () => {
        const wrapper = mount(StatusBadge, { props: { status: 'whatever' } });
        expect(wrapper.text()).toContain('whatever');
    });
});
