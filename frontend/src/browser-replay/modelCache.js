import {CACHE_NAME} from './modelManifest.js'

export async function verifyModel(buffer, file, cryptoApi = globalThis.crypto) {
  if (buffer.byteLength !== file.bytes) throw new Error('模型文件不完整，请重新准备模型。')
  const digest = await cryptoApi.subtle.digest('SHA-256', buffer)
  const hex = [...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('')
  if (hex !== file.sha256) throw new Error('模型校验失败，请重新准备模型。')
  return buffer
}

export async function loadModel(file, {onProgress=()=>{}, cacheStorage=globalThis.caches, fetcher=globalThis.fetch, cryptoApi=globalThis.crypto, signal}={}) {
  let cache
  try { cache = await cacheStorage?.open(CACHE_NAME) } catch { /* private mode / quota: use memory */ }
  try {
    const hit = await cache?.match(file.url)
    if (hit) {
      const buffer = await verifyModel(await hit.arrayBuffer(), file, cryptoApi)
      onProgress({name:file.name, loaded:file.bytes, total:file.bytes, cached:true, stored:true})
      return buffer
    }
  } catch { await cache?.delete(file.url).catch(()=>{}) }
  const response = await fetcher(file.url, {signal, credentials:'omit', cache:'no-store', redirect:'error'})
  if (!response.ok) throw new Error(`模型暂时无法加载（${response.status}），请检查网络后重试。`)
  const chunks = []
  let loaded = 0
  if (response.body) {
    const reader = response.body.getReader()
    try {
      while (true) {
        const {done, value} = await reader.read()
        if (done) break
        loaded += value.byteLength
        if (loaded > file.bytes) { await reader.cancel(); throw new Error('模型大小与当前版本不符。') }
        chunks.push(value)
        onProgress({name:file.name, loaded, total:file.bytes, cached:false})
      }
    } finally { reader.releaseLock() }
  } else {
    const value = new Uint8Array(await response.arrayBuffer()); loaded = value.byteLength; chunks.push(value)
  }
  const bytes = new Uint8Array(loaded)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  await verifyModel(bytes.buffer, file, cryptoApi)
  let stored = false
  try {
    await cache?.put(file.url, new Response(bytes, {headers:{'Content-Type':'application/octet-stream'}}))
    stored = !!cache
  } catch { /* full storage does not prevent local inference */ }
  onProgress({name:file.name, loaded, total:file.bytes, cached:false, stored})
  return bytes.buffer
}
