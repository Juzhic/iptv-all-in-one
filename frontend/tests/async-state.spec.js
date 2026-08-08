import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AsyncState from '../src/components/AsyncState.vue'

describe('AsyncState', () => {
  it('renders errors and invokes retry', async () => {
    let retried = false
    const wrapper = mount(AsyncState, {
      props: { error: new Error('network down'), retry: () => { retried = true } },
      global: {
        stubs: {
          't-button': { template: '<button @click="$attrs.onClick"><slot /></button>' },
          't-skeleton': true,
        },
      },
    })
    expect(wrapper.text()).toContain('network down')
    await wrapper.get('button').trigger('click')
    expect(retried).toBe(true)
  })

  it('renders the empty state without rendering success content', () => {
    const wrapper = mount(AsyncState, {
      props: { empty: true, emptyTitle: '没有记录' },
      slots: { default: '<div>success</div>' },
      global: { stubs: { 't-button': true, 't-skeleton': true } },
    })
    expect(wrapper.text()).toContain('没有记录')
    expect(wrapper.text()).not.toContain('success')
  })
})
