<template>
  <div class="scan-config-tab configuration-page">
    <t-card size="small" :bordered="false" class="keys-card workspace-card">
      <div class="section-header">
        <div>
          <div class="section-title section-title--flush">API Key 管理</div>
          <p class="section-desc">刷新余额查看账号配额；“测试可用性”单独验证所选 Key 的真实搜索权限。</p>
          <p class="section-desc">每次测试用已保存的关键词查询最多 1 条，可能消耗平台额度，不采集频道或测速。</p>
        </div>

        <t-space>
          <t-button variant="outline" size="small" :loading="keysLoading" @click="loadKeys">刷新余额</t-button>
          <t-button theme="primary" size="small" @click="openAddModal">+ 添加 Key</t-button>
        </t-space>
      </div>

      <div class="table-scroll-shell">
        <t-table
          :columns="keyColumns"
          :data="keyList"
          :bordered="false"
          row-key="_row_key"
          size="small"
          :pagination="null"
        >
          <template #platform="{ row }">
            {{ platformLabelMap[row.platform] || row.platform }}
          </template>
          <template #credit="{ row }">
            <div v-if="row.platform === 'fofa' && row.balances" class="fofa-balances">
              <span v-for="balance in fofaBalanceLabels" :key="balance.key">
                {{ balance.label }}：{{ formatCredit(row.balances[balance.key]) }}
              </span>
            </div>
            <template v-else>{{ formatCredit(row.credit, row.role_limit) }}</template>
          </template>
          <template #status="{ row }">
            <t-tag :theme="statusTheme(row.status)" size="small" variant="light" class="key-status">{{ row.status }}</t-tag>
          </template>
          <template #actions="{ row }">
            <t-space :size="4">
              <t-button variant="outline" size="small" :loading="testingKeyId === row._row_key" :disabled="!!testingKeyId && testingKeyId !== row._row_key" @click="testKey(row)">测试可用性</t-button>
              <t-button variant="outline" size="small" @click="editKey(row)">编辑</t-button>
              <t-button variant="outline" size="small" theme="danger" @click="deleteKey(row)">删除</t-button>
            </t-space>
          </template>
        </t-table>
      </div>
      <section v-if="keyTestTarget" class="key-test-report" aria-live="polite" aria-label="Key 可用性测试结果">
        <strong>{{ keyTestTarget }} · {{ testingKeyId ? '正在测试…' : '测试结果' }}</strong>
        <p v-if="testingKeyId">正在检查账号和搜索接口，请等待。本次不轮换其他 Key，不自动重试。</p>
        <template v-else-if="keyTestResult">
          <p><t-tag :theme="probeTheme(keyTestResult.state)" class="key-status">{{ keyTestResult.summary }}</t-tag></p>
          <p class="section-desc">测试时间：{{ new Date(keyTestResult.tested_at).toLocaleString() }}；结果仅代表本次请求。</p>
          <p class="key-test-query">使用已保存的主查询关键词：{{ keyTestResult.query }}</p>
          <div v-for="step in keyTestResult.steps" :key="step.kind" class="key-test-step">
            <strong>{{ step.kind === 'account' ? '账号接口' : '搜索接口' }} · {{ probeStateLabel(step.state) }}</strong>
            <p v-if="step.endpoint">{{ step.method }} {{ step.endpoint }}</p>
            <p v-if="step.http_status !== null">HTTP {{ step.http_status }} · 业务码 {{ step.code || '-' }} · {{ step.elapsed_ms }} ms</p>
            <p>{{ step.message }}</p>
          </div>
        </template>
        <p v-else-if="keyTestError">{{ keyTestError }}。本次未确认可用性，不代表 Key 失效。</p>
      </section>
    </t-card>

    <div class="scan-config-toolbar" aria-label="采集配置操作">
      <div class="toolbar-copy">
        <div class="toolbar-title-row">
          <span class="toolbar-title">采集配置</span>
          <span class="toolbar-note">保存一次会提交下面所有采集参数和高级策略</span>
        </div>
        <div class="toolbar-pills">
          <span class="toolbar-pill">{{ provinceBadgeText }}</span>
          <span class="toolbar-pill">关键词：{{ searchKeywordCount }} 条</span>
          <span class="toolbar-pill">{{ cScanStatusLabel }}</span>
          <span class="toolbar-pill">{{ scheduleBadgeText }}</span>
          <span class="toolbar-pill toolbar-pill--accent">{{ strategyBadgeText }}</span>
        </div>
      </div>

      <t-space class="toolbar-actions">
        <t-button variant="outline" @click="reloadConfig">
          <template #icon><RefreshIcon /></template>
          重新加载
        </t-button>
        <t-button class="scan-config-save-button" theme="primary" :loading="saving" :disabled="!configLoaded" @click="saveScanConfig">
          <template #icon><SaveIcon /></template>
          保存配置
        </t-button>
      </t-space>
    </div>

    <t-card size="small" :bordered="false" class="config-card workspace-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">采集参数</div>
          <p class="section-desc">常用参数集中在这里：范围、平台采集量、C 段扩展和定时执行，调整后用上方按钮统一保存。</p>
        </div>

        <div class="config-header-pills">
          <span class="config-pill">{{ provinceBadgeText }}</span>
          <span class="config-pill config-pill--accent">{{ cScanStatusLabel }}</span>
        </div>
      </div>

      <div class="config-panel-grid">
        <section class="config-panel">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">范围与来源</div>
            <h3>省份与运营商</h3>
            <p>省份与运营商筛选作用于 API 主查询及质量画像。历史热点、社区源、DDGS 和全国补扫使用各自来源范围。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>省份范围</label>
                <span>留空表示全国范围，可直接搜索省份名后批量选择。</span>
              </div>

              <div class="province-card">
                <div class="province-toolbar">
                  <div class="province-summary">
                    <span class="province-summary-main">{{ provinceSummary }}</span>
                    <span class="province-summary-sub">已选 {{ scanCfg.selected_provinces.length }} / {{ PROVINCES.length }} 个省份</span>
                  </div>

                  <t-button
                    variant="outline"
                    size="small"
                    @click="toggleSelectAllProv"
                  >{{ isAllProvincesSelected ? '取消全选' : '全选' }}</t-button>
                </div>

                <t-select
                  v-model="scanCfg.selected_provinces"
                  multiple
                  filterable
                  clearable
                  :min-collapsed-num="4"
                  :options="provinceOptions"
                  placeholder="搜索并选择省份"
                  class="province-select"
                  :popup-props="{ overlayInnerStyle: { maxHeight: '320px' } }"
                />
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>C 段单段 IP 上限</label>
                <span>每个命中 /24 最多补扫的邻近 IP 数；命中的原始 IP 不会重复探测。</span>
              </div>
              <t-input-number v-model="scanCfg.c_scan_limit" :min="1" :max="5000" :step="10" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>C 段全局网段上限</label>
                <span>单轮所有平台共享的 /24:端口扩展次数，避免多个平台重复消耗预算。</span>
              </div>
              <t-input-number v-model="scanCfg.c_segment_max_segments" :min="1" :max="50" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>C 段全局 IP 上限</label>
                <span>单轮所有扩展探测共享的 IP 总预算。</span>
              </div>
              <t-input-number v-model="scanCfg.c_segment_max_total_ips" :min="1" :max="5000" :step="10" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>单来源 C 段上限</label>
                <span>每个平台或质量画像最多占用的扩展网段数，保证多个来源都有补量机会。</span>
              </div>
              <t-input-number v-model="scanCfg.c_segment_per_source_max_segments" :min="1" :max="50" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>单来源 C 段 IP 上限</label>
                <span>同一平台或质量画像最多占用的扩展 IP 数，防止早到任务抢占总预算。</span>
              </div>
              <t-input-number v-model="scanCfg.c_segment_per_source_max_ips" :min="1" :max="5000" :step="10" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>运营商</label>
                <span>只看特定网络环境时可以缩小到电信、联通、移动或广电。</span>
              </div>
              <t-select v-model="scanCfg.operator" clearable :options="operatorOptions" placeholder="全部运营商" class="field-control field-control--wide" />
            </div>
          </div>
        </section>

        <section class="config-panel config-panel--accent">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">策略与调度</div>
            <h3>采集规模与定时</h3>
            <p>这里控制每轮采集量、是否启用 C 段扩展探测，以及后台自动执行的时间安排。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>采集数量</label>
                <span>各平台在每个所选省份的主查询目标条数；多省份会累加，画像预算另计。</span>
              </div>

              <div class="scan-size-grid">
                <div class="scan-size-item">
                  <label>Quake 360</label>
                  <t-input-number v-model="scanCfg.quake_size" :min="1" :max="10000" :step="1" size="small" />
                </div>
                <div class="scan-size-item">
                  <label>Hunter 鹰图</label>
                  <t-input-number v-model="scanCfg.hunter_size" :min="1" :max="10000" :step="1" size="small" />
                </div>
                <div class="scan-size-item">
                  <label>DayDayMap</label>
                  <t-input-number v-model="scanCfg.daydaymap_size" :min="1" :max="10000" :step="1" size="small" />
                </div>
                <div class="scan-size-item">
                  <label>Fofa</label>
                  <t-input-number v-model="scanCfg.fofa_size" :min="1" :max="10000" :step="1" size="small" />
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>采集平台</label>
                <span>留空按省积分策略自动选择；勾选后仅使用所选平台的 Key。</span>
              </div>
              <t-checkbox-group v-model="scanCfg.enabled_platforms" :options="platformOptions" />
            </div>
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>省积分模式</label>
                <span>未指定平台时按 Quake、FOFA、Hunter、DayDayMap 顺序选一个；跳过独立补扫和宽泛域名搜索。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.cost_saver_mode" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.cost_saver_mode ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.cost_saver_mode ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
                <div class="field-inline-hint">
                  {{ costSaverHint }}
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>C 段探测</label>
                <span>开启后会围绕已命中的可用 IP 扩展同网段探测，能补量，但会增加请求数。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.enable_c_scan" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.enable_c_scan ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.enable_c_scan ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
                <div class="field-inline-hint">
                  {{ cScanHint }}
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>复检后自动拓展</label>
                <span>定时或手动复检结束后，从本轮质量达标的候选源探测同一 C 段。需要同时开启“C 段探测”；不消耗 FOFA 等搜索 API 额度。</span>
              </div>
              <t-switch v-model="scanCfg.detection_expansion_enabled" :label="['开启', '关闭']" />
              <div class="field-inline-hint">仅处理公网 IPv4 的 HTTP 源及原端口，跳过内网、域名和 HTTPS 源。新频道经过深测后入池，每轮最多运行 120 秒；同一网段/端口的冷却记录在重启后仍有效。</div>
            </div>
            <div v-for="field in expansionFields" :key="field.key" class="config-field">
              <div class="config-field-meta">
                <label>{{ field.label }}</label>
                <span>{{ field.hint }}</span>
              </div>
              <t-input-number v-model="scanCfg[field.key]" :min="1" :max="field.max" class="field-control" />
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>DDGS 搜索</label>
                <span>通过 DuckDuckGo 搜索引擎发现 IPTV 源站，作为 API 平台之外的补充来源。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.ddgs_enabled" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.ddgs_enabled ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.ddgs_enabled ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
                <div class="field-inline-hint">
                  {{ scanCfg.ddgs_enabled ? '将通过搜索引擎查找公开 IPTV 源，增加覆盖面但会消耗额外时间。' : '当前仅使用 API 平台（Quake/Hunter/DayDayMap/Fofa）进行采集。' }}
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>定时采集</label>
                <span>关闭每天执行并清空星期，即可停用定时采集。时间使用北京时间。</span>
              </div>

              <div class="schedule-card">
                <t-checkbox-group v-model="scanCfg.update_days" :options="weekdayOptions" class="weekday-group" />

                <div class="schedule-row">
                  <t-time-picker v-model="scanCfg.update_time" format="HH:mm" class="schedule-time" />
                  <t-checkbox v-model="scanCfg.daily_full_update" @change="onDailyFullChange">每天</t-checkbox>
                </div>

                <div class="schedule-summary">{{ scheduleSummary }}</div>
                <div v-if="countdownText" class="countdown-text">{{ countdownText }}</div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </t-card>

    <t-card size="small" :bordered="false" class="config-card workspace-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">搜索关键词</div>
          <p class="section-desc">关键词保存在数据库采集配置中，每次新采集都会读取最新内容，并自动转换为 Quake、Hunter、DayDayMap 和 Fofa 各自的查询语法。</p>
        </div>

        <div class="config-header-pills">
          <span class="config-pill">当前 {{ searchKeywordCount }} 条</span>
          <t-button variant="outline" size="small" @click="appendRecommendedKeywords">补充推荐规则</t-button>
          <t-button variant="outline" size="small" @click="resetSearchKeywords">恢复默认</t-button>
        </div>
      </div>

      <section class="config-panel search-keywords-panel">
        <div class="config-field config-field--stack">
          <div class="config-field-meta">
            <label>主采集搜索规则</label>
            <span>每行一条，各行之间为“或”，匹配任意一条即可；默认搜索正文，用 <code>&amp;&amp;</code> 连接同一页面必须同时包含的特征，用 <code>title:</code> 搜索标题。空行、重复项和以 # 开头的注释会自动忽略。</span>
          </div>
          <t-textarea
            v-model="scanCfg.search_keywords"
            placeholder="/iptv/live/zh_cn.js&#10;/tsfile/live/&#10;title:Tvheadend"
            :autosize="{ minRows: 7, maxRows: 14 }"
            class="search-keywords-editor"
          />
          <div class="field-inline-hint">
            推荐规则覆盖酒店 IPTV、TXIPTV、ZHGXTV、直播频道 JSON 列表和 Tvheadend；TXIPTV 不再限定固定 key。点击“补充推荐规则”会保留现有内容，保存后用于下一轮采集。
          </div>
          <div class="field-inline-hint">
            更多规则用于扩大候选来源，不保证每类结果都被取回。可开启下方“质量优先查询”，按接口类型分配画像预算；预算总量不变，覆盖更多类型时每类分到的数量会减少。
          </div>
          <div class="field-inline-hint">
            “高清 / 4K / CCTV”等正文关键词不能证明实际画质，还可能漏掉未标注的好源。频道质量以实际测速和后续复检为准；建议结合下方最低带宽、最大延迟、最低稳定性及历史质量热点筛选。
          </div>
        </div>
      </section>
    </t-card>

    <t-card size="small" :bordered="false" class="config-card workspace-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">高级采集策略</div>
          <p class="section-desc">补源和智能发现放在这一块。它们和基础参数共用同一份采集配置，保存入口保持一致。</p>
        </div>

        <div class="config-header-pills">
          <span class="config-pill">{{ strategyBadgeText }}</span>
          <span class="config-pill config-pill--accent">{{ communityBadgeText }}</span>
        </div>
      </div>

      <div class="config-panel-grid">
        <section class="config-panel">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">ISP 智能分析</div>
            <h3>质量优先发现</h3>
            <p>优先使用高价值查询和历史高质量网段，把采集预算更多花在稳定源附近。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>质量优先查询</label>
                <span>额外执行 TXIPTV、直播接口、ZHGXTV、Tvheadend 等高价值画像查询。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.quality_discovery_enabled" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.quality_discovery_enabled ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.quality_discovery_enabled ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>画像查询预算</label>
                <span>质量画像每个平台的总搜索目标量，会按已选省份和画像拆分。</span>
              </div>
              <t-input-number v-model="scanCfg.quality_query_profile_size" :min="10" :max="2000" :step="10" class="field-control" />
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>质量热点补源</label>
                <span>围绕历史高稳定、低延迟、高带宽源所在网段继续探测。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.quality_hotspot_enabled" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.quality_hotspot_enabled ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.quality_hotspot_enabled ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>热点探测预算</label>
                <span>每轮质量热点最多探测的 IP:端口候选数量。</span>
              </div>
              <t-input-number v-model="scanCfg.quality_hotspot_scan_limit" :min="1" :max="5000" :step="10" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最低稳定性</label>
                <span>低于该稳定性的数据不参与质量热点学习。</span>
              </div>
              <t-input-number v-model="scanCfg.quality_source_min_stability" :min="0" :max="100" :step="5" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最低带宽 (MB/s)</label>
                <span>深度检测的硬性准入线；低于此值的频道不会通过深度检测。</span>
              </div>
              <t-input-number v-model="scanCfg.quality_thresholds.min_bandwidth_MBps" :min="0.001" :max="1000" :step="0.05" :decimal-places="3" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最大深测延迟 (ms)</label>
                <span>超过此延迟的频道会被深度检测硬性淘汰。</span>
              </div>
              <t-input-number v-model="scanCfg.quality_thresholds.max_delay_ms" :min="1" :max="120000" :step="100" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>深测最低稳定性</label>
                <span>低于此稳定性即使带宽足够也不会作为有效源入库。</span>
              </div>
              <t-input-number v-model="scanCfg.quality_thresholds.stability_low" :min="0" :max="100" :step="5" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>深测时长</label>
                <span>采集流程统一深度检测的单源采样时长，手动复检和定时复检共用。</span>
              </div>
              <t-input-number v-model="scanCfg.deep_check_duration" :min="1" :max="120" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>深测采样</label>
                <span>单源深度检测至少读取的字节数，增大后更能暴露短时断流但采集更慢。</span>
              </div>
              <t-input-number v-model="scanCfg.deep_check_min_bytes" :min="4096" :max="10485760" :step="65536" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>深测超时</label>
                <span>单次深度检测请求超时，过低会误杀慢启动源，过高会拖慢批次。</span>
              </div>
              <t-input-number v-model="scanCfg.deep_check_request_timeout" :min="2" :max="120" :step="1" class="field-control" />
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>ISP Intelligence</label>
                <span>启用基于运营商的智能热点段识别。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.isp_intelligence_enabled" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.isp_intelligence_enabled ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.isp_intelligence_enabled ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
                <div class="field-inline-hint">
                  {{ scanCfg.isp_intelligence_enabled ? '将分析 ISP 数据识别热门网段，优先探测高价值区域。' : '当前使用标准采集模式，不进行 ISP 智能分析。' }}
                </div>
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最小频道数</label>
                <span>热点段最少需要包含的频道数量。</span>
              </div>
              <t-input-number v-model="scanCfg.hot_segment_min_channels" :min="1" :max="100" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>热点 IP 探测预算</label>
                <span>本轮在热点网段内最多探测的 IP 数量。</span>
              </div>
              <t-input-number v-model="scanCfg.hot_segment_scan_limit" :min="1" :max="500" :step="10" class="field-control" />
            </div>
          </div>
        </section>

        <section class="config-panel config-panel--accent">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">社区源配置</div>
            <h3>Community Sources</h3>
            <p>从社区维护的源列表中获取 IPTV 数据，扩展采集覆盖面。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>社区源</label>
                <span>启用从社区源获取 IPTV 数据。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.community_sources_enabled" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.community_sources_enabled ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.community_sources_enabled ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
                <div class="field-inline-hint">
                  {{ scanCfg.community_sources_enabled ? '将从社区维护的源获取数据，增加覆盖面但会消耗额外时间。' : '当前不读取社区列表，其余启用的采集来源继续执行。' }}
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>社区源 URL</label>
                <span>每行一个 M3U 文件直链（含 #EXTINF），追加到内置列表；GitHub 请填写 Raw 文件地址。</span>
              </div>
              <t-textarea
                v-model="scanCfg.community_source_urls"
                placeholder="https://raw.githubusercontent.com/user/repo/main/iptv.m3u&#10;https://example.com/iptv.m3u"
                :autosize="{ minRows: 3, maxRows: 6 }"
                class="field-control field-control--wide"
              />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>GitHub 代理</label>
                <span>GitHub 资源代理地址，留空表示不使用代理。</span>
              </div>
              <t-input v-model="scanCfg.github_proxy" placeholder="https://ghproxy.com/" class="field-control field-control--wide" />
            </div>
          </div>
        </section>
      </div>
    </t-card>

    <t-dialog
      v-model:visible="keyModalVisible"
      :header="keyModalTitle"
      :footer="false"
      width="420px"
      destroy-on-close
    >
      <t-form label-width="80px">
        <t-form-item label="平台">
          <t-select v-model="keyForm.platform" :disabled="keyEditMode" style="width: 100%">
            <t-option value="quake" label="Quake 360" />
            <t-option value="hunter" label="Hunter 鹰图" />
            <t-option value="daydaymap" label="DayDayMap" />
            <t-option value="fofa" label="Fofa" />
          </t-select>
          <div class="platform-link">
            <t-link
              :href="platformLinkMap[keyForm.platform]"
              target="_blank"
              theme="primary"
              size="small"
            >
              前往 {{ platformLabelMap[keyForm.platform] || keyForm.platform }} 官网获取 Key ↗
            </t-link>
          </div>
        </t-form-item>

        <t-form-item label="API Key">
          <t-input
            v-model="keyForm.key"
            type="password"
            :placeholder="keyEditMode ? '输入用于替换的新 Key（原 Key 不会回显）' : '粘贴 API Key'"
            autocomplete="new-password"
          />
        </t-form-item>

        <t-form-item v-if="keyForm.platform === 'fofa'" label="Email（选填）">
          <t-input v-model="keyForm.email" placeholder="兼容旧配置，当前 API 仅需 Key" />
        </t-form-item>
      </t-form>

      <t-space class="dialog-actions">
        <t-button variant="outline" @click="keyModalVisible = false">取消</t-button>
        <t-button theme="primary" @click="submitKey">{{ keyEditMode ? '保存' : '添加' }}</t-button>
      </t-space>
    </t-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next/es/message/index.mjs'
