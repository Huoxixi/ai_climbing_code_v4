import assert from 'node:assert/strict'
import test from 'node:test'
import config from '../vite.config.js'

const forMode = (mode) => typeof config === 'function' ? config({ command: 'build', mode }) : config

test('desktop build selects the local application without reading env files', () => {
  assert.equal(forMode('boulder-local').define?.['import.meta.env.VITE_LOCAL_BOULDER_ONLY'], JSON.stringify('true'))
})

test('the full application build keeps its existing mode', () => {
  assert.equal(forMode('production').define?.['import.meta.env.VITE_LOCAL_BOULDER_ONLY'], undefined)
})
