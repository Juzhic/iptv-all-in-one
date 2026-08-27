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
      { value: 'scan-results', label: '扫描频道', short: '频', description: '筛选、复检并导出扫描发现的频道地址' },
      { value: 'sources', label: '数据来源', short: '源', description: '按质量评分查看订阅源、扫描平台及频道覆盖' },
      { value: 'detection', label: '检测监控', short: '检', description: '管理定期检测策略并追踪质量变化' },
    ],
  },
  {
    label: '任务',
    value: 'tasks',
    items: [
      { value: 'testing', label: '系统测试', short: '测', description: '启动测速任务并跟踪实时进度' },
      { value: 'scanner', label: '频道扫描', short: '扫', description: '执行测绘平台扫描并观察运行日志' },
      { value: 'ip-scan', label: 'IP 扫描', short: 'IP', description: '批量探测指定 IP、域名与端口' },
    ],
  },
  {
    label: '配置',
    value: 'configuration',
    items: [
      { value: 'history', label: '历史记录', short: '史', description: '按日期查询、展开并对比历次测速结果' },
      { value: 'configuration', label: '配置中心', short: '配', description: '集中维护系统参数、文本文件与扫描策略' },
    ],
  },
]

export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items)
export const TAB_VALUES = NAV_ITEMS.map((item) => item.value)

export function getPageMeta(value) {
  return NAV_ITEMS.find((item) => item.value === value) || NAV_ITEMS[0]
}