import { DialogPlugin } from 'tdesign-vue-next/es/dialog/index.mjs'
import RefreshIcon from 'tdesign-icons-vue-next/esm/components/refresh.js'
import SaveIcon from 'tdesign-icons-vue-next/esm/components/save.js'
import {
  apiSaveScanConfig,
  apiScanConfig,
  apiScanKeyAdd,
  apiScanKeyDelete,
  apiScanKeys,
  apiScanKeysCredits,
  apiScanKeyUpdate,
  apiScanKeyTest,
} from '../api.js'

const saving = ref(false)
const keyList = ref([])
const keysLoading = ref(false)
const keyModalVisible = ref(false)
const keyModalTitle = ref('添加 API Key')
const keyEditMode = ref(false)
const keyForm = reactive({ platform: 'quake', key: '', email: '' })
const oldKey = ref('')
const testingKeyId = ref('')
const keyTestTarget = ref('')
const keyTestResult = ref(null)
const keyTestError = ref('')

function probeTheme(state) {
  return state === 'passed' ? 'success' : state === 'auth_failed' ? 'danger' : 'warning'
}
function probeStateLabel(state) {
  return { passed: '通过', auth_failed: '认证失败', permission_denied: '权限受限',
    quota_exhausted: '额度不足', rate_limited: '请求限流', unavailable: '服务异常',
    api_error: '平台拒绝请求', unknown: '无法判断', skipped: '未提供 API Key 账号接口' }[state] || '无法判断'
}
async function testKey(row) {
  if (testingKeyId.value) return
  testingKeyId.value = row._row_key
  keyTestTarget.value = `${platformLabelMap[row.platform] || row.platform} ${row.key_suffix}`
  keyTestResult.value = null
  keyTestError.value = ''
  try {
    keyTestResult.value = await apiScanKeyTest(row.platform, row.key_id)
  } catch (error) {
    keyTestError.value = error.message || '测试请求失败'
  } finally {
    testingKeyId.value = ''
  }
}

