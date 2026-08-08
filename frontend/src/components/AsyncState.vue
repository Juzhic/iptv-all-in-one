<template>
  <section class="async-state" :aria-busy="loading ? 'true' : 'false'" :aria-live="error ? 'assertive' : 'polite'">
    <t-skeleton v-if="loading" :row-col="skeletonRows" animation="gradient" />
    <div v-else-if="error" class="async-state__message async-state__message--error" role="alert">
      <div class="async-state__title">{{ errorTitle }}</div>
      <p>{{ errorMessage }}</p>
      <t-button v-if="retry" size="small" variant="outline" theme="primary" @click="retry">重新加载</t-button>
    </div>
    <div v-else-if="empty" class="async-state__message">
      <div class="async-state__title">{{ emptyTitle }}</div>
      <p v-if="emptyDescription">{{ emptyDescription }}</p>
      <slot name="empty-action" />
    </div>
    <slot v-else />
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  loading: { type: Boolean, default: false },
  error: { type: [String, Error, Object], default: '' },
  empty: { type: Boolean, default: false },
  errorTitle: { type: String, default: '加载失败' },
  emptyTitle: { type: String, default: '暂无数据' },
  emptyDescription: { type: String, default: '' },
  retry: { type: Function, default: null },
  rows: { type: Number, default: 4 },
})

const errorMessage = computed(() => props.error?.message || String(props.error || '请稍后重试'))
const skeletonRows = computed(() => Array.from({ length: props.rows }, (_, index) => ({
  width: index === props.rows - 1 ? '68%' : '100%',
})))
</script>

<style scoped>
.async-state { min-width: 0; }
.async-state__message {
  display: grid;
  place-items: center;
  gap: 8px;
  min-height: 180px;
  padding: 28px;
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
  text-align: center;
}
.async-state__message p { margin: 0; }
.async-state__title { color: var(--app-text); font-weight: 700; }
.async-state__message--error { border-color: color-mix(in srgb, var(--td-error-color, #d54941) 45%, transparent); }
</style>
