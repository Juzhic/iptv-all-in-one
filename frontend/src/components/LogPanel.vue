<template>
  <div class="log-panel-wrapper">
    <div class="log-toolbar">
      <t-button :theme="autoScroll ? 'primary' : 'default'" variant="outline" size="small" @click="autoScroll = !autoScroll">
        {{ autoScroll ? '暂停滚动' : '自动滚动' }}
      </t-button>
      <t-button variant="outline" size="small" @click="$emit('clear')">清空日志</t-button>
      <span v-if="showCount" class="log-count">{{ entries.length }} 条</span>
    </div>
    <div class="log-panel" ref="panelRef">
      <div v-for="(line, index) in entries" :key="index" class="log-line">
        <span v-if="line.ts || line.time" class="log-time">[{{ line.ts || line.time }}]</span>
        <span v-if="line.level" :class="levelClass(line.level)">[{{ levelText(line.level) }}]</span>
        <span :class="msgClass(line)">{{ line.message || line.msg || '' }}</span>
      </div>
      <div v-if="!entries.length" class="log-empty">{{ emptyText }}</div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  entries: { type: Array, default: () => [] },
  showCount: { type: Boolean, default: true },
  emptyText: { type: String, default: '暂无日志' },
})

defineEmits(['clear'])

const panelRef = ref(null)
const autoScroll = ref(true)

watch(() => props.entries.length, () => {
  if (!autoScroll.value) return
  nextTick(() => {
    const el = panelRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

function levelClass(level) {
  if (level === 'ERROR') return 'log-level-error'
  if (level === 'WARNING') return 'log-level-warn'
  return 'log-level-info'
}

function levelText(level) {
  if (level === 'ERROR') return 'ERROR'
  if (level === 'WARNING') return 'WARN'
  return 'INFO'
}

function msgClass(line) {
  const msg = line.message || line.msg || ''
  if (/失败|异常|error|终止/i.test(msg)) return 'log-msg-fail'
  if (/通过|完成|pass|成功|存活|发现/i.test(msg)) return 'log-msg-pass'
  return 'log-msg-info'
}
</script>

<style scoped>
.log-panel-wrapper {
  display: flex;
  flex-direction: column;
}

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.log-count {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
}

.log-panel {
  height: 400px;
  overflow-y: auto;
  padding: 12px;
  border-radius: 12px;
  background:
    radial-gradient(circle at top right, rgba(124, 58, 237, 0.18), transparent 34%),
    linear-gradient(160deg, #161822 0%, #1e2230 100%);
  color: #cdd6f4;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  scroll-behavior: smooth;
}

.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.log-empty {
  color: #94a3b8;
  padding: 8px;
}

.log-time {
  margin-right: 8px;
  color: #93c5fd;
}

.log-level-error {
  color: #f38ba8;
  margin-right: 4px;
}

.log-level-warn {
  color: #f59e0b;
  margin-right: 4px;
}

.log-level-info {
  color: #cba6f7;
  margin-right: 4px;
}

.log-msg-fail {
  color: #f38ba8;
}

.log-msg-pass {
  color: #a6e3a1;
}

.log-msg-info {
  color: #cdd6f4;
}
</style>
