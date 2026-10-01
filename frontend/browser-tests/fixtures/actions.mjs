// Constructed events only. This fixture contains no climber, photo or user record.
export const organized = {
  source_duration_seconds: 8,
  video: { duration_seconds: 8, fps: 24, frame_count: 192, width: 640, height: 360 },
  holds: [{ id: '1' }],
  groups: [0, 1, 2].map((index) => ({
    id: `fixture-group-${index}`, start_seconds: index * 2, end_seconds: index * 2 + 1.5,
    description: '构造伸手动作',
    events: [{ id: `fixture-event-${index}`, limb: 'left_hand', action: 'reach',
      start_seconds: index * 2, end_seconds: index * 2 + 1.5,
      evidence_status: 'locally_verified', event_status: 'locally_verified',
      caption_parts: [{ start_seconds: index * 2, text: '向上伸手' }],
      evidence: [{ frame_id: `frame-${index * 48}`, time_seconds: index * 2 }],
      facts: [], technique_tags: [], relations: [],
    }],
  })),
  metrics: [
    { key: 'route_total', label: '线路总岩点', value: 3, unit: '个' },
    { key: 'route_used', label: '使用岩点', value: 2, unit: '个' },
    { key: 'route_usage', label: '使用岩点比例', value: 66.7, unit: '%' },
    { key: 'duration', label: '攀爬时长', value: 8, unit: '秒' },
  ],
  motion_summary: { duration_seconds: 8, segments: [
    { kind: 'moving', start_seconds: 0, end_seconds: 6 },
    { kind: 'unknown', start_seconds: 6, end_seconds: 8 },
  ], totals: [{ kind: 'moving', label: '移动', percent: 75, seconds: 6 },
    { kind: 'unknown', label: '未观测', percent: 25, seconds: 2 }] },
}

export async function syntheticMedia(browser) {
  const page = await browser.newPage()
  try {
    const data = await page.evaluate(async () => {
      const canvas = document.createElement('canvas')
      canvas.width = 640; canvas.height = 360
      const context = canvas.getContext('2d')
      const stream = canvas.captureStream(24)
      const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' })
      const chunks = []
      recorder.ondataavailable = event => chunks.push(event.data)
      const stopped = new Promise(resolve => { recorder.onstop = resolve })
      recorder.start()
      let frame = 0
      const timer = setInterval(() => {
        context.fillStyle = '#263b46'; context.fillRect(0, 0, 640, 360)
        context.fillStyle = '#e3bb26'; context.fillRect(20 + (frame++ % 120) * 3, 160, 40, 40)
      }, 1000 / 24)
      await new Promise(resolve => setTimeout(resolve, 8000))
      clearInterval(timer); recorder.stop(); await stopped
      stream.getTracks().forEach(track => track.stop())
      return Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()))
    })
    return Buffer.from(data)
  } finally { await page.close() }
}
