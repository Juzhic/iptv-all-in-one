import { describe, expect, it } from 'vitest'
import { parseSubscription, playbackSource } from '../src/utils/playlist.js'

describe('tested subscription playlist', () => {
  it('skips update metadata, preserves ranked routes, decodes attributes and deduplicates', () => {
    const channels = parseSubscription('\uFEFF#EXTM3U\r\n' + [
      '#EXTINF:-1 tvg-id="更新时间" group-title="🕘️更新时间",2026-09-14',
      'http://localhost/update_time',
      '#EXTINF:-1 tvg-logo="https://logo.test/a,b.png" group-title="新闻 &amp; 资讯",CCTV,新闻',
      'https://tv.test/best.m3u8?token=a,b',
      '#EXTINF:-1 group-title="新闻 &amp; 资讯",CCTV,新闻',
      '# comment',
      'http://tv.test/backup.ts',
      '#EXTINF:-1 group-title="新闻 &amp; 资讯",CCTV,新闻',
      'http://tv.test/backup.ts',
    ].join('\r\n'))
    expect(channels).toHaveLength(1)
    expect(channels[0]).toMatchObject({ name: 'CCTV,新闻', group: '新闻 & 资讯', urls: ['https://tv.test/best.m3u8?token=a,b', 'http://tv.test/backup.ts'] })
  })

  it('handles empty and malformed lists without inventing channels', () => {
    expect(parseSubscription('#EXTM3U\n# No channels available')).toEqual([])
    expect(parseSubscription('<html>server error</html>')).toEqual([])
    expect(parseSubscription('#EXTINF:-1,\nhttp://tv.test/a\n#EXTINF:-1,unfinished')).toEqual([])
  })

  it('retains unsupported routes so the player can explain and allow copying them', () => {
    expect(parseSubscription('#EXTINF:-1,TV\nrtsp://tv.test/live')[0].urls).toEqual(['rtsp://tv.test/live'])
  })

  it.each([
    ['https://tv.test/live.m3u8?auth=x', 'hls'], ['http://tv.test/udp/239.1.2.3:1234', 'mpegts'],
    ['http://tv.test/rtp/239.1.2.3:1234', 'mpegts'], ['http://tv.test/live.ts?x=1', 'mpegts'],
    ['https://tv.test/live.flv', 'flv'], ['https://tv.test/movie.mp4', 'native'], ['https://tv.test/live', 'hls'],
  ])('identifies %s as %s', (url, type) => expect(playbackSource(url, 'auto', 'http:').type).toBe(type))

  it('supports explicit format selection', () => expect(playbackSource('https://tv.test/live', 'mpegts').type).toBe('mpegts'))

  it.each(['javascript:alert(1)', 'data:video/mp4,abc', 'rtsp://tv.test/live', 'not a URL', 'https://user:password@tv.test/live'])('rejects unsafe or unsupported address %s', url => {
    expect(() => playbackSource(url)).toThrow()
  })

  it('accepts HTTP sources for server-side proxy playback', () => {
    expect(playbackSource('http://tv.test/live')).toEqual({ url: 'http://tv.test/live', type: 'hls' })
  })
})
