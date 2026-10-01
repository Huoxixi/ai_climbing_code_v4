import { after } from 'node:test'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'

export async function startFixtureServer(port, externalUrl) {
  if (externalUrl) return externalUrl
  const base = `http://127.0.0.1:${port}`
  const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)), windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = '', failure
  const capture = chunk => { output = (output + chunk.toString()).slice(-8000) }
  server.stdout.on('data', capture)
  server.stderr.on('data', capture)
  server.once('error', error => { failure = error })
  const stop = () => server.kill()
  after(stop)
  process.once('exit', stop)
  const deadline = Date.now() + 15000
  try {
    while (Date.now() < deadline) {
      if (failure) throw failure
      if (server.exitCode !== null) throw new Error(`Fixture server exited (${server.exitCode}): ${output}`)
      // ANSI-colored logs differ between Windows and CI. Readiness is HTTP.
      try { if ((await fetch(base, { signal: AbortSignal.timeout(500) })).ok) return base } catch { /* not listening yet */ }
      await delay(100)
    }
    throw new Error(`Fixture server startup timed out: ${output}`)
  } catch (error) { stop(); throw error }
}
