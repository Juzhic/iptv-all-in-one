<template>
  <t-card size="small" :bordered="false" class="config-card workspace-card" data-testid="multicast-config">
    <div class="config-header">
      <div>
        <div class="section-title section-title--flush">UDPXY 频道模板</div>
        <p class="section-desc">扫描发现 UDPXY 后使用这些频道表生成候选。平台、搜索预算与区域筛选统一使用上方配置。</p>
      </div>
    </div>

    <div>
      <section class="config-panel">
        <div class="config-panel-head">
          <h3>频道模板</h3>
          <p>模板保存频道名称与组播地址。代理能访问状态页不代表能播放，最终以实际检测为准。</p>
        </div>
        <div class="config-field-list">
          <div class="config-field config-field--stack">
            <div class="config-field-meta">
              <label>使用内置模板</label>
              <span>来自 spider-iptv 的 2024 年历史快照，可能存在过期地址；不使用文件中的旧代理。可用自定义模板更新同一省份和运营商的频道表。</span>
            </div>
            <t-switch v-model="config.multicast_use_builtin" :label="['开启', '关闭']" aria-label="使用内置组播模板" />
            <details class="multicast-catalog">
              <summary>查看内置覆盖范围（{{ catalog.length }} 组）</summary>
              <div class="multicast-catalog-list">
                <t-tag v-for="item in catalog" :key="`${item.province}-${item.operator}`" size="small" variant="light">
                  {{ item.province }} · {{ item.operator }} · {{ item.channels }} 频道
                </t-tag>
              </div>
            </details>
          </div>
          <div class="config-field config-field--stack">
            <div class="config-field-meta">
              <label>自定义模板</label>
              <span>粘贴 TXT 或 M3U，每组替换对应省份和运营商的内置频道表。支持 rtp://、udp:// 及含 /rtp/、/udp/ 的 HTTP 地址；只提取其中的组播地址。最多 32 组。</span>
            </div>
            <div v-for="(item, index) in config.multicast_templates" :key="index" class="multicast-template">
              <div class="multicast-template-controls">
                <t-select v-model="item.province" :options="provinceOptions" placeholder="选择省份" :aria-label="`模板 ${index + 1} 省份`" />
                <t-select v-model="item.operator" :options="operatorOptions" placeholder="选择运营商" :aria-label="`模板 ${index + 1} 运营商`" />
                <t-button variant="text" theme="danger" :aria-label="`删除模板 ${index + 1}`" @click="config.multicast_templates.splice(index, 1)">删除</t-button>
              </div>
              <t-textarea v-model="item.content" :maxlength="128000" :aria-label="`模板 ${index + 1} 频道表`"
                placeholder="CCTV1,rtp://239.1.1.1:1234&#10;CCTV2,udp://239.1.1.2:1234"
                :autosize="{ minRows: 5, maxRows: 12 }" />
            </div>
            <t-button variant="outline" :disabled="config.multicast_templates.length >= 32"
              @click="config.multicast_templates.push({ province: '', operator: '', content: '' })">添加组播模板</t-button>
          </div>
          <div class="field-inline-hint">修改后使用页面“保存配置”。手动代理请在“IP 探测”选择“UDPXY（组播）”，填写 IP 和端口，无需搜索 API。</div>
        </div>
      </section>
    </div>
  </t-card>
</template>

<script setup>
defineProps({
  config: { type: Object, required: true },
  catalog: { type: Array, default: () => [] },
  provinceOptions: { type: Array, required: true },
})

const operatorOptions = ['电信', '联通', '移动'].map(value => ({ label: value, value }))
</script>

<style scoped>
@import '../styles/configuration.css';

:deep(.t-switch) { align-self: flex-start; flex-shrink: 0; }
.multicast-template { display: grid; gap: 12px; width: 100%; min-width: 0; }
.multicast-template-controls { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.multicast-catalog { width: 100%; color: var(--td-text-color-secondary); }
.multicast-catalog summary { cursor: pointer; }
.multicast-catalog-list { display: flex; flex-wrap: wrap; gap: 6px; padding-top: 12px; }
</style>
