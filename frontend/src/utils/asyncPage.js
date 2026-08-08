import { defineAsyncComponent, h } from 'vue'
import AsyncState from '../components/AsyncState.vue'

const AsyncPageLoading = {
  name: 'AsyncPageLoading',
  setup: () => () => h(AsyncState, { loading: true, rows: 6 }),
}

const AsyncPageError = {
  name: 'AsyncPageError',
  props: { error: { type: Object, required: true } },
  setup: props => () => h(AsyncState, {
    error: props.error,
    errorTitle: '页面加载失败',
    retry: () => window.location.reload(),
  }),
}

export function defineAsyncPage(loader) {
  return defineAsyncComponent({
    loader,
    loadingComponent: AsyncPageLoading,
    errorComponent: AsyncPageError,
    delay: 0,
    timeout: 30000,
    suspensible: false,
  })
}