const platformLabelMap = {
  quake: 'Quake 360',
  hunter: 'Hunter 鹰图',
  daydaymap: 'DayDayMap',
  fofa: 'Fofa',
}

const platformLinkMap = {
  quake: 'https://quake.360.net/',
  hunter: 'https://hunter.qianxin.com/',
  daydaymap: 'https://www.daydaymap.com/',
  fofa: 'https://fofa.info/',
}

const DEFAULT_SEARCH_KEYWORDS = [
  '/tsfile/live/',
  '/iptv/live/zh_cn.js',
  '/iptv/live/1000.json',
  '/ZHGXTV/Public/json/live_interface.txt',
  '/channel_list.json',
  '/api/live/channels',
  '/live/channels.json',
  'title:Tvheadend',
]

const expansionFields = [
  { key: 'detection_expansion_max_ips', label: '复检拓展 IP 上限', hint: '每轮探测的相邻 IP 总数，与采集时的 C 段预算分别计算。', max: 200, default: 50 },
  { key: 'detection_expansion_max_segments', label: '复检拓展网段上限', hint: '每轮最多处理的网段/端口组合，优先从稳定性较高的源拓展。', max: 10, default: 2 },
  { key: 'detection_expansion_cooldown_hours', label: '网段冷却时间（小时）', hint: '同一网段/端口两次拓展的最短间隔，超时或取消也进入冷却。', max: 720, default: 24 },
  { key: 'detection_expansion_max_channels', label: '新候选深测上限', hint: '每轮最多检测的新频道数；质量不达标不入池，重复 URL 跳过。', max: 200, default: 50 },
]

