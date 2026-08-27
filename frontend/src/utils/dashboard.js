function number(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export function percentRate(value) {
  const parsed = number(value)
  return Math.max(0, Math.min(100, parsed <= 1 ? parsed * 100 : parsed))
}

export function normalizeSubscriptionRun(row) {
  if (!row || typeof row !== 'object') return null
  if (row.summary) return row

  const total = number(row.channels_total)
  const passed = number(row.channels_passed)
  return {
    ...row,
    duration_seconds: number(row.duration_seconds),
    summary: {
      total_tested: total,
      total_passed: passed,
      pass_rate: percentRate(row.pass_rate),
      unique_channels_total: total,
      unique_channels_passed: passed,
      source_count: number(row.source_count),
      avg_bandwidth_MBps: number(row.avg_bandwidth_MBps),
      avg_quality: number(row.avg_quality),
    },
  }
}

export function normalizeSubscriptionTrend(rows) {
  if (!Array.isArray(rows)) return []
  const aggregated = rows.some(row => row && !row.summary && 'channels_total' in row)
  const ordered = aggregated ? [...rows].reverse() : [...rows]
  return ordered.map(normalizeSubscriptionRun).filter(Boolean)
}

function deltaText(value) {
  const delta = number(value)
  if (!delta) return '较上轮持平'
  return `较上轮 ${delta > 0 ? '+' : ''}${delta.toLocaleString()}`
}

function countCard(label, key, latest, status) {
  const value = number(latest?.[key])
  return {
    label,
    value: latest ? value.toLocaleString() : '--',
    sub: latest ? deltaText(latest.deltas?.[key]) : '等待首次频道扫描',
    status: latest ? status : '待采集',
    tone: latest ? 'info' : 'muted',
    progress: null,
  }
}

export function buildDashboardCards(dashboard, latestRun, runningTaskCount = 0) {
  const scanLatest = dashboard?.scan?.latest
  const pool = dashboard?.scan?.pool || {}
  const subscription = dashboard?.subscriptions?.latest

  if (scanLatest || subscription || Object.keys(pool).length) {
    const poolGood = number(pool.good)
    const poolPoor = number(pool.poor)
    const poolUnreachable = number(pool.unreachable)
    const poolPending = number(pool.pending)
    const decided = poolGood + poolPoor + poolUnreachable
    const goodRate = pool.good_rate_percent != null
      ? number(pool.good_rate_percent)
      : (decided ? poolGood / decided * 100 : 0)
    const subscriptionRate = percentRate(subscription?.pass_rate)

    return [
      countCard('扫描原始数', 'total_raw', scanLatest, '已采集'),
      countCard('扫描去重数', 'total_deduped', scanLatest, '已归并'),
      countCard('快速通过数', 'total_fast_pass', scanLatest, '已快筛'),
      countCard('深检通过数', 'total_deep_pass', scanLatest, '已验证'),
      {
        label: '持久池良好率',
        value: decided ? `${goodRate.toFixed(1)}%` : '--',
        sub: `良好 ${poolGood} · 较差 ${poolPoor} · 不可达 ${poolUnreachable} · 待定 ${poolPending}`,
        status: decided ? (goodRate >= 80 ? '健康' : '需关注') : '待采集',
        tone: decided ? (goodRate >= 80 ? 'good' : 'warn') : 'muted',
        progress: decided ? goodRate : null,
      },
      {
        label: '数据来源 / 频道',
        value: subscription ? `${number(subscription.source_count)} / ${number(subscription.channels_total)}` : '--',
        sub: subscription ? `通过频道 ${number(subscription.channels_passed).toLocaleString()}` : '等待首次系统测试',
        status: subscription ? '最新一轮' : '待采集',
        tone: subscription ? 'info' : 'muted',
        progress: null,
      },
      {
        label: '数据来源频道通过率',
        value: subscription ? `${subscriptionRate.toFixed(1)}%` : '--',
        sub: subscription
          ? `${number(subscription.channels_passed).toLocaleString()} / ${number(subscription.channels_total).toLocaleString()} 个频道通过`
          : '等待首次系统测试',
        status: subscription ? (subscriptionRate >= 80 ? '健康' : '需关注') : '待采集',
        tone: subscription ? (subscriptionRate >= 80 ? 'good' : 'warn') : 'muted',
        progress: subscription ? subscriptionRate : null,
      },
      {
        label: '订阅平均质量',
        value: subscription ? `${number(subscription.avg_bandwidth_MBps).toFixed(2)} MB/s` : '--',
        sub: subscription
          ? `平均质量 ${number(subscription.avg_quality).toFixed(2)} · ${runningTaskCount} 个任务活动`
          : '等待带宽和质量样本',
        status: subscription ? '已聚合' : '待采集',
        tone: subscription ? 'good' : 'muted',
        progress: null,
      },
    ]
  }

  const summary = latestRun?.summary || {}
  const passRate = number(summary.pass_rate)
  return [
    {
      label: '订阅通过率',
      value: latestRun ? `${passRate.toFixed(1)}%` : '--',
      sub: latestRun
        ? `${number(summary.total_passed).toLocaleString()} / ${number(summary.total_tested).toLocaleString()} 个地址通过`
        : '等待首次系统测试',
      status: passRate >= 80 ? '健康' : (latestRun ? '需关注' : '待采集'),
      tone: passRate >= 80 ? 'good' : (latestRun ? 'warn' : 'muted'),
      progress: latestRun ? percentRate(passRate) : null,
    },
    {
      label: '任务队列',
      value: String(runningTaskCount),
      sub: runningTaskCount ? '运行中任务按 2 秒刷新' : '空闲状态按 10 秒刷新',
      status: runningTaskCount ? '运行中' : '空闲',
      tone: runningTaskCount ? 'info' : 'muted',
      progress: null,
    },
  ]
}
