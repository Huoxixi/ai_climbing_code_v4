<template>
  <div class="container">
    <h1>🧗‍♂️ 智行通途 (AI 智能攀岩定线 V6.0)</h1>
    <p class="subtitle">商用级数字双生岩板 | 有限岩点极简主义 | 物理规则校验</p>

    <div class="control-panel">
      <div class="input-group">
        <label>攀岩者身高 (cm)</label>
        <input type="number" v-model="profile.height" placeholder="175"/>
      </div>
      <div class="input-group">
        <label>攀岩者臂展 (cm)</label>
        <input type="number" v-model="profile.arm_span" placeholder="180"/>
      </div>
      <div class="input-group">
        <label>目标难度</label>
        <select v-model="profile.target_difficulty">
          <option value="V0">V0 (新手启蒙 - 如爬梯般稳定)</option>
          <option value="V1">V1 (入门进阶 - 需注意重心转移)</option>
          <option value="V2">V2 (基础挑战 - 引入少量侧拉或小跨度)</option>
          <option value="V3">V3 进阶挑战 (动态发力)</option> 
        </select>
      </div>
      <button @click="generateRoute" :disabled="loading" class="primary-btn">
        {{ loading ? '🧠 深度演算与纠错中...' : '🚀 生成商用路线' }}
      </button>
    </div>

    <div v-if="error" class="error-box">⚠️ {{ error }}</div>

    <div class="result-area" v-if="routeSteps.length > 0 || routeName">
      <h2>📍 路线演算报告: <span class="route-name">{{ routeName || '未命名挑战' }}</span></h2>
      
      <div class="visual-dashboard">
        <div class="timeline">
          <div class="scroll-container">
            <div 
              class="step-card" 
              v-for="movement in routeSteps" 
              :key="movement.step + '-' + movement.limb"
              :class="{ 'start-step': movement.step === 0, 'top-step': movement.is_top }"
            >
              <div class="step-header">
                <span class="step-num">{{ movement.step === 0 ? 'START' : `Step ${movement.step}` }}</span>
                <span class="limb-badge" :class="movement.limb">{{ movement.limb }}</span>
                <span class="target-hold">➔ {{ movement.hold_id }}</span>
              </div>
              <p class="reasoning">💡 {{ movement.intent }}</p>
            </div>
          </div>
        </div>

        <div class="wall-container">
          <div class="board-wrapper">
            
            <div class="y-axis-area">
              <div class="y-axis-inner">
                <span 
                  v-for="y in 18" 
                  :key="'y-'+y" 
                  class="y-label"
                  :style="{ bottom: `${8 + ((y-1) / 17) * 84}%` }"
                >
                  {{ y }}
                </span>
              </div>
            </div>
            
            <div class="wall-main-col">
              
              <div class="wall-and-ruler">
                <div class="wall">
                  
                  <div class="grid-layer">
                    <template v-for="y in 18" :key="'hole-row-'+y">
                      <div 
                        v-for="(char, xIndex) in 'ABCDEFGHIJK'.split('')" 
                        :key="'hole-'+char+y"
                        class="t-nut-hole"
                        :style="{ left: `${8 + (xIndex/10)*84}%`, bottom: `${8 + ((y-1)/17)*84}%` }"
                      ></div>
                    </template>
                  </div>
                  
                  <div 
                    v-for="hold in routeHolds" 
                    :key="'hold-'+hold.id"
                    class="mounted-hold"
                    :class="[
                      hold.type === 'Jug' || hold.type === 'Sloper' ? 'size-large' : 'size-small',
                      'type-' + hold.type,
                      { 'is-start-hold': isStartHold(hold.id), 'is-top-hold': isTopHold(hold.id) }
                    ]"
                    :style="getCoordinateStyle(hold.id)"
                  >
                    <div class="hold-limbs-row" v-if="hold.type !== 'Sloper'">
                      <span v-for="limb in getLimbsOnHold(hold.id)" :key="limb" class="limb-dot" :class="limb" :title="getChineseLimb(limb)"></span>
                    </div>
                  </div>
                </div>

                <div class="ruler-area">
                  <div class="height-ruler-container">
                    <div class="ruler-line" :style="{ height: referencePersonHeight }">
                      <div class="ruler-label">👤 {{ profile.height }} cm</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="x-axis-area">
                <div class="x-axis-inner">
                  <span 
                    v-for="(char, xIndex) in 'ABCDEFGHIJK'.split('')" 
                    :key="'x-'+char"
                    class="x-label"
                    :style="{ left: `${8 + (xIndex / 10) * 84}%` }"
                  >
                    {{ char }}
                  </span>
                </div>
              </div>

              <div class="scale-info">
                <span class="scale-item">📐 物理比例尺：1 格 = 20 cm</span>
                <span class="scale-item limit">🧗‍♂️ 当前臂展极限跨度 ≈ {{ Math.floor(profile.arm_span / 20) }} 格</span>
              </div>

              <p class="wall-caption">🧗‍♀️ 虚拟岩板孪生映射 (11x18 标准网格孔位)</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import axios from 'axios'

