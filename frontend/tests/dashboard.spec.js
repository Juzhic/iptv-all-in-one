import { describe, expect, it } from 'vitest'
import {
  buildDashboardCards,
  normalizeSubscriptionRun,
  normalizeSubscriptionTrend,
  percentRate,
} from '../src/utils/dashboard.js'

describe('2.0 dashboard metrics', () => {
  const dashboard = {
    scan: {
      latest: {
        total_raw: 120,
        total_deduped: 80,
        total_fast_pass: 50,
        total_deep_pass: 32,
        deltas: { total_raw: 10, total_deduped: -2, total_fast_pass: 0, total_deep_pass: 4 },
      },
      pool: { good: 75, poor: 15, unreachable: 10, pending: 20, good_rate_percent: 75 },
    },
    subscriptions: {
      latest: {
        source_count: 4,
        channels_total: 100,
        channels_passed: 86,
        pass_rate: 0.86,
        avg_bandwidth_MBps: 3.25,
        avg_quality: 2.8,
      },
    },
  }

  it('renders the complete scan funnel, pending-excluded good rate and subscription quality', () => {
    const cards = buildDashboardCards(dashboard, null, 2)
    expect(cards.map(card => card.label)).toEqual([
      '扫描原始数', '扫描去重数', '快速通过数', '深检通过数',
      '持久池良好率', '数据来源 / 频道', '数据来源频道通过率', '订阅平均质量',
    ])
    expect(cards[0]).toMatchObject({ value: '120', sub: '较上轮 +10' })
    expect(cards[1]).toMatchObject({ value: '80', sub: '较上轮 -2' })
    expect(cards[4]).toMatchObject({ value: '75.0%', progress: 75 })
    expect(cards[4].sub).toContain('待定 20')
    expect(cards[6]).toMatchObject({ value: '86.0%', progress: 86 })
    expect(cards[7].value).toBe('3.25 MB/s')
  })

  it('normalizes ratio-based SQL rows into the legacy chart shape without mutating input', () => {
    const rows = Object.freeze([
      Object.freeze({ run_id: 'old', finished_at: '2026-08-01 00:00:00', channels_total: 10, channels_passed: 5, pass_rate: 0.5 }),
      Object.freeze({ run_id: 'new', finished_at: '2026-08-02 00:00:00', channels_total: 20, channels_passed: 18, pass_rate: 0.9 }),
    ])
    const normalized = normalizeSubscriptionTrend(rows)
    expect(normalized.map(row => row.run_id)).toEqual(['new', 'old'])
    expect(normalized[0].summary).toMatchObject({ total_tested: 20, total_passed: 18, pass_rate: 90 })
    expect(rows[0]).not.toHaveProperty('summary')
    expect(percentRate(0.864)).toBeCloseTo(86.4)
    expect(normalizeSubscriptionRun(null)).toBeNull()
  })
})
