const PROXY_SAFE_CHUNK = 8 * 1024 * 1024

export async function uploadInChunks({ file, create, append, complete, onProgress }) {
  const session = await create()
  let offset = Number(session.offset || 0)
  const chunkSize = Math.min(Number(session.chunk_size || PROXY_SAFE_CHUNK), PROXY_SAFE_CHUNK)
  while (offset < file.size) {
    const end = Math.min(offset + chunkSize, file.size)
    const response = await append(session.id, offset, file.slice(offset, end))
    offset = Number(response.offset)
    onProgress?.(Math.round(offset * 100 / file.size))
  }
  return complete(session.id)
}
