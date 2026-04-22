<template>
  <div class="wall-display">
    <div class="wall-frame">
      <!-- 坐标轴 -->
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

      <!-- 骨架连线 -->
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
        <div class="hold-visual" :style="{ transform: `rotate(${hold.rotation}deg)` }">
          <!-- 优先显示图片 -->
          <div v-if="getHoldImage(hold)" class="hold-image-container">
            <img :src="getHoldImage(hold)" class="hold-image" />
          </div>
          
          <!-- 无图片时回退到 CSS 图形 -->
          <div v-else class="geometric-shape" 
               :class="hold.hold_type.toLowerCase()"
               :style="{ color: getShapeColor(hold.hold_type) }">
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
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  placedHolds: Array,
  routeSteps: Array,
  currentIndex: Number,
  holdImageMap: Object,
});

const API_BASE_URL = 'http://127.0.0.1:8000';

const getCoord = (id) => {
  if (!id) return { left: '50%', bottom: '50%' };
  const xIdx = id.charCodeAt(0) - 65;
  const yIdx = parseInt(id.substring(1)) - 1;
  return { left: `${8 + (xIdx / 10) * 84}%`, bottom: `${8 + (yIdx / 17) * 84}%` };
};

const getHoldImage = (hold) => {
  const typeMap = props.holdImageMap[hold.hold_type];
  if (!typeMap) return null;
  const imageUrl = typeMap[hold.variant] || typeMap['default'];
  return imageUrl ? `${API_BASE_URL}${imageUrl}` : null;
};

const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981');
const getLimbEmoji = (limb) => ({ LH: '✋', RH: '✋', LF: '🦶', RF: '🦶' }[limb] || limb);

const isStart = (id) => props.routeSteps.some(s => s.step === 0 && s.hold_id === id);
const isTop = (id) => props.routeSteps.some(s => s.is_top && s.hold_id === id);

const currentLimbs = computed(() => {
  const limbs = {};
  props.routeSteps.slice(0, props.currentIndex + 1).forEach(m => {
    limbs[m.limb] = { id: m.hold_id };
  });
  return limbs;
});

const skeletonLines = computed(() => {
  const limbs = currentLimbs.value;
  if (!limbs.LH && !limbs.RH && !limbs.LF && !limbs.RF) return {};

  const getPos = (id) => {
    const coords = getCoord(id);
    return {
      x: parseFloat(coords.left),
      y: 100 - parseFloat(coords.bottom)
    };
  };

  const res = {};
  const p = {
    lh: limbs.LH ? getPos(limbs.LH.id) : null,
    rh: limbs.RH ? getPos(limbs.RH.id) : null,
    lf: limbs.LF ? getPos(limbs.LF.id) : null,
    rf: limbs.RF ? getPos(limbs.RF.id) : null
  };

  const activeLimbs = [p.lh, p.rh, p.lf, p.rf].filter(i => i);
  if (activeLimbs.length < 2) return {};
  
  const com = {
    x: activeLimbs.reduce((acc, curr) => acc + curr.x, 0) / activeLimbs.length,
    y: activeLimbs.reduce((acc, curr) => acc + curr.y, 0) / activeLimbs.length
  };

  if (p.lh) res.lh = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.lh.x}%`, y2: `${p.lh.y}%` };
  if (p.rh) res.rh = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.rh.x}%`, y2: `${p.rh.y}%` };
  if (p.lf) res.lf = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.lf.x}%`, y2: `${p.lf.y}%` };
  if (p.rf) res.rf = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.rf.x}%`, y2: `${p.rf.y}%` };

  const hands = [p.lh, p.rh].filter(i => i);
  const feet = [p.lf, p.rf].filter(i => i);
  if (hands.length && feet.length) {
    const handCom = {
      x: hands.reduce((acc, curr) => acc + curr.x, 0) / hands.length,
      y: hands.reduce((acc, curr) => acc + curr.y, 0) / hands.length
    };
    const footCom = {
      x: feet.reduce((acc, curr) => acc + curr.x, 0) / feet.length,
      y: feet.reduce((acc, curr) => acc + curr.y, 0) / feet.length
    };
    res.body = { x1: `${handCom.x}%`, y1: `${handCom.y}%`, x2: `${footCom.x}%`, y2: `${footCom.y}%` };
  }

  return res;
});
</script>

<style scoped>
/* Styles from App.vue */
.wall-display { flex: 1; display: flex; justify-content: center; align-items: center; padding: 20px 0; }
.wall-frame {
  width: 450px; height: 650px; 
  background: #2a1e12; /* 木纹底色 */
  background-image: 
    repeating-linear-gradient(45deg, rgba(0,0,0,0.05) 0px, rgba(0,0,0,0.05) 2px, transparent 2px, transparent 10px),
    radial-gradient(circle at 50% 50%, #3d2b1f 0%, #2a1e12 100%);
  border-radius: 15px; position: relative;
  box-shadow: 0 20px 50px rgba(0,0,0,0.5), inset 0 0 60px rgba(0,0,0,0.3); 
  border: 12px solid #1a120b;
}

/* 坐标轴样式 */
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

.hold-image-container {
  width: 42px; height: 42px; display: flex; align-items: center; justify-content: center;
}
.hold-image {
  max-width: 100%; max-height: 100%; object-fit: contain; filter: drop-shadow(0 4px 6px rgba(0,0,0,0.5));
}

.hold-tooltip {
  position: absolute; bottom: 110%; left: 50%; transform: translateX(-50%) translateY(10px);
  background: rgba(15, 23, 42, 0.95); border: 1px solid #3b82f6; padding: 10px 14px; border-radius: 8px;
  font-size: 0.75rem; white-space: nowrap; opacity: 0; pointer-events: none;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 10px 20px rgba(0,0,0,0.6); backdrop-filter: blur(4px);
  z-index: 1000;
}
.hold-entity:hover .hold-tooltip { opacity: 1; transform: translateX(-50%) translateY(0); }
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