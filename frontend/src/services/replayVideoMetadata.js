// Inspect metadata without owning page state; always release the temporary probe.
export async function inspectVideo(file) {
  const url = URL.createObjectURL(file)
  const probe = document.createElement('video')
  let timer
  try {
    const metadata = await new Promise((resolve, reject) => {
      timer = window.setTimeout(() => reject(new Error('视频信息读取超时')), 8000)
      probe.preload = 'metadata'
      probe.onloadedmetadata = () => { window.clearTimeout(timer); resolve({ width: probe.videoWidth, height: probe.videoHeight, duration: probe.duration }) }
      probe.onerror = () => { window.clearTimeout(timer); reject(new Error('浏览器无法预览此视频编码')) }
      probe.src = url
    })
    if (!metadata.width || !metadata.height || !Number.isFinite(metadata.duration)) throw new Error('无法读取视频尺寸或时长，请重新选择文件。')
    return metadata
  } finally {
    window.clearTimeout(timer)
    probe.onloadedmetadata = null
    probe.onerror = null
    probe.removeAttribute('src')
    probe.load()
    URL.revokeObjectURL(url)
  }
}
