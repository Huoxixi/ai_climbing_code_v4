import test from 'node:test'
import assert from 'node:assert/strict'
import { createReplaySummaryController } from '../src/services/replaySummaryState.js'

function harness() {
  let time = 0, sequence = 0
  const timers = new Map(), updates = []
  const controller = createReplaySummaryController({ now: () => time, onChange: state => updates.push(state),
    schedule(fn, delay) { const id = ++sequence; timers.set(id, { fn, at: time + delay }); return id },
    cancel: id => timers.delete(id),
  })
  function advance(ms) {
    const end = time + ms
    while (timers.size) {
      const [id, timer] = [...timers].sort((a, b) => a[1].at - b[1].at)[0]
      if (timer.at > end) break
      time = timer.at; timers.delete(id); timer.fn()
    }
    time = end
  }
  controller.setRecord('a')
  return { controller, advance, timers, updates }
}

test('the automatic recap finishes at the reading duration and only runs once for a record', () => {
  const { controller, advance, timers } = harness()
  assert.equal(controller.ended(5.2), true)
  advance(1000)
  assert.equal(controller.state.phase, 'automatic')
  assert.equal(controller.ended(5.2), false)
  advance(4200)
  assert.equal(controller.state.phase, 'collapsed')
  assert.equal(timers.size, 0)
  assert.equal(controller.ended(5.2), false)
})

test('opening the disc manually holds the recap until an explicit collapse', () => {
  const { controller, advance, timers } = harness()
  controller.ended(4); advance(4000); controller.open(); advance(60000)
  controller.interrupt()
  assert.equal(controller.state.phase, 'manual')
  assert.equal(timers.size, 0)
  controller.collapse()
  assert.equal(controller.state.phase, 'collapsed')
  assert.equal(controller.ended(4), false)
})

test('playing or seeking interrupts a recap without scheduling another automatic presentation', () => {
  const { controller, advance, timers } = harness()
  controller.interrupt()
  assert.equal(controller.state.phase, 'hidden')
  controller.ended(20); advance(200); controller.interrupt(); advance(30000)
  assert.equal(controller.state.phase, 'collapsed')
  assert.equal(controller.ended(20), false)
  assert.equal(timers.size, 0)
})

test('record switching cancels the prior timer and returning to a seen record does not replay it', () => {
  const { controller, advance, timers } = harness()
  controller.ended(20); controller.setRecord('b'); advance(30000)
  assert.equal(controller.state.phase, 'hidden')
  assert.equal(timers.size, 0)
  assert.equal(controller.ended(4), true)
  controller.setRecord('a')
  assert.equal(controller.state.phase, 'collapsed')
  assert.equal(controller.ended(20), false)
})

test('reduced motion gets a static reading hold and unmount cancels pending updates', () => {
  const { controller, advance, timers, updates } = harness()
  controller.ended(3.6, true); advance(7999)
  assert.equal(controller.state.phase, 'automatic')
  assert.equal(controller.state.reducedMotion, true)
  advance(1)
  assert.equal(controller.state.phase, 'collapsed')
  controller.setRecord('b'); controller.ended(20)
  controller.dispose()
  const count = updates.length
  advance(30000); controller.open(); controller.ended(20)
  assert.equal(timers.size, 0)
  assert.equal(updates.length, count)
})

test('opening summary before the video ends consumes its automatic presentation', () => {
  const { controller } = harness()
  assert.equal(controller.ended(0), false)
  controller.open(); controller.collapse()
  assert.equal(controller.ended(20), false)
})
