export const NAV_GROUPS = [
  {
    label: '工作台',
    value: 'workspace',
    items: [
      { value: 'overview', label: '总览', short: '总', description: '查看最新测速、频道覆盖与质量趋势' },
    ],
  },
  {
    label: '质量',
    value: 'quality',
    items: [
      { value: 'scan-results', label: '候选源池', short: '池', description: '筛选、复检并导出测绘采集得到的频道地址' },
      { value: 'sources', label: '数据来源', short: '源', description: '按质量评分查看订阅源、测绘平台及频道覆盖' },
      { value: 'detection', label: '健康复检', short: '检', description: '管理候选源池复检策略并追踪质量变化' },
    ],
  },
  {
    label: '任务',
    value: 'tasks',
    items: [
      { value: 'testing', label: '全量测速', short: '测', description: '对启用的数据源执行测速并更新播放列表' },
      { value: 'scanner', label: '测绘采集', short: '采', description: '从测绘平台、搜索引擎及补探测流程采集候选源' },
      { value: 'ip-scan', label: 'IP 探测', short: 'IP', description: '批量探测指定 IP、域名与端口' },
    ],
  },
  {
    label: '配置',
    value: 'configuration',
    items: [
      { value: 'history', label: '历史记录', short: '史', description: '按日期查询、展开并对比历次测速结果' },
      { value: 'configuration', label: '配置中心', short: '配', description: '集中维护系统参数、文本文件与采集策略' },
    ],
  },
]

export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items)
export const TAB_VALUES = NAV_ITEMS.map((item) => item.value)

export function getPageMeta(value) {
  return NAV_ITEMS.find((item) => item.value === value) || NAV_ITEMS[0]
}