const scanCfg = reactive({
  detection_expansion_enabled: true,
  ...Object.fromEntries(expansionFields.map(field => [field.key, field.default])),
  enabled_platforms: [],
  selected_provinces: [],
  operator: '',
  quake_size: 200,
  hunter_size: 200,
  daydaymap_size: 200,
  search_keywords: DEFAULT_SEARCH_KEYWORDS.join('\n'),
  cost_saver_mode: true,
  enable_c_scan: true,
  c_scan_limit: 50,
  c_segment_max_segments: 8,
  c_segment_max_total_ips: 200,
  c_segment_per_source_max_segments: 2,
  c_segment_per_source_max_ips: 50,
  update_time: '03:00',
  update_days: [0, 1, 2, 3, 4, 5, 6],
  daily_full_update: true,
  ddgs_enabled: false,
  quality_discovery_enabled: true,
  quality_query_profile_size: 120,
  quality_hotspot_enabled: true,
  quality_hotspot_scan_limit: 120,
  quality_hotspot_min_score: 8,
  quality_source_min_stability: 45,
  quality_thresholds: {
    stability_high: 60,
    stability_low: 30,
    max_delay_ms: 2000,
    min_bandwidth_MBps: 0.3,
  },
  deep_check_duration: 6,
  deep_check_min_bytes: 131072,
  deep_check_request_timeout: 10,
  isp_intelligence_enabled: false,
  hot_segment_min_channels: 3,
  hot_segment_scan_limit: 200,
  community_sources_enabled: false,
  community_source_urls: '',
  github_proxy: '',
  fofa_api_key: '',
  fofa_email: '',
  fofa_size: 200,
})

const configLoaded = ref(false)
const savedSnapshot = ref('')
const isDirty = computed(() => configLoaded.value && JSON.stringify(scanCfg) !== savedSnapshot.value)
const platformOptions = [
  { label: 'Quake 360', value: 'quake' }, { label: 'Hunter 鹰图', value: 'hunter' },
  { label: 'FOFA', value: 'fofa' }, { label: 'DayDayMap', value: 'daydaymap' },
]

const PROVINCES = [
  '北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江', '江苏',
  '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '海南',
  '四川', '贵州', '云南', '陕西', '甘肃', '青海', '台湾', '内蒙古', '广西', '西藏',
  '宁夏', '新疆', '香港', '澳门',
]

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000

const provinceOptions = PROVINCES.map((province) => ({
  label: province,
  value: province,
}))

const operatorOptions = [
  { label: '全部', value: '' },
  { label: '电信', value: '电信' },
  { label: '联通', value: '联通' },
  { label: '移动', value: '移动' },
  { label: '广电', value: '广电' },
]

const weekdayOptions = WEEKDAY_LABELS.map((label, index) => ({
  label,
  value: index,
}))

const fofaBalanceLabels = [
  { key: 'fofa_point', label: 'F 点' },
  { key: 'fcoin', label: 'F 币' },
  { key: 'remain_free_point', label: '免费 F 点' },
  { key: 'remain_api_query', label: '月度查询剩余次数' },
  { key: 'remain_api_data', label: '月度数据剩余条数' },
]

const keyColumns = [
  { colKey: 'platform', title: '平台', width: 120 },
  { colKey: 'key_suffix', title: 'Key', width: 150 },
  { colKey: 'credit', title: '余额 / 配额', width: 240 },
  { colKey: 'status', title: '状态', width: 140 },
  { colKey: 'actions', title: '操作', width: 260 },
]

const provinceSummary = computed(() => {
  const count = scanCfg.selected_provinces.length
  if (!count) return '未限制省份'
  if (count === PROVINCES.length) return '已选择全部省份'
  if (count <= 4) return `已选：${scanCfg.selected_provinces.join('、')}`
  return `已选 ${count} 个省份`
})