const profile = ref({ height: 175, arm_span: 180, target_difficulty: 'V1' })
const loading = ref(false)
const error = ref('')
const routeSteps = ref([])
const routeName = ref('')

const getChineseLimb = (limbCode) => {
  const map = { 'LH': '左手', 'RH': '右手', 'LF': '左脚', 'RF': '右脚' };
  return map[limbCode] || limbCode;
}

const generateRoute = async () => {
  loading.value = true
  error.value = ''
  routeSteps.value = []
  
  try {
    const payload = {
      climber: { height_cm: profile.value.height, span_cm: profile.value.arm_span },
      target_difficulty: profile.value.target_difficulty
    };
    
    const response = await axios.post('http://106.14.216.81:8000/api/generate', payload);
    
    if (response.data && response.data.beta_sequence) {
      routeSteps.value = response.data.beta_sequence;
      routeName.value = response.data.route_name || '未命名路线';
    } else {
      error.value = "未获取到路线序列，请检查后端返回格式";
    }
  } catch (err) {
    error.value = `请求失败！可能是大模型多次反思失败，或数据校验被拦截（物理不合规）。报错详情: ${err.message}`
  } finally {
    loading.value = false
  }
}

// 物理世界映射公式
const pxPerCm = 580 / 360; 
const referencePersonHeight = computed(() => {
  const h = profile.value.height || 175; 
  return `${h * pxPerCm}px`;
});

// 视觉岩点生成逻辑 (优化了 Crimp 的分布)
const getHoldVisualType = (holdId) => {
  if (!holdId) return 'Jug';
  const y = parseInt(holdId.substring(1));
  const charCode = holdId.charCodeAt(0);
  const hash = y + charCode;

  if (y <= 6) {
    const startPool = ['Jug', 'Pinch', 'Sloper', 'Jug']; 
    return startPool[hash % startPool.length];
  }
  if (y >= 16) {
    return hash % 2 === 0 ? 'Crimp' : 'Sloper';
  }
  const midPool = ['Jug', 'Sloper', 'Pinch', 'Jug', 'Sloper', 'Pinch', 'Crimp']; 
  return midPool[hash % midPool.length];
}

const routeHolds = computed(() => {
  const uniqueHolds = new Map();
  routeSteps.value.forEach(step => {
    if (!uniqueHolds.has(step.hold_id)) {
      uniqueHolds.set(step.hold_id, {
        id: step.hold_id,
        type: getHoldVisualType(step.hold_id),
        steps: [step.step],
        movements: [step]
      });
    } else {
      const hold = uniqueHolds.get(step.hold_id);
      if (!hold.steps.includes(step.step)) hold.steps.push(step.step);
      hold.movements.push(step);
    }
  });
  return Array.from(uniqueHolds.values());
});

const isStartHold = (holdId) => routeSteps.value.some(s => s.hold_id === holdId && s.step === 0);
const isTopHold = (holdId) => routeSteps.value.some(s => s.hold_id === holdId && s.is_top);
const getLimbsOnHold = (holdId) => {
  const holdsOnId = routeSteps.value.filter(s => s.hold_id === holdId);
  const latestLimbs = new Map();
  holdsOnId.forEach(h => latestLimbs.set(h.limb, h.step));
  return Array.from(latestLimbs.keys());
}

