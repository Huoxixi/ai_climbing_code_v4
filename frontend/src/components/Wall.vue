<template>
  <main class="stage">
    <div class="stage-header" v-if="routeData">
      <div class="route-info">
        <h2>{{ routeData.route_name }}</h2>
        <div class="commentary-card" v-if="routeData.setter_commentary">
          <span class="quote-icon">"</span>
          <p>{{ routeData.setter_commentary }}</p>
        </div>
      </div>
      <div class="controls">
        <div class="control-labels">
          <span class="step-counter">动作序列 {{ routeSteps.length > 0 ? currentIndex + 1 : 0 }} / {{ routeSteps.length }}</span>
          <span class="difficulty-tag">{{ profile.target_difficulty }}</span>
        </div>
        <input type="range" :value="currentIndex" @input="updateIndex($event.target.value)" min="0" :max="maxIndex" class="modern-slider" />
      </div>
    </div>

    <div class="wall-display">
      <div class="wall-frame">
        <div class="axis-x">
          <span v-for="x in 'ABCDEFGHIJK'.split('')" :key="x">{{ x }}</span>
        </div>
        <div class="axis-y">
          <span v-for="y in 18" :key="y">{{ y }}</span>
        </div>

        <div class="grid-backdrop">
          <template v-for="y in 18" :key="'y-'+y">
            <div v-for="(x, xi) in 'ABCDEFGHIJK'.split('')" :key="x+y" 
                 class="hole" :style="getCoord(x+y)"></div>
          </template>
        </div>

        <svg class="skeleton-layer">
          <line v-if="skeletonLines.body" v-bind="skeletonLines.body" class="bone body-bone" />
          <line v-if="skeletonLines.lh" v-bind="skeletonLines.lh" class="bone limb-bone" />
          <line v-if="skeletonLines.rh" v-bind="skeletonLines.rh" class="bone limb-bone" />
          <line v-if="skeletonLines.lf" v-bind="skeletonLines.lf" class="bone limb-bone" />
          <line v-if="skeletonLines.rf" v-bind="skeletonLines.rf" class="bone limb-bone" />
        </svg>

        <div v-for="hold in placedHolds" :key="hold.id"
             class="hold-entity"
             :class="{ 'start-glow': isStart(hold.id), 'top-glow': isTop(hold.id) }"
             :style="getCoord(hold.id)">
          <div class="hold-svg" :style="{ color: getShapeColor(hold.hold_type), transform: `rotate(${hold.rotation}deg)` }">
            <div class="geometric-shape" :class="hold.hold_type.toLowerCase()">
              <div class="inner-shadow"></div>
              <div class="bolt-hole"></div>
            </div>
          </div>
          <div class="hold-tooltip">
            <div class="tooltip-row"><span class="label">ID:</span> {{ hold.id }}</div>
            <div class="tooltip-row"><span class="label">类型:</span> {{ hold.hold_type }}</div>
            <div class="tooltip-row"><span class="label">旋转:</span> {{ hold.rotation }}°</div>
          </div>
        </div>

        <div v-for="(pos, limb) in currentLimbs" :key="limb"
             class="limb-cursor" :class="limb.toLowerCase()"
             :style="getCoord(pos.id)">
          <span class="limb-icon">{{ getLimbEmoji(limb) }}</span>
        </div>
      </div>
    </div>
  </main>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  routeData: Object,
  routeSteps: Array,
  currentIndex: Number,
  profile: Object,
  placedHolds: Array,
  currentLimbs: Object,
  skeletonLines: Object
})

const emit = defineEmits(['update:currentIndex'])

const maxIndex = computed(() => Math.max(0, props.routeSteps.length - 1))

const isStart = (id) => props.routeSteps.some(s => s.step === 0 && s.hold_id === id)
const isTop = (id) => props.routeSteps.some(s => s.is_top && s.hold_id === id)

const getCoord = (id) => {
  if (!id) return { left: '50%', bottom: '50%' }
  const xIdx = id.charCodeAt(0) - 65
  const yIdx = parseInt(id.substring(1)) - 1
  return { left: `${8 + (xIdx / 10) * 84}%`, bottom: `${8 + (yIdx / 17) * 84}%` }
}
const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981')
const getLimbEmoji = (limb) => ({ LH: '✋', RH: '✋', LF: '🦶', RF: '🦶' }[limb] || limb)

const updateIndex = (value) => {
  emit('update:currentIndex', parseInt(value))
}
</script>