const normalizedSearchKeywords = computed(() => (
  (scanCfg.search_keywords || '')
    .split('\n')
    .map(keyword => keyword.trim())
    .filter(keyword => keyword && !keyword.startsWith('#'))
))

const searchKeywordCount = computed(() => new Set(normalizedSearchKeywords.value).size)

const provinceBadgeText = computed(() => {
  const count = scanCfg.selected_provinces.length
  return count ? `范围：${count} 省` : '范围：全国'
})

const cScanStatusLabel = computed(() => (
  scanCfg.enable_c_scan ? 'C段探测：已启用' : 'C段探测：已关闭'
))

const scheduleBadgeText = computed(() => {
  const time = scanCfg.update_time || '03:00'
  if (scanCfg.daily_full_update) return `定时：每天 ${time}`
  const count = scanCfg.update_days?.length || 0
  return count ? `定时：每周 ${count} 天 ${time}` : '定时：已停用'
})

const enabledStrategyCount = computed(() => ([
  scanCfg.cost_saver_mode,
  scanCfg.ddgs_enabled,
  scanCfg.quality_discovery_enabled,
  scanCfg.quality_hotspot_enabled,
  scanCfg.isp_intelligence_enabled,
  scanCfg.community_sources_enabled,
].filter(Boolean).length))

const strategyBadgeText = computed(() => `策略：${enabledStrategyCount.value} 项启用`)

const communityBadgeText = computed(() => (
  scanCfg.community_sources_enabled ? '社区源：已启用' : '社区源：已关闭'
))

const cScanHint = computed(() => (
  scanCfg.enable_c_scan
    ? `当前会围绕已命中的网段继续扩展探测，全局最多 ${scanCfg.c_segment_max_segments} 段 / ${scanCfg.c_segment_max_total_ips} IP。`
    : '当前只使用主搜索结果，不做同网段扩展，速度更快，也更省额度。'
))

const costSaverHint = computed(() => (
  scanCfg.cost_saver_mode
    ? '未选平台时只使用一个可用平台；独立 Tvheadend、IPTV 互动和域名补扫关闭，画像预算仍可单独控制。'
    : '未选平台时使用所有可用 Key；已勾选平台时遵循勾选范围。独立补扫可能产生额外 API 消耗。'
))

const scheduleSummary = computed(() => {
  const time = scanCfg.update_time || '03:00'
  if (scanCfg.daily_full_update) {
    return `执行计划：每天 ${time}（北京时间）`
  }

  const labels = (scanCfg.update_days || [])
    .map((index) => WEEKDAY_LABELS[index])
    .filter(Boolean)

  if (!labels.length) {
    return '执行计划：未选择采集日'
  }
  return `执行计划：${labels.join('、')} ${time}（北京时间）`
})


function statusTheme(status) {
  if (status === '正常') return 'success'
  if (status === '偏低') return 'warning'
  if (/未知|有效/.test(status)) return 'primary'
  return 'danger'
}

