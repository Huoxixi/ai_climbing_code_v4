import test from 'node:test'
import assert from 'node:assert/strict'
import { createReplayCardAutoplay } from '../src/services/replayCardAutoplay.js'

function harness() {
  let time=0, id=0, index=0, finished=0
  const timers=new Map()
  const player=createReplayCardAutoplay({current:()=>({index,count:3}),advance:()=>index++,finish:()=>finished++,
    schedule(fn,ms){timers.set(++id,{fn,at:time+ms});return id},cancel:id=>timers.delete(id)})
  function advance(ms){const end=time+ms;while(timers.size){const [key,timer]=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];if(timer.at>end)break;time=timer.at;timers.delete(key);timer.fn()}time=end}
  return {player,advance,timers,get index(){return index},get finished(){return finished}}
}
test('first automatic pass gives every card six seconds and finishes once',()=>{
  const h=harness();h.player.start();h.advance(5999);assert.equal(h.index,0)
  h.advance(1);assert.equal(h.index,1);h.advance(6000);assert.equal(h.index,2)
  h.advance(6000);assert.equal(h.finished,1);assert.equal(h.timers.size,0)
  h.advance(60000);assert.equal(h.finished,1)
})
test('manual interaction cancels pending automatic paging',()=>{
  const h=harness();h.player.start();h.advance(5000);h.player.stop();h.advance(60000)
  assert.equal(h.index,0);assert.equal(h.finished,0);assert.equal(h.timers.size,0)
})
test('hover, focus or hidden page pauses, and resume gives a full reading interval',()=>{
  const h=harness();h.player.start();h.advance(5900);h.player.pause(true);h.advance(30000)
  assert.equal(h.index,0);assert.equal(h.timers.size,0)
  h.player.pause(false);h.advance(5999);assert.equal(h.index,0);h.advance(1);assert.equal(h.index,1)
})
test('reset discards the previous deadline and disposal cancels all future work',()=>{
  const h=harness();h.player.start();h.advance(5900);h.player.reset();h.advance(100)
  assert.equal(h.index,0);h.player.dispose();h.player.start();h.advance(60000)
  assert.equal(h.index,0);assert.equal(h.finished,0);assert.equal(h.timers.size,0)
})
