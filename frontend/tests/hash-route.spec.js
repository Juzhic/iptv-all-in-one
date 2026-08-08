import { describe, expect, it } from 'vitest'
import { parseHashRoute, routeHash } from '../src/composables/useHashRoute.js'

describe('hash routing', () => {
  const routes = ['overview', 'scan-results', 'settings']

  it('parses canonical and query-bearing hashes', () => {
    expect(parseHashRoute('#/scan-results', routes)).toBe('scan-results')
    expect(parseHashRoute('#/settings?section=text', routes)).toBe('settings')
  })

  it('falls back for unknown and malformed hashes', () => {
    expect(parseHashRoute('#/unknown', routes)).toBe('overview')
    expect(parseHashRoute('#/%E0%A4%A', routes)).toBe('overview')
  })

  it('maps legacy configuration hashes to the configuration center', () => {
    expect(parseHashRoute('#/settings', [...routes, 'configuration'], 'overview', { settings: 'configuration' })).toBe('configuration')
  })

  it('generates stable route hashes', () => {
    expect(routeHash('scan-results')).toBe('#/scan-results')
  })
})
