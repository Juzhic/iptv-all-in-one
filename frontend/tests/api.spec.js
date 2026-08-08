import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  apiDiscover,
  apiScanAllResults,
  apiScanKeyDelete,
  apiScanKeyUpdate,
  apiTriggerTest,
  deleteJSON,
  fetchJSON,
  postJSON,
  putJSON,
} from '../src/api.js'

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: vi.fn().mockResolvedValue(payload == null ? '' : JSON.stringify(payload)),
  }
}

describe('API request policy', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it.each([
    ['POST', () => postJSON('/api/post')],
    ['PUT', () => putJSON('/api/put')],
    ['DELETE', () => deleteJSON('/api/delete')],
  ])('adds the mutation guard and JSON body for %s', async (method, request) => {
    fetch.mockResolvedValueOnce(response({ ok: true, data: {} }))
    await request()
    const [, options] = fetch.mock.calls[0]
    expect(options.method).toBe(method)
    expect(options.headers['X-IPTV-Request']).toBe('1')
    expect(options.headers['Content-Type']).toBe('application/json')
    expect(options.body).toBe('{}')
  })

  it('uses POST for discovery operations', async () => {
    fetch.mockResolvedValueOnce(response({ ok: true, data: { items: [] } }))
    await apiDiscover()
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'POST', body: '{}' })
  })

  it('keeps backend error data available to callers', async () => {
    fetch.mockResolvedValueOnce(response({
      ok: false,
      error: '任务冲突',
      data: { task: { task_id: 'task-old', state: 'running' } },
    }, 409))
    await expect(fetchJSON('/api/fail')).rejects.toMatchObject({
      message: '任务冲突',
      status: 409,
      data: { task: { task_id: 'task-old', state: 'running' } },
    })
  })

  it('normalizes a 202 task envelope without losing message fields', async () => {
    fetch.mockResolvedValueOnce(response({
      ok: true,
      data: { task: { task_id: 'task-202', task_type: 'test', state: 'starting' } },
      message: 'accepted',
    }, 202))
    await expect(apiTriggerTest()).resolves.toMatchObject({
      task_id: 'task-202',
      state: 'starting',
      message: 'accepted',
    })
  })

  it('paginates all scan results while preserving server-side filters', async () => {
    fetch
      .mockResolvedValueOnce(response({ ok: true, data: { items: [{ id: 1 }, { id: 2 }], total: 3 } }))
      .mockResolvedValueOnce(response({ ok: true, data: { items: [{ id: 3 }], total: 3 } }))
    await expect(apiScanAllResults(
      { search: '央视', quality: 'good', sort_by: 'delay', sort_order: 'asc' },
      { pageSize: 2 },
    )).resolves.toHaveLength(3)

    expect(fetch.mock.calls[0][0]).toContain('search=%E5%A4%AE%E8%A7%86')
    expect(fetch.mock.calls[0][0]).toContain('page=1')
    expect(fetch.mock.calls[0][0]).toContain('size=2')
    expect(fetch.mock.calls[1][0]).toContain('page=2')
  })

  it('updates and deletes scanner keys exclusively by key_id', async () => {
    fetch.mockResolvedValue(response({ ok: true, data: {} }))
    await apiScanKeyUpdate('quake', 'kid-1', 'replacement-secret')
    await apiScanKeyDelete('quake', 'kid-1')

    const updateBody = JSON.parse(fetch.mock.calls[0][1].body)
    const deleteBody = JSON.parse(fetch.mock.calls[1][1].body)
    expect(updateBody).toEqual({ platform: 'quake', key_id: 'kid-1', new_key: 'replacement-secret' })
    expect(deleteBody).toEqual({ platform: 'quake', key_id: 'kid-1' })
  })
})