function formatCredit(credit, roleLimit) {
  const current = credit != null
    ? Number(credit).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : '-'
  if (roleLimit != null) {
    return `${current} / ${Number(roleLimit).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  }
  return current
}

function selectAllProv() {
  scanCfg.selected_provinces = [...PROVINCES]
}

function clearAllProv() {
  scanCfg.selected_provinces = []
}

const isAllProvincesSelected = computed(() => scanCfg.selected_provinces.length === PROVINCES.length)

function toggleSelectAllProv() {
  if (isAllProvincesSelected.value) {
    scanCfg.selected_provinces = []
  } else {
    scanCfg.selected_provinces = [...PROVINCES]
  }
}

function resetSearchKeywords() {
  scanCfg.search_keywords = DEFAULT_SEARCH_KEYWORDS.join('\n')
}

function appendRecommendedKeywords() {
  const existing = scanCfg.search_keywords || ''
  const rules = new Set(existing.split('\n').map(line => line.trim()))
  const additions = DEFAULT_SEARCH_KEYWORDS.filter(rule => !rules.has(rule))
  if (!additions.length) {
    MessagePlugin.success('已包含全部推荐规则')
    return
  }
  scanCfg.search_keywords = [existing.trimEnd(), ...additions].filter(Boolean).join('\n')
  MessagePlugin.success(`已补充 ${additions.length} 条推荐规则，保存后生效`)
}

function onDailyFullChange() {
  if (scanCfg.daily_full_update) {
    scanCfg.update_days = [0, 1, 2, 3, 4, 5, 6]
  }
}

function getBeijingTargetMs(dayOffset, hour, minute) {
  const nowInBeijing = new Date(Date.now() + BEIJING_OFFSET_MS)
  return Date.UTC(
    nowInBeijing.getUTCFullYear(),
    nowInBeijing.getUTCMonth(),
    nowInBeijing.getUTCDate() + dayOffset,
    hour,
    minute,
    0,
    0,
  ) - BEIJING_OFFSET_MS
}

const countdownText = ref('')
let countdownTimer = null

function updateCountdown() {
  if (!scanCfg.update_time || (!scanCfg.update_days?.length && !scanCfg.daily_full_update)) {
    countdownText.value = ''
    return
  }

  const parts = (scanCfg.update_time || '03:00').split(':')
  const parsedHour = Number.parseInt(parts[0], 10)
  const parsedMinute = Number.parseInt(parts[1], 10)
  const hour = Number.isInteger(parsedHour) && parsedHour >= 0 && parsedHour <= 23 ? parsedHour : 3
  const minute = Number.isInteger(parsedMinute) && parsedMinute >= 0 && parsedMinute <= 59 ? parsedMinute : 0
  const days = scanCfg.daily_full_update ? [0, 1, 2, 3, 4, 5, 6] : scanCfg.update_days

  if (!days?.length) {
    countdownText.value = '未设置采集日'
    return
  }

  const nowMs = Date.now()
  let targetMs = null

  for (let dayOffset = 0; dayOffset < 8; dayOffset += 1) {
    const candidateMs = getBeijingTargetMs(dayOffset, hour, minute)
    const candidateInBeijing = new Date(candidateMs + BEIJING_OFFSET_MS)

    const jsDay = candidateInBeijing.getUTCDay()
    const weekday = jsDay === 0 ? 6 : jsDay - 1

    if (days.includes(weekday) && candidateMs > nowMs) {
      targetMs = candidateMs
      break
    }
  }

  if (!targetMs) {
    countdownText.value = '未找到匹配时间'
    return
  }

  const diff = targetMs - Date.now()
  const totalSeconds = Math.floor(diff / 1000)
  const daysLeft = Math.floor(totalSeconds / 86400)
  const remain = totalSeconds % 86400
  const hoursLeft = Math.floor(remain / 3600)
  const minutesLeft = Math.floor((remain % 3600) / 60)
  const secondsLeft = remain % 60
  const pad = (value) => (value < 10 ? `0${value}` : `${value}`)

  countdownText.value = daysLeft > 0
    ? `下次采集：${daysLeft}天 ${pad(hoursLeft)}:${pad(minutesLeft)}:${pad(secondsLeft)}`
    : `下次采集：${pad(hoursLeft)}:${pad(minutesLeft)}:${pad(secondsLeft)}`
}

async function reloadConfig() {
  if (await canLeave()) await loadConfig()
}

async function loadConfig() {
  try {
    const cfg = await apiScanConfig()
    scanCfg.enabled_platforms = Array.isArray(cfg.enabled_platforms) ? cfg.enabled_platforms : []
    scanCfg.selected_provinces = Array.isArray(cfg.selected_provinces) ? cfg.selected_provinces : []
    scanCfg.operator = cfg.operator || ''
    scanCfg.quake_size = typeof cfg.quake_size === 'number' ? cfg.quake_size : 200
    scanCfg.hunter_size = typeof cfg.hunter_size === 'number' ? cfg.hunter_size : 200
    scanCfg.daydaymap_size = typeof cfg.daydaymap_size === 'number' ? cfg.daydaymap_size : 200
    scanCfg.search_keywords = Array.isArray(cfg.search_keywords)
      ? cfg.search_keywords.join('\n')
      : (cfg.search_keywords || DEFAULT_SEARCH_KEYWORDS.join('\n'))
    scanCfg.cost_saver_mode = cfg.cost_saver_mode !== false
    scanCfg.enable_c_scan = cfg.enable_c_scan !== false
    scanCfg.detection_expansion_enabled = cfg.detection_expansion_enabled !== false
    for (const field of expansionFields) {
      scanCfg[field.key] = typeof cfg[field.key] === 'number' ? cfg[field.key] : field.default
    }
    scanCfg.c_scan_limit = typeof cfg.c_scan_limit === 'number' ? cfg.c_scan_limit : 50
    scanCfg.c_segment_max_segments = typeof cfg.c_segment_max_segments === 'number' ? cfg.c_segment_max_segments : 8
    scanCfg.c_segment_max_total_ips = typeof cfg.c_segment_max_total_ips === 'number' ? cfg.c_segment_max_total_ips : 200
    scanCfg.c_segment_per_source_max_segments = typeof cfg.c_segment_per_source_max_segments === 'number' ? cfg.c_segment_per_source_max_segments : 2
    scanCfg.c_segment_per_source_max_ips = typeof cfg.c_segment_per_source_max_ips === 'number' ? cfg.c_segment_per_source_max_ips : 50
    scanCfg.update_time = cfg.update_time || '03:00'
    scanCfg.update_days = Array.isArray(cfg.update_days) ? cfg.update_days : [0, 1, 2, 3, 4, 5, 6]
    scanCfg.daily_full_update = cfg.daily_full_update !== false
    scanCfg.ddgs_enabled = !!cfg.ddgs_enabled
    scanCfg.quality_discovery_enabled = cfg.quality_discovery_enabled !== false
    scanCfg.quality_query_profile_size = typeof cfg.quality_query_profile_size === 'number' ? cfg.quality_query_profile_size : 120
    scanCfg.quality_hotspot_enabled = cfg.quality_hotspot_enabled !== false
    scanCfg.quality_hotspot_scan_limit = typeof cfg.quality_hotspot_scan_limit === 'number' ? cfg.quality_hotspot_scan_limit : 120
    scanCfg.quality_hotspot_min_score = typeof cfg.quality_hotspot_min_score === 'number' ? cfg.quality_hotspot_min_score : 8
    scanCfg.quality_source_min_stability = typeof cfg.quality_source_min_stability === 'number' ? cfg.quality_source_min_stability : 45
    const thresholds = cfg.quality_thresholds || {}
    scanCfg.quality_thresholds = {
      stability_high: typeof thresholds.stability_high === 'number' ? thresholds.stability_high : 60,
      stability_low: typeof thresholds.stability_low === 'number' ? thresholds.stability_low : 30,
      max_delay_ms: typeof thresholds.max_delay_ms === 'number' ? thresholds.max_delay_ms : 2000,
      min_bandwidth_MBps: typeof thresholds.min_bandwidth_MBps === 'number' ? thresholds.min_bandwidth_MBps : 0.3,
    }
    scanCfg.deep_check_duration = typeof cfg.deep_check_duration === 'number' ? cfg.deep_check_duration : 6
    scanCfg.deep_check_min_bytes = typeof cfg.deep_check_min_bytes === 'number' ? cfg.deep_check_min_bytes : 131072
    scanCfg.deep_check_request_timeout = typeof cfg.deep_check_request_timeout === 'number' ? cfg.deep_check_request_timeout : 10
    scanCfg.isp_intelligence_enabled = !!cfg.isp_intelligence_enabled
    scanCfg.hot_segment_min_channels = typeof cfg.hot_segment_min_channels === 'number' ? cfg.hot_segment_min_channels : 3
    scanCfg.hot_segment_scan_limit = typeof cfg.hot_segment_scan_limit === 'number' ? cfg.hot_segment_scan_limit : 200
    scanCfg.community_sources_enabled = !!cfg.community_sources_enabled
    scanCfg.community_source_urls = Array.isArray(cfg.community_source_urls) ? cfg.community_source_urls.join('\n') : (cfg.community_source_urls || '')
    scanCfg.github_proxy = cfg.github_proxy || ''
    scanCfg.fofa_api_key = cfg.fofa_api_key || ''
    scanCfg.fofa_email = cfg.fofa_email || ''
    scanCfg.fofa_size = typeof cfg.fofa_size === 'number' ? cfg.fofa_size : 200
    savedSnapshot.value = JSON.stringify(scanCfg)
    configLoaded.value = true
    updateCountdown()
  } catch (_) {
    configLoaded.value = false
    MessagePlugin.error('加载采集配置失败，请重新打开页面后再保存')
  }
}

function validateScanConfig() {
  const errors = []
  if (scanCfg.fofa_email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(scanCfg.fofa_email)) {
    errors.push('Fofa 邮箱格式不正确')
  }
  if (!searchKeywordCount.value) {
    errors.push('请至少保留一条搜索关键词')
  }
  if (normalizedSearchKeywords.value.some(rule => rule.split('&&').some(
    fragment => !fragment.trim().replace(/^(title|body):/i, '').trim(),
  ))) errors.push('关键词中不能包含空条件（例如 title: 或末尾的 &&）')
  if (searchKeywordCount.value > 100) {
    errors.push('搜索关键词不能超过 100 条')
  }
  if (normalizedSearchKeywords.value.some(keyword => keyword.length > 256)) {
    errors.push('单条搜索关键词不能超过 256 个字符')
  }
  if (scanCfg.quake_size > 10000) {
    errors.push('Quake 采集数量不能超过 10000')
  }
  if (scanCfg.hunter_size > 10000) {
    errors.push('Hunter 采集数量不能超过 10000')
  }
  if (scanCfg.daydaymap_size > 10000) {
    errors.push('DayDayMap 采集数量不能超过 10000')
  }
  if (scanCfg.fofa_size > 10000) {
    errors.push('Fofa 采集数量不能超过 10000')
  }
  if (scanCfg.quality_query_profile_size < 10 || scanCfg.quality_query_profile_size > 2000) {
    errors.push('画像查询预算需要在 10 到 2000 之间')
  }
  if (scanCfg.quality_hotspot_scan_limit < 1 || scanCfg.quality_hotspot_scan_limit > 5000) {
    errors.push('质量热点探测预算需要在 1 到 5000 之间')
  }
  if (scanCfg.quality_source_min_stability < 0 || scanCfg.quality_source_min_stability > 100) {
    errors.push('最低稳定性需要在 0 到 100 之间')
  }
  if (scanCfg.c_scan_limit < 1 || scanCfg.c_scan_limit > 5000) {
    errors.push('C 段单段 IP 上限需要在 1 到 5000 之间')
  }
  if (scanCfg.c_segment_max_segments < 1 || scanCfg.c_segment_max_segments > 50) {
    errors.push('C 段全局网段上限需要在 1 到 50 之间')
  }
  if (scanCfg.c_segment_max_total_ips < 1 || scanCfg.c_segment_max_total_ips > 5000) {
    errors.push('C 段全局 IP 上限需要在 1 到 5000 之间')
  }
  if (scanCfg.c_segment_per_source_max_segments < 1 || scanCfg.c_segment_per_source_max_segments > 50) {
    errors.push('单来源 C 段上限需要在 1 到 50 之间')
  }
  if (scanCfg.c_segment_per_source_max_ips < 1 || scanCfg.c_segment_per_source_max_ips > 5000) {
    errors.push('单来源 C 段 IP 上限需要在 1 到 5000 之间')
  }
  const thresholds = scanCfg.quality_thresholds || {}
  if (thresholds.min_bandwidth_MBps < 0.001 || thresholds.min_bandwidth_MBps > 1000) {
    errors.push('最低带宽需要在 0.001 到 1000 MB/s 之间')
  }
  if (thresholds.max_delay_ms < 1 || thresholds.max_delay_ms > 120000) {
    errors.push('最大深测延迟需要在 1 到 120000 ms 之间')
  }
  if (thresholds.stability_low < 0 || thresholds.stability_low > 100) {
    errors.push('深测最低稳定性需要在 0 到 100 之间')
  }
  for (const field of expansionFields) {
    if (!Number.isInteger(scanCfg[field.key]) || scanCfg[field.key] < 1 || scanCfg[field.key] > field.max) {
      errors.push(`${field.label}应为 1～${field.max} 的整数`)
    }
  }
  if (scanCfg.deep_check_duration < 1 || scanCfg.deep_check_duration > 120) {
    errors.push('深测时长需要在 1 到 120 秒之间')
  }
  if (scanCfg.deep_check_min_bytes < 4096 || scanCfg.deep_check_min_bytes > 10485760) {
    errors.push('深测采样需要在 4096 到 10485760 字节之间')
  }
  if (scanCfg.deep_check_request_timeout < 2 || scanCfg.deep_check_request_timeout > 120) {
    errors.push('深测超时需要在 2 到 120 秒之间')
  }
  const timeParts = (scanCfg.update_time || '').split(':')
  const hour = Number.parseInt(timeParts[0], 10)
  const minute = Number.parseInt(timeParts[1], 10)
  if (
    timeParts.length !== 2
    || !Number.isInteger(hour)
    || !Number.isInteger(minute)
    || hour < 0
    || hour > 23
    || minute < 0
    || minute > 59
  ) {
    errors.push('定时采集时间格式不正确')
  }
  if (scanCfg.github_proxy && !/^https?:\/\/.+/.test(scanCfg.github_proxy)) {
    errors.push('GitHub 代理地址格式不正确，需以 http:// 或 https:// 开头')
  }
  if (scanCfg.community_source_urls) {
    const urls = typeof scanCfg.community_source_urls === 'string'
      ? scanCfg.community_source_urls.split('\n').map(u => u.trim()).filter(Boolean)
      : scanCfg.community_source_urls
    for (const url of urls) {
      if (!/^https?:\/\/.+/.test(url)) {
        errors.push(`社区源 URL 格式不正确: ${url}`)
        break
      }
    }
  }
  return errors
}

async function saveScanConfig() {
  if (!configLoaded.value || saving.value) return false
  const errors = validateScanConfig()
  if (errors.length) {
    MessagePlugin.warning(errors[0])
    return
  }
  saving.value = true
  try {
    const data = { ...scanCfg }
    if (data.daily_full_update) {
      data.update_days = [0, 1, 2, 3, 4, 5, 6]
    }
    
    if (typeof data.community_source_urls === 'string') {
      data.community_source_urls = data.community_source_urls
        .split('\n')
        .map(url => url.trim())
        .filter(url => url)
    }
    if (typeof data.search_keywords === 'string') {
      data.search_keywords = [...new Set(
        data.search_keywords
          .split('\n')
          .map(keyword => keyword.trim())
          .filter(keyword => keyword && !keyword.startsWith('#')),
      )]
    }

    const res = await apiSaveScanConfig(data)
    // unwrap() 返回 json.data，成功时是配置对象
    MessagePlugin.success('采集配置已保存')
    if (res && typeof res === 'object') {
      // 保持 community_source_urls 为字符串格式（textarea 需要）
      const saved = { ...res }
      if (Array.isArray(saved.community_source_urls)) {
        saved.community_source_urls = saved.community_source_urls.join('\n')
      }
      if (Array.isArray(saved.search_keywords)) {
        saved.search_keywords = saved.search_keywords.join('\n')
      }
      for (const key of Object.keys(scanCfg)) {
        if (Object.hasOwn(saved, key)) scanCfg[key] = saved[key]
      }
    }
    savedSnapshot.value = JSON.stringify(scanCfg)
    updateCountdown()
    return true
  } catch (_) {
    MessagePlugin.error('保存失败')
    return false
  } finally {
    saving.value = false
  }
}

async function loadKeys() {
  if (keysLoading.value) return
  keysLoading.value = true
  try {
    // 1. 快速加载 Key 列表
    const res = await apiScanKeys()
    const keyItems = Array.isArray(res) ? res : (res?.items || [])
    keyList.value = keyItems.map((item) => ({
      ...item,
      key_suffix: item.suffix || item.key_suffix || '••••',
      _row_key: item.key_id || item.key || `${item.platform}:${item.suffix || item.key_suffix || ''}`,
      status: '加载中...',
      credit: null,
    }))
    
    // 2. 异步获取余额 (不阻塞列表显示)
    await apiScanKeysCredits().then(creditsData => {
      const creditsMap = {}
      const creditItems = Array.isArray(creditsData) ? creditsData : (creditsData?.items || [])
      ;creditItems.forEach(item => {
        const suffix = item.suffix || item.key_suffix || ''
        creditsMap[`${item.platform || ''}:${item.key_id || suffix}`] = item
        if (suffix) creditsMap[`suffix:${item.platform}:${suffix}`] = item
      })
        
        keyList.value = keyList.value.map(item => {
          const creditInfo = creditsMap[`${item.platform || ''}:${item.key_id || item.key_suffix}`]
            || creditsMap[`suffix:${item.platform}:${item.key_suffix}`]
          if (creditInfo) {
            let status = '正常'
            const credit = creditInfo.credit != null ? Number(creditInfo.credit) : null
            
            if (creditInfo.error) status = creditInfo.error
            else if (item.platform === 'fofa') status = creditInfo.verified ? 'Key有效' : '余额未知'
            else if (credit === null) {
              // 各平台无余额查询能力时的友好提示
              if (item.platform === 'daydaymap') status = creditInfo.role || 'Key有效 (余额需登录查看)'
              else status = creditInfo.role || '余额未知'
            }
            else if (credit < 100) status = '余额不足'
            else if (credit < 300) status = '偏低'
            
            return { ...item, ...creditInfo, status }
          }
          return { ...item, status: '余额未知' }
        })
    }).catch(err => {
      console.error('获取余额失败', err)
      // 余额查询失败时更新所有 Key 的状态，让用户知道已失败
      keyList.value = keyList.value.map(item => ({
        ...item,
        status: '余额查询失败',
      }))
      MessagePlugin.warning('余额查询失败：' + (err?.message || '请检查后端日志'))
    })
    
  } catch (error) {
    console.error('加载 Key 列表失败', error)
    MessagePlugin.error('刷新余额失败')
  } finally {
    keysLoading.value = false
  }
}

function openAddModal() {
  keyEditMode.value = false
  keyModalTitle.value = '添加 API Key'
  keyForm.platform = 'quake'
  keyForm.key = ''
  keyForm.email = ''
  oldKey.value = ''
  keyModalVisible.value = true
}

function editKey(row) {
  keyEditMode.value = true
  keyModalTitle.value = '编辑 API Key'
  keyForm.platform = row.platform
  keyForm.key = ''
  keyForm.email = row.platform === 'fofa' ? (row.email || scanCfg.fofa_email || '') : ''
  oldKey.value = row.key_id || row.key || ''
  keyModalVisible.value = true
}

async function submitKey() {
  if (!keyForm.key.trim()) {
    MessagePlugin.error('请输入 Key')
    return
  }
  const email = keyForm.platform === 'fofa' ? keyForm.email.trim() : ''
  if (keyForm.platform === 'fofa' && email) {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      MessagePlugin.error('Fofa 邮箱格式不正确')
      return
    }
  }

  try {
    let res
    if (keyEditMode.value) {
      res = await apiScanKeyUpdate(keyForm.platform, oldKey.value, keyForm.key, email)
    } else {
      res = await apiScanKeyAdd(keyForm.platform, keyForm.key, email)
    }

    MessagePlugin.success(keyEditMode.value ? 'Key 已更新' : 'Key 已添加')
    if (keyForm.platform === 'fofa') scanCfg.fofa_email = email
    keyModalVisible.value = false
    loadKeys()
  } catch (error) {
    MessagePlugin.error(error.message || '操作失败')
  }
}

async function deleteKey(row) {
  const confirmDialog = DialogPlugin.confirm({
    header: '删除 API Key',
    body: `确定删除 ${platformLabelMap[row.platform] || row.platform} 的 Key 吗？删除后无法恢复。`,
    theme: 'warning',
    confirmBtn: { content: '删除', theme: 'danger' },
    onConfirm: async () => {
      try {
        await apiScanKeyDelete(row.platform, row.key_id || row.key)
        MessagePlugin.success('Key 已删除')
        loadKeys()
      } catch (_) {
        MessagePlugin.error('删除失败')
      }
      confirmDialog.hide()
    },
  })
}

async function canLeave() {
  if (!isDirty.value) return true
  return new Promise(resolve => {
    const dialog = DialogPlugin.confirm({
      header: '采集配置尚未保存', body: '离开将丢弃本次修改。',
      confirmBtn: '放弃修改', cancelBtn: '继续编辑',
      onConfirm: () => {
        Object.assign(scanCfg, JSON.parse(savedSnapshot.value))
        dialog.hide()
        resolve(true)
      },
      onCancel: () => { dialog.hide(); resolve(false) },
      onClose: () => { dialog.hide(); resolve(false) },
    })
  })
}
function beforeUnload(event) {
  if (isDirty.value) { event.preventDefault(); event.returnValue = '' }
}
defineExpose({ save: saveScanConfig, canLeave })

onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  loadConfig()
  loadKeys()
  countdownTimer = setInterval(updateCountdown, 1000)
  updateCountdown()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  if (countdownTimer) clearInterval(countdownTimer)
})
</script>

<style scoped src="../styles/configuration.css"></style>

<style scoped>
.fofa-balances { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.key-status { max-width: 100%; height: auto; white-space: normal; overflow-wrap: anywhere; }
.key-test-report { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--td-component-stroke); overflow-wrap: anywhere; }
.key-test-report p { margin: 6px 0; }
.key-test-query, .key-test-step { font-size: 12px; line-height: 1.7; }
.key-test-step { margin-top: 12px; padding: 12px; border: 1px solid var(--td-component-stroke); border-radius: var(--td-radius-medium); }

.keys-card {
  min-width: 0;
}

.table-scroll-shell {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.table-scroll-shell :deep(.t-table) {
  min-width: 700px;
}

.scan-config-toolbar {
  position: sticky;
  top: 8px;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 10px;
  background: var(--td-bg-color-container);
  box-shadow: none;
}

.toolbar-copy {
  min-width: 0;
}

.toolbar-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.toolbar-title {
  color: var(--td-text-color-primary);
  font-size: 15px;
  font-weight: 700;
}

.toolbar-note {
  color: var(--td-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.toolbar-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.toolbar-pill {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: var(--td-radius-default);
  background: var(--td-bg-color-secondarycontainer);
  color: var(--td-text-color-secondary);
  font-size: 12px;
  font-weight: 600;
}

.toolbar-pill--accent {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
}

.toolbar-actions {
  flex-shrink: 0;
}

.section-header,
.search-keywords-panel,
.search-keywords-editor {
  width: 100%;
}

.search-keywords-panel code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--td-bg-color-secondarycontainer);
  color: var(--td-brand-color);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.province-card,
.schedule-card,
.fofa-config-card {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--td-component-stroke);
  border-radius: 8px;
  background: var(--td-bg-color-secondarycontainer);
}

.fofa-config-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.scan-size-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
}

.scan-size-item {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.scan-size-item :deep(.t-input-number) { width: 100%; }

.scan-size-item label {
  color: var(--td-text-color-primary);
  font-size: 13px;
  font-weight: 600;
}

.fofa-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fofa-field label {
  color: var(--td-text-color-primary);
  font-size: 13px;
  font-weight: 600;
}

.province-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.province-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.province-summary-main {
  color: var(--td-text-color-primary);
  font-size: 13px;
  font-weight: 600;
}

.province-summary-sub {
  color: var(--td-text-color-secondary);
  font-size: 12px;
}

.province-select {
  width: 100%;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.schedule-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.schedule-time {
  width: 140px;
}

.schedule-summary {
  margin-top: 10px;
  color: var(--td-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.countdown-text {
  margin-top: 6px;
  color: var(--td-brand-color);
  font-size: 12px;
  line-height: 1.5;
}

.dialog-actions {
  justify-content: flex-end;
  margin-top: 16px;
}

.platform-link {
  margin-top: 6px;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .config-panel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .section-header,
  .config-header,
  .scan-config-toolbar,
  .config-field {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-actions {
    width: 100%;
  }

  .toolbar-actions :deep(.t-space-item) {
    flex: 1;
  }

  .toolbar-actions :deep(.t-button) {
    width: 100%;
  }

  .config-header-pills {
    justify-content: flex-start;
  }

  .field-control,
  .field-control--wide,
  .field-stack {
    width: 100%;
  }

  .scan-size-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .scan-size-item :deep(.t-input-number) {
    width: 100%;
  }

  .province-toolbar {
    align-items: stretch;
  }

  .config-card :deep(.t-card__body) {
    padding: 16px;
  }

  .config-panel { padding: 0; }
  .scan-config-toolbar { position: static; }
}
</style>
