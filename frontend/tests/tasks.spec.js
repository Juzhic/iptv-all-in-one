import { describe, expect, it } from 'vitest'
import { normalizeTask, normalizeTasks } from '../src/utils/tasks.js'

describe('task normalization', () => {
  it('normalizes task mappings', () => {
    const tasks = normalizeTasks({
      test: { id: 't1', running: true },
      scan: { task_id: 's1', state: 'idle' },
    })
    expect(tasks.test).toMatchObject({ task_id: 't1', task_type: 'test', state: 'running', active: true })
    expect(tasks.scan).toMatchObject({ task_id: 's1', task_type: 'scan', active: false })
    expect(tasks.ip_scan).toBeNull()
  })

  it('normalizes the items response shape and ignores unknown task types', () => {
    const tasks = normalizeTasks({ items: [
      { task_id: 'ip1', task_type: 'ip_scan', state: 'queued' },
      { task_id: 'other', task_type: 'unknown', state: 'running' },
    ] })
    expect(tasks.ip_scan).toMatchObject({ task_id: 'ip1', active: true })
    expect(Object.keys(tasks)).toEqual(['test', 'scan', 'ip_scan', 'detection'])
  })

  it('retains the fixed task mapping when the compatibility items array is empty', () => {
    const tasks = normalizeTasks({
      scan: { task_id: 'scan-map', state: 'running', progress: 64 },
      items: [],
    })
    expect(tasks.scan).toMatchObject({ task_id: 'scan-map', active: true, progress: 64 })
  })

  it('keeps structured progress and derives active state', () => {
    expect(normalizeTask({ state: 'stopping', progress: { processed: 8 } }, 'scan')).toMatchObject({
      task_type: 'scan',
      active: true,
      progress: { processed: 8 },
    })
  })
})
