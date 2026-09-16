<template>
  <t-card size="small" :bordered="false" class="config-card workspace-card" data-testid="multicast-config">
    <div class="config-header">
      <div>
        <div class="section-title section-title--flush">UDPXY 组播采集</div>
        <p class="section-desc">为代理匹配同省份、同运营商的组播频道表，生成 HTTP 线路后逐条测速，合格线路进入候选池。</p>
      </div>
      <t-switch v-model="config.multicast_enabled" :label="['开启', '关闭']" aria-label="UDPXY 组播采集" />
    </div>

    <div class="config-panel-grid">
      <section class="config-panel">
        <div class="config-panel-head">
          <h3>代理发现</h3>
          <p>沿用上方省份和运营商筛选。手动代理优先，所有来源共用每轮代理和频道上限。</p>
        </div>
        <div class="config-field-list">
          <div class="config-field config-field--stack">
            <div class="config-field-meta">
              <label>Quake 自动发现</label>
              <span>仅当本轮采集平台包含 Quake 且已配置 Key 时搜索，会消耗 Quake 额度。关闭后仍可使用手动代理。</span>
            </div>
            <t-switch v-model="config.multicast_quake_enabled" :label="['开启', '关闭']" aria-label="Quake 组播自动发现" />
          </div>
          <div v-for="field in budgetFields" :key="field.key" class="config-field">
            <div class="config-field-meta"><label>{{ field.label }}</label><span>{{ field.hint }}</span></div>
            <t-input-number v-model="config[field.key]" :min="1" :max="field.max" class="field-control" />
          </div>
          <div class="config-field config-field--stack">
            <div class="config-field-meta">
              <label>手动代理</label>
              <span>每行填写“省份,运营商,代理基础地址”。支持电信、联通、移动；地址需为公网 IP，可带 /udpxy 前缀，不能带账号、参数或频道播放路径。</span>
            </div>
            <t-textarea v-model="config.multicast_proxy_urls" :maxlength="64000"
              placeholder="广东,电信,http://你的公网IP:端口&#10;# 每行一个代理"
              :autosize="{ minRows: 4, maxRows: 10 }" aria-label="手动组播代理" />
          </div>
          <div class="field-inline-hint">每轮组播采集最多运行 120 秒，其中搜索最多 60 秒；并发探测最多 5 个代理。小预算下模板按日轮转，未匹配的代理会在采集日志中说明。</div>
        </div>
      </section>

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
          <div class="field-inline-hint">修改后使用页面“保存配置”，从下一轮采集开始生效。关闭自动发现并填写代理，可不使用搜索 API。</div>
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
const budgetFields = [
  { key: 'multicast_search_size', label: '组播搜索预算', max: 300, hint: 'Quake 每轮最多请求的结果条数，在所选模板组之间分配；与主查询、质量画像预算分别计算。' },
  { key: 'multicast_max_proxies', label: '代理探测上限', max: 50, hint: '每轮最多探测的代理与模板组合数，手动代理同样计入。' },
  { key: 'multicast_max_channels', label: '组播候选上限', max: 2000, hint: '每轮进入常规检测的组播频道数，各个可用代理轮流分配，避免单个代理占满。' },
]
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
