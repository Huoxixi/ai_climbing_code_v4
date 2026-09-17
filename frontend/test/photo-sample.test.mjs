import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { photoSampleFile } from '../src/utils/photoSample.js'

for (const sample of [1,2]) {
  test(`bundled photo ${sample} preserves the exact original bytes`, async () => {
    const bytes = await readFile(new URL(`../src/assets/boulder-samples/boulder-${sample}.jpg`, import.meta.url))
    const file = await photoSampleFile(`data:image/jpeg;base64,${bytes.toString('base64')}`, `抱石路线${sample}`)
    assert.equal(file.name, `抱石路线${sample}.jpg`)
    assert.equal(file.type, 'image/jpeg')
    assert.deepEqual(Buffer.from(await file.arrayBuffer()), bytes)
  })
}

test('a deployed sample asset can be downloaded and converted to an upload file', async () => {
  const bytes = await readFile(new URL('../src/assets/boulder-samples/boulder-1.jpg', import.meta.url))
  const requests = []
  const file = await photoSampleFile('/assets/boulder-1.hash.jpg', '抱石路线1', async (url, options) => {
    requests.push({ url, options })
    return new Response(bytes, { status:200, headers:{ 'content-type':'image/jpeg' } })
  })

  assert.deepEqual(requests, [{ url:'/assets/boulder-1.hash.jpg', options:{ cache:'force-cache' } }])
  assert.equal(file.name, '抱石路线1.jpg')
  assert.equal(file.type, 'image/jpeg')
  assert.deepEqual(Buffer.from(await file.arrayBuffer()), bytes)
})

test('production build keeps both public samples as server assets instead of inline data', async () => {
  const sources = await Promise.all([
    '../src/components/PhotoRouteWorkflowPage.vue',
    '../src/components/PhotoRoutesV2Page.vue',
  ].map((path) => readFile(new URL(path, import.meta.url), 'utf8')))

  for (const source of sources) {
    assert.match(source, /boulder-1\.jpg'/)
    assert.match(source, /boulder-2\.jpg'/)
    assert.doesNotMatch(source, /boulder-[12]\.jpg\?inline/)
  }
})

test('missing or non-image server samples are rejected before uploading', async () => {
  await assert.rejects(photoSampleFile('/missing.jpg', 'sample', async () => new Response('', { status:404 })))
  await assert.rejects(photoSampleFile('/wrong-type.jpg', 'sample', async () => new Response('Hi', { status:200, headers:{ 'content-type':'text/html' } })))
})