<style scoped>
.stage { flex: 1; display: flex; flex-direction: column; padding: 30px; position: relative; overflow-y: auto; }
.stage-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 30px; gap: 40px; }
.route-info { flex: 1; }
.route-info h2 { font-size: 1.8rem; margin: 0 0 15px 0; background: linear-gradient(90deg, #f8fafc, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800; }
.commentary-card {
  background: rgba(30, 41, 59, 0.5); border: 1px solid rgba(51, 65, 85, 0.5); border-left: 4px solid #3b82f6;
  padding: 15px 20px; border-radius: 0 12px 12px 0; position: relative; max-width: 600px;
}
.quote-icon { position: absolute; top: -10px; left: 10px; font-size: 3rem; color: #3b82f6; opacity: 0.2; font-family: serif; }
.commentary-card p { margin: 0; font-size: 0.95rem; line-height: 1.6; color: #cbd5e1; font-style: italic; }
.controls {
  background: #1e293b; padding: 20px; border-radius: 16px; border: 1px solid #334155;
  width: 300px; display: flex; flex-direction: column; gap: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.2);
}
.control-labels { display: flex; justify-content: space-between; align-items: center; }
.step-counter { font-size: 0.85rem; color: #94a3b8; font-weight: 600; }
.difficulty-tag { background: #3b82f6; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; }
.modern-slider {
  -webkit-appearance: none; width: 100%; height: 6px; background: #0f172a; border-radius: 3px; outline: none;
}
.modern-slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 18px; height: 18px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: 3px solid #1e293b; transition: 0.2s;
}
.modern-slider::-webkit-slider-thumb:hover { transform: scale(1.2); box-shadow: 0 0 15px rgba(59, 130, 246, 0.5); }
.wall-display { flex: 1; display: flex; justify-content: center; align-items: center; padding: 20px 0; }
.wall-frame {
  width: 450px; height: 650px; 
  background: #2a1e12;
  background-image: 
    repeating-linear-gradient(45deg, rgba(0,0,0,0.05) 0px, rgba(0,0,0,0.05) 2px, transparent 2px, transparent 10px),
    radial-gradient(circle at 50% 50%, #3d2b1f 0%, #2a1e12 100%);
  border-radius: 15px; position: relative;
  box-shadow: 0 20px 50px rgba(0,0,0,0.5), inset 0 0 60px rgba(0,0,0,0.3); 
  border: 12px solid #1a120b;
}
.axis-x, .axis-y {
  position: absolute; color: #846345; font-size: 10px; font-weight: bold; font-family: monospace;
}
.axis-x { bottom: -25px; left: 8%; right: 8%; display: flex; justify-content: space-between; }
.axis-y { left: -25px; bottom: 8%; top: 8%; display: flex; flex-direction: column-reverse; justify-content: space-between; }
.hole { 
  position: absolute; width: 8px; height: 8px; 
  background: #1a120b; border-radius: 50%; transform: translate(-50%, 50%); 
  box-shadow: inset 0 2px 4px rgba(0,0,0,0.8), 0 1px 1px rgba(255,255,255,0.1);
}
.skeleton-layer {
  position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; z-index: 15;
}
.bone { stroke: rgba(255, 255, 255, 0.3); stroke-width: 4; stroke-linecap: round; transition: all 0.6s cubic-bezier(0.4, 0, 0.2, 1); }
.limb-bone { stroke-dasharray: 4 6; stroke: rgba(255, 255, 255, 0.2); }
.body-bone { stroke: rgba(255, 255, 255, 0.5); stroke-width: 6; }
.hold-entity { 
  position: absolute; transform: translate(-50%, 50%); z-index: 10; 
  cursor: help; transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.hold-entity:hover { transform: translate(-50%, 50%) scale(1.3); z-index: 100; }
.hold-tooltip {
  position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
  background: #0f172a; border: 1px solid #3b82f6; padding: 8px 12px; border-radius: 6px;
  font-size: 0.7rem; white-space: nowrap; opacity: 0; pointer-events: none;
  transition: 0.2s; margin-bottom: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.4);
}
.hold-entity:hover .hold-tooltip { opacity: 1; transform: translateX(-50%) translateY(-5px); }
.tooltip-row { margin-bottom: 2px; }
.tooltip-row .label { color: #64748b; font-weight: bold; margin-right: 4px; }
.geometric-shape { 
  width: 32px; height: 32px; background: currentColor; 
  box-shadow: 
    inset -4px -4px 8px rgba(0,0,0,0.4),
    inset 4px 4px 8px rgba(255,255,255,0.3),
    0 8px 15px rgba(0,0,0,0.4);
  opacity: 0.95; 
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.inner-shadow { position: absolute; inset: 0; background: radial-gradient(circle at 30% 30%, transparent 50%, rgba(0,0,0,0.2) 100%); pointer-events: none; }
.bolt-hole { width: 6px; height: 6px; background: #1a120b; border-radius: 50%; box-shadow: inset 0 1px 2px black; opacity: 0.6; }
.jug { border-radius: 35% 65% 65% 35% / 30% 30% 70% 70%; width: 38px; height: 32px; }
.crimp { height: 12px; width: 34px; border-radius: 4px; }
.sloper { border-radius: 50%; width: 40px; height: 40px; filter: contrast(1.1); }
.pinch { width: 14px; height: 36px; border-radius: 8px; }
.pocket { border-radius: 50%; background: transparent !important; border: 8px solid currentColor; box-shadow: 0 5px 10px rgba(0,0,0,0.3); }
.pocket .bolt-hole { display: none; }
.foot { width: 16px; height: 16px; clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%); }
.start-glow::after { content: ''; position: absolute; width: 60px; height: 60px; border: 3px solid #10b981; border-radius: 50%; top:-14px; left:-14px; animation: circle-pulse 2s infinite; box-shadow: 0 0 20px #10b981; pointer-events: none; }
.top-glow::after { content: ''; position: absolute; width: 60px; height: 60px; border: 3px solid #ef4444; border-radius: 50%; top:-14px; left:-14px; animation: circle-pulse 2s infinite; box-shadow: 0 0 20px #ef4444; pointer-events: none; }
@keyframes circle-pulse {
  0% { transform: scale(0.8); opacity: 0.8; }
  50% { transform: scale(1.1); opacity: 0.4; }
  100% { transform: scale(0.8); opacity: 0.8; }
}
.limb-cursor {
  position: absolute; width: 32px; height: 32px; border-radius: 50%; z-index: 20;
  display: flex; align-items: center; justify-content: center; font-size: 16px;
  transform: translate(-50%, 50%); 
  box-shadow: 0 5px 15px rgba(0,0,0,0.4); 
  border: 3px solid white; 
  transition: all 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.limb-icon { filter: drop-shadow(0 2px 2px rgba(0,0,0,0.3)); }
.lh { background-color: #E91E63; color: white; } 
.rh { background-color: #9C27B0; color: white; } 
.lf { background-color: #3F51B5; color: white; } 
.rf { background-color: #00BCD4; color: white; }
</style>