// 🌟 全局统一绝对坐标系转换核心
const getCoordinateStyle = (hold_id) => {
  if (!hold_id || hold_id.length < 2) return { left: '50%', bottom: '50%' };
  const xChar = hold_id.charAt(0).toUpperCase();
  const yNum = parseInt(hold_id.substring(1));
  
  const xIndex = Math.max(0, Math.min(10, xChar.charCodeAt(0) - 65));
  const yIndex = Math.max(0, Math.min(17, yNum - 1));
  
  return {
    left: `${8 + (xIndex / 10) * 84}%`,
    bottom: `${8 + (yIndex / 17) * 84}%`
  };
}
</script>

<style scoped>
/* ================= 全局排版 ================= */
.container { max-width: 1000px; margin: 40px auto; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; color: #333; }
h1 { text-align: center; margin-bottom: 5px; font-size: 2.2em; color: #0f172a;}
.subtitle { text-align: center; color: #64748b; margin-bottom: 30px; font-weight: bold; font-size: 0.9em;}
.route-name { color: #2563eb; font-weight: 900; }

/* ================= 控制台 ================= */
.control-panel { 
  display: flex; gap: 20px; align-items: flex-end; justify-content: space-between;
  background: white; padding: 25px; border-radius: 12px; border: 1px solid #e2e8f0;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.input-group { display: flex; flex-direction: column; gap: 8px; flex: 1;}
label { font-weight: 600; font-size: 0.85em; color: #475569; }
input, select { padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.95em; outline: none;}
input:focus, select:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2); }

.primary-btn {
  padding: 12px 24px; height: 42px; background: #0f172a; color: white; border: none; border-radius: 6px; 
  font-weight: bold; font-size: 0.95em; cursor: pointer; transition: all 0.2s; white-space: nowrap;
}
.primary-btn:hover:not(:disabled) { background: #1e293b; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15);}
.primary-btn:disabled { background: #94a3b8; cursor: not-allowed; transform: none; box-shadow: none;}
.error-box { margin-top: 20px; padding: 15px; background: #fef2f2; border: 1px solid #fecaca; color: #ef4444; border-radius: 8px; font-weight: bold; }

/* ================= 视觉面板分栏布局 ================= */
.visual-dashboard { display: flex; gap: 30px; margin-top: 20px; align-items: flex-start; }

/* ================= 左侧：文字时间轴 ================= */
.timeline { 
  flex: 1; position: relative; height: 650px; 
}
.scroll-container { 
  position: absolute; top:0; left:0; right:0; bottom:0; 
  overflow-y: auto; padding-right: 10px; 
  display: flex; flex-direction: column; gap: 10px;
}
.step-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; border-left: 4px solid #3b82f6; }
.step-card.start-step { border-left-color: #10b981; background: #f0fdf4; }
.step-card.top-step { border-left-color: #ef4444; background: #fef2f2; }
.step-header { display: flex; align-items: center; gap: 10px; margin-bottom: 5px; }
.step-num { font-weight: 900; color: #64748b; font-size: 0.85em; min-width: 45px;}
.target-hold { font-family: monospace; font-weight: bold; color: #0f172a; font-size: 1em;}
.reasoning { color: #475569; font-size: 0.85em; line-height: 1.4; margin: 0;}
.limb-badge { padding: 2px 6px; border-radius: 4px; font-size: 0.75em; font-weight: bold; }
.limb-badge.LF, .limb-badge.RF { background: #dbeafe; color: #1e3a8a; }
.limb-badge.LH, .limb-badge.RH { background: #fee2e2; color: #991b1b; }


/* ================= 🎯 大一统坐标系 (Grand Unified Coordinates) ================= */
.wall-container { flex: 0 0 540px; display: flex; flex-direction: column; }
/* 🎯 修复 1：将 align-items 改为 flex-start，严禁父级拉伸 Y 轴 */
.board-wrapper { 
  display: flex; 
  align-items: flex-start; 
  margin-bottom: 10px; 
}

/* 🎯 修复 2：将 Y 轴高度死锁为 600px，与岩板外部尺寸分毫不差 */
.y-axis-area {
  width: 30px; 
  height: 600px; /* 强制等高 */
  flex-shrink: 0; /* 防止被挤压 */
  margin-right: 10px; 
  padding: 10px 0; /* 上下扣除 10px 边框，暴露出完美的 580px 内胆空间 */
  box-sizing: border-box;
}
.y-axis-inner { position: relative; width: 100%; height: 100%; }
.y-label {
  position: absolute; right: 0;
  transform: translateY(50%); /* 确保中心对齐 */
  font-weight: bold; color: #94a3b8; font-size: 0.85em; 
}

.wall-main-col { display: flex; flex-direction: column; }
.wall-and-ruler { display: flex; align-items: stretch; }

/* 岩板本体 */
.wall {
  width: 420px; height: 600px;
  background: #1e293b; border-radius: 12px; position: relative;
  box-shadow: inset 0 0 40px rgba(0,0,0,0.8), 0 10px 25px -5px rgba(0,0,0,0.2);
  border: 10px solid #0f172a; box-sizing: border-box; overflow: hidden;
}

/* 抛弃 Flexbox 间距，孔位使用与岩点一样的绝对坐标计算 */
.grid-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
.t-nut-hole {
  position: absolute; width: 6px; height: 6px; background: #0f172a; 
  border-radius: 50%;
  transform: translate(-50%, 50%); /* 孔位中心严格对齐坐标点 */
  box-shadow: inset 0 1px 2px rgba(255,255,255,0.1); 
}

/* 标尺区域跟随岩板高度 */
.ruler-area {
  padding: 10px 0; /* 抵消边框，对齐 580px 净高度 */
  margin-left: 15px; box-sizing: border-box;
}
.height-ruler-container { position: relative; width: 60px; height: 100%; }
.ruler-line {
  position: absolute; bottom: 0; left: 20px; width: 2px;
  background: repeating-linear-gradient(to top, #94a3b8, #94a3b8 6px, transparent 6px, transparent 12px);
  transition: height 0.3s ease;
}
.ruler-line::after { content: ''; position: absolute; top: 0; left: -15px; width: 32px; height: 2px; background: #ef4444; box-shadow: 0 0 8px rgba(239, 68, 68, 0.6); }
.ruler-label {
  position: absolute; top: -28px; left: 50%; transform: translateX(-50%);
  background: #0f172a; color: #f8fafc; padding: 4px 8px; border-radius: 4px;
  font-size: 0.8em; font-weight: bold; white-space: nowrap; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
}

/* 岩点视图 */
.mounted-hold {
  position: absolute; background-color: #3b82f6; border-radius: 50%; 
  transform: translate(-50%, 50%); /* 岩点中心严格对齐坐标点 */
  display: flex; align-items: center; justify-content: center; z-index: 10;
  transition: all 0.2s ease; box-sizing: border-box; 
}
.mounted-hold.size-large { width: 28px; height: 28px; }
.mounted-hold.size-small { width: 14px; height: 14px; }
.mounted-hold.type-Crimp::after { content: ''; display: block; width: 6px; height: 6px; background-color: #0f172a; border-radius: 50%;}
.mounted-hold.is-start-hold { box-shadow: inset 0 0 0 2px white, 0 0 0 6px rgba(59, 130, 246, 0.4); z-index: 15; }
.mounted-hold.is-top-hold { box-shadow: inset 0 0 0 2px white, 0 0 0 5px #ef4444; z-index: 20; }

/* X 轴容器镜像 */
.x-axis-area {
  width: 420px; padding: 0 10px; /* 抵消岩板左右 10px 边框，暴露出 400px 的净空间 */
  box-sizing: border-box; margin-top: 10px;
}
.x-axis-inner { position: relative; width: 100%; height: 20px; }
.x-label {
  position: absolute;
  transform: translateX(-50%); /* 确保中心对齐 */
  font-weight: bold; color: #94a3b8; font-size: 0.85em; text-align: center;
}

/* 比例尺 */
.scale-info {
  display: flex; justify-content: space-between;
  width: 400px; margin-left: 10px; margin-top: 15px; padding: 8px 12px;
  background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; box-sizing: border-box;
}
.scale-item { font-size: 0.85em; font-weight: 700; color: #475569; }
.scale-item.limit { color: #ef4444; }
.wall-caption { width: 400px; text-align: center; margin-left: 10px; margin-top: 10px; color: #94a3b8; font-size: 0.8em; }

</style>