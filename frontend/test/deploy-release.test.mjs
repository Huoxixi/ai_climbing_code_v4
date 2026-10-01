import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('production Detectron2 cache keeps a pip-installable wheel filename', async () => {
  const script = await readFile(new URL('../../deploy/scripts/deploy_release.sh', import.meta.url), 'utf8')
  const wheel = script.match(/^DETECTRON2_WHEEL="\$\{DETECTRON2_WHEEL_CACHE\}\/([^"\n]+)"$/m)

  assert.ok(wheel, 'the release script must name the cached wheel')
  assert.equal(wheel[1], 'detectron2-0.6-cp312-cp312-linux_x86_64.whl')
  assert.match(wheel[1], /^[^-]+-[^-]+-[^-]+-[^-]+-[^-]+\.whl$/)
  assert.match(script, /DETECTRON2_LEGACY_WHEEL="\$\{DETECTRON2_WHEEL_CACHE\}\/detectron2-py312-torch2\.8-cpu\.whl"/)
  assert.match(script, /sha256sum --check --status "\$\{DETECTRON2_LEGACY_WHEEL_SHA256\}"/)
  assert.match(script, /--no-build-isolation/)
  assert.match(script, /basename "\$\{detectron2_wheel_candidate\}"/)
})
