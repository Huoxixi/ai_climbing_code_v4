import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { photoSampleFile } from '../src/utils/photoSample.js'

for (const sample of [1,2]) {
  test(`bundled photo ${sample} preserves the exact original bytes without fetching`, async () => {
    const bytes = await readFile(new URL(`../src/assets/boulder-samples/boulder-${sample}.jpg`, import.meta.url))
    const file = photoSampleFile(`data:image/jpeg;base64,${bytes.toString('base64')}`, `抱石路线${sample}`)
    assert.equal(file.name, `抱石路线${sample}.jpg`)
    assert.equal(file.type, 'image/jpeg')
    assert.deepEqual(Buffer.from(await file.arrayBuffer()), bytes)
  })
}

test('invalid sample data is rejected before uploading', () => {
  assert.throws(() => photoSampleFile('/missing.jpg', 'sample'))
  assert.throws(() => photoSampleFile('data:text/html;base64,SGk=', 'sample'))
})
