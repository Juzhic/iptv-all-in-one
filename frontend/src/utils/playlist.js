// Read the generated subscription, preserving its channel and quality ordering.
export function parseSubscription(text) {
  const channels = new Map()
  let entry = null
  for (const raw of text.replace(/^\uFEFF/, '').split(/\r?\n/)) {
    const line = raw.trim()
    if (line.startsWith('#EXTINF:')) {
      const match = line.match(/^#EXTINF:(?:[^",]|"[^"]*")*,(.*)$/)
      const attrs = Object.fromEntries([...line.matchAll(/([\w-]+)="([^"]*)"/g)].map((m) => [m[1], decodeAttribute(m[2])]))
      entry = match ? { name: match[1].trim(), group: attrs['group-title'] || '默认', id: attrs['tvg-id'] } : null
    } else if (line && !line.startsWith('#') && entry) {
      const current = entry
      entry = null
      // result.m3u contains a synthetic update-time entry, not a TV channel.
      if (current.id === '更新时间' && line === 'http://localhost/update_time') continue
      if (!current.name) continue
      const key = JSON.stringify([current.group, current.name])
      if (!channels.has(key)) channels.set(key, { key, name: current.name, group: current.group, urls: [] })
      const urls = channels.get(key).urls
      if (!urls.includes(line)) urls.push(line)
    }
  }
  return [...channels.values()]
}

function decodeAttribute(value) {
  const entities = { '&quot;': '"', '&#x27;': "'", '&#39;': "'", '&lt;': '<', '&gt;': '>', '&amp;': '&' }
  return value.replace(/&(?:quot|lt|gt|amp|#x27|#39);/g, (entity) => entities[entity])
}

export function playbackSource(raw, mode = 'auto') {
  let url
  try { url = new URL(raw) } catch { throw new Error('线路地址无效，请切换线路。') }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('浏览器不支持此协议，请复制线路地址到外部播放器。')
  if (url.username || url.password) throw new Error('此线路需要地址内认证，请使用外部播放器。')
  const path = url.pathname.toLowerCase()
  const type = mode !== 'auto' ? mode
    : /\.flv$/.test(path) ? 'flv'
      : /\.ts$|\/(?:udp|rtp)\//.test(path) ? 'mpegts'
        : /\.(?:mp4|webm|ogg)$/.test(path) ? 'native' : 'hls'
  return { url: url.href, type }
}
