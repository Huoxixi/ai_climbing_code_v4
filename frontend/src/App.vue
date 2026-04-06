<template>
  <div class="container">
    <h1>🧗‍♂️ 智行通途 (AI 智能攀岩定线 V7.5 拟真版)</h1>
    <p class="subtitle">商用级数字双生岩板 | 真实比例矢量材质 | 物理时序回放</p>

    <div class="control-panel">
      <div class="profile-section">
        <h3 class="section-title">👤 攀岩者参数</h3>
        <div class="input-grid">
          <div class="input-group">
            <label>身高 (cm)</label>
            <input type="number" v-model="profile.height" placeholder="175"/>
          </div>
          <div class="input-group">
            <label>臂展 (cm)</label>
            <input type="number" v-model="profile.arm_span" placeholder="180"/>
          </div>
          <div class="input-group full-width">
            <label>目标难度</label>
            <select v-model="profile.target_difficulty">
              <option value="V0">V0 (新手 - 稳定爬梯，大把手)</option>
              <option value="V1">V1 (入门 - 重心转移，大把手为主)</option>
              <option value="V2">V2 (基础 - 引入抠口与大跨度)</option>
              <option value="V3">V3 (进阶 - 动态发力与摩擦点折叠)</option> 
            </select>
          </div>
        </div>
      </div>

      <div class="recipe-section">
        <h3 class="section-title">🧪 定线材料配方</h3>
        <div class="recipe-grid">
          <div v-for="type in holdTypes" :key="type" class="recipe-item">
            <div class="recipe-label">
              <span class="color-dot" :style="{ backgroundColor: getShapeColor(type) }"></span>
              {{ type }}
            </div>
            <input type="number" v-model.number="recipe[type]" min="0" max="15" />
          </div>
        </div>
      </div>
    </div>

    <div class="action-bar">
      <button @click="generateRoute" :disabled="loading" class="primary-btn">
        {{ loading ? '🧠 严格演算与纠错中...' : '🚀 生成商用路线' }}
      </button>
      <div v-if="error" class="error-box">⚠️ {{ error }}</div>
    </div>

    <div class="result-area" v-if="routeData">
      <div class="result-header">
        <h2>📍 路线报告: <span class="route-name">{{ routeData.route_name || '未命名挑战' }}</span></h2>
        <div class="playback-controls">
          <label>动作演示: Step {{ currentStep }} / {{ maxStep }}</label>
          <input type="range" v-model.number="currentStep" min="0" :max="maxStep" class="slider" />
        </div>
      </div>
      
      <div class="visual-dashboard">
        <div class="timeline">
          <div class="scroll-container">
            <div class="step-card" v-for="m in routeSteps" :key="m.step + '-' + m.limb"
                 :class="{ 'start-step': m.step === 0, 'top-step': m.is_top, 'active-step': m.step === currentStep }"
                 @click="currentStep = m.step">
              <div class="step-header">
                <span class="step-num">{{ m.step === 0 ? 'START' : `Step ${m.step}` }}</span>
                <span class="limb-badge" :class="m.limb">{{ m.limb }}</span>
                <span class="target-hold">➔ {{ m.hold_id }}</span>
                <span class="shape-badge" :style="{ color: getShapeColor(m.shape_type) }">{{ m.shape_type || 'Jug' }}</span>
              </div>
              <p class="reasoning">💡 {{ m.intent || '起步稳固重心' }}</p>
            </div>
          </div>
        </div>

        <div class="wall-container">
          <div class="board-wrapper">
            <div class="y-axis-area">
              <div class="y-axis-inner">
                <span v-for="y in 18" :key="'y-'+y" class="y-label" :style="{ bottom: `${8 + ((y-1) / 17) * 84}%` }">{{ y }}</span>
              </div>
            </div>
            
            <div class="wall-main-col">
              <div class="wall-and-ruler">
                <div class="wall">
                  <div class="grid-layer">
                    <template v-for="y in 18" :key="'hole-row-'+y">
                      <div v-for="(char, xIndex) in 'ABCDEFGHIJK'.split('')" :key="'hole-'+char+y"
                        class="t-nut-hole" :style="{ left: `${8 + (xIndex/10)*84}%`, bottom: `${8 + ((y-1)/17)*84}%` }">
                      </div>
                    </template>
                  </div>
                  
                  <div v-for="hold in uniqueRouteHolds" :key="'hold-'+hold.id"
                    class="mounted-hold" :class="{ 'is-start': hold.isStart, 'is-top': hold.isTop }"
                    :style="getCoordinateStyle(hold.id)"
                  >
                    <div class="hold-shape-wrapper" 
                         :style="{ color: getShapeColor(hold.shape_type), transform: `rotate(${getHoldRotation(hold.id, hold.shape_type)}deg)` }">
                      <svg viewBox="0 0 100 100" class="organic-hold">
                        <defs>
                          <filter id="3d-bevel" x="-20%" y="-20%" width="140%" height="140%">
                            <feDropShadow dx="2" dy="4" stdDeviation="3" flood-opacity="0.6" />
                            <feComponentTransfer><feFuncA type="linear" slope="0.9"/></feComponentTransfer>
                          </filter>
                        </defs>
                        
                        <g filter="url(#3d-bevel)">
                          <path v-if="hold.shape_type === 'Jug'" fill="currentColor" d="M 15 30 Q 50 10 85 30 L 85 70 Q 50 90 15 70 Z" />
                          
                          <path v-else-if="hold.shape_type === 'Crimp'" fill="currentColor" d="M 20 40 Q 50 35 80 40 L 75 60 Q 50 65 25 60 Z" />
                          
                          <circle v-else-if="hold.shape_type === 'Sloper'" cx="50" cy="50" r="42" fill="currentColor" opacity="0.85" />
                          
                          <rect v-else-if="hold.shape_type === 'Pinch'" x="35" y="15" width="30" height="70" rx="15" fill="currentColor" />
                          
                          <g v-else-if="hold.shape_type === 'Pocket'">
                            <circle cx="50" cy="50" r="32" fill="currentColor" />
                            <circle cx="50" cy="55" r="14" fill="#111" /> </g>

                          <polygon v-else-if="hold.shape_type === 'Foot'" fill="currentColor" points="50,35 65,50 50,65 35,50" />
                          
                          <path v-else fill="currentColor" d="M 15 30 Q 50 10 85 30 L 85 70 Q 50 90 15 70 Z" />
                        </g>

                        <circle v-if="hold.shape_type !== 'Pocket'" cx="50" cy="48" r="3.5" fill="#111" />
                        <circle v-if="hold.shape_type === 'Pocket'" cx="50" cy="25" r="3" fill="#111" />
                      </svg>
                    </div>
                  </div>

                  <div v-for="(limbData, limbName) in currentLimbs" :key="'limb-'+limbName"
                       class="limb-marker" :class="limbName.toLowerCase()" :style="getCoordinateStyle(limbData.id)">
                    {{ limbName }}
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
                  <span v-for="(char, xIndex) in 'ABCDEFGHIJK'.split('')" :key="'x-'+char" class="x-label" :style="{ left: `${8 + (xIndex / 10) * 84}%` }">{{ char }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive } from 'vue'
import axios from 'axios'

const profile = ref({ height: 175, arm_span: 180, target_difficulty: 'V1' })
const holdTypes = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot']
const recipe = reactive({ Jug: 4, Crimp: 0, Sloper: 0, Pinch: 0, Pocket: 0, Foot: 3 })

const loading = ref(false)
const error = ref('')
const routeData = ref(null)
const currentStep = ref(0)

const generateRoute = async () => {
  loading.value = true; error.value = ''; routeData.value = null; currentStep.value = 0
  const cleanRecipe = {}
  Object.keys(recipe).forEach(k => { if (recipe[k] > 0) cleanRecipe[k] = recipe[k] })
  try {
    const apiUrl = import.meta.env.VITE_API_BASE_URL ? `${import.meta.env.VITE_API_BASE_URL}/api/generate` : 'http://106.14.216.81:8000/api/generate'
    const response = await axios.post(apiUrl, { climber: { height_cm: profile.value.height, span_cm: profile.value.arm_span }, target_difficulty: profile.value.target_difficulty, recipe: cleanRecipe })
    if (response.data && response.data.beta_sequence) {
      routeData.value = response.data
      let step = 0; const interval = setInterval(() => { if (step < maxStep.value) { currentStep.value = ++step; } else { clearInterval(interval); } }, 800);
    } else { error.value = "未获取到路线序列，请检查后端返回格式" }
  } catch (err) { error.value = `拦截！报错: ${err.response?.data?.detail || err.message}` } 
  finally { loading.value = false }
}

const routeSteps = computed(() => routeData.value?.beta_sequence || [])
const maxStep = computed(() => routeSteps.value.length ? Math.max(...routeSteps.value.map(b => b.step)) : 0)

const uniqueRouteHolds = computed(() => {
  if (!routeSteps.value.length) return []
  const holdsMap = new Map()
  routeSteps.value.forEach(step => {
    if (!holdsMap.has(step.hold_id)) holdsMap.set(step.hold_id, { id: step.hold_id, shape_type: step.shape_type || 'Jug', isStart: step.step === 0, isTop: step.is_top || false })
    else if (step.is_top) holdsMap.get(step.hold_id).isTop = true
  })
  return Array.from(holdsMap.values())
})

const currentLimbs = computed(() => {
  const limbs = {}; routeSteps.value.filter(b => b.step <= currentStep.value).forEach(m => { limbs[m.limb] = { id: m.hold_id } }); return limbs
})

const pxPerCm = 580 / 360 
const referencePersonHeight = computed(() => `${(profile.value.height || 175) * pxPerCm}px`)

const getCoordinateStyle = (hold_id) => {
  if (!hold_id) return { left: '50%', bottom: '50%' }
  const xIndex = Math.max(0, Math.min(10, hold_id.charAt(0).toUpperCase().charCodeAt(0) - 65))
  const yIndex = Math.max(0, Math.min(17, parseInt(hold_id.substring(1)) - 1))
  return { left: `${8 + (xIndex / 10) * 84}%`, bottom: `${8 + (yIndex / 17) * 84}%` }
}

// 🌟 修正核心：物理岩点安装角度算法
const getHoldRotation = (id, shape) => {
  const hash = id.charCodeAt(0) * 17 + parseInt(id.substring(1)) * 23;
  if (shape === 'Crimp') return (hash % 10) - 5; // Crimp 绝不能竖着，必须近似水平(-5到5度)
  if (shape === 'Jug') return (hash % 30) - 15;  // Jug 允许微调
  if (shape === 'Pinch') return (hash % 40) - 20;// Pinch 主要是垂直方向
  return hash % 360; // 圆形/脚点随意
}

const getShapeColor = (type) => ({ Jug: '#4CAF50', Crimp: '#F44336', Sloper: '#FF9800', Pinch: '#9C27B0', Pocket: '#2196F3', Foot: '#9E9E9E' }[type] || '#4CAF50')
</script>

<style scoped>
.container { max-width: 1050px; margin: 30px auto; font-family: 'Segoe UI', system-ui, sans-serif; color: #333; }
h1 { text-align: center; margin-bottom: 5px; font-size: 2.2em; color: #0f172a;}
.subtitle { text-align: center; color: #64748b; margin-bottom: 30px; font-weight: bold; font-size: 0.9em;}
.control-panel { display: flex; gap: 20px; margin-bottom: 20px; }
.profile-section, .recipe-section { background: white; padding: 20px; border-radius: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.profile-section { flex: 1; } .recipe-section { flex: 1.2; }
.section-title { margin-top: 0; margin-bottom: 15px; font-size: 1.1em; color: #1e293b; border-bottom: 2px solid #f1f5f9; padding-bottom: 8px;}
.input-grid { display: flex; flex-wrap: wrap; gap: 15px; }
.input-group { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 120px;}
.input-group.full-width { min-width: 100%; }
label { font-weight: 600; font-size: 0.85em; color: #475569; }
input, select { padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 6px; outline: none;}
.recipe-desc { font-size: 0.8em; color: #64748b; margin-top: -10px; margin-bottom: 12px;}
.recipe-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.recipe-item { display: flex; align-items: center; justify-content: space-between; background: #f8fafc; padding: 6px 10px; border-radius: 6px; border: 1px solid #e2e8f0;}
.recipe-label { display: flex; align-items: center; gap: 6px; font-size: 0.85em; font-weight: 600; color: #475569;}
.color-dot { width: 10px; height: 10px; border-radius: 50%; }
.recipe-item input { width: 50px; padding: 4px; text-align: center; }
.action-bar { margin-bottom: 30px; }
.primary-btn { width: 100%; padding: 14px; background: #0f172a; color: white; border: none; border-radius: 8px; font-weight: bold; font-size: 1.1em; cursor: pointer; transition: all 0.2s;}
.primary-btn:disabled { background: #94a3b8; cursor: not-allowed; }
.error-box { margin-top: 15px; padding: 12px; background: #fef2f2; border: 1px solid #fecaca; color: #ef4444; border-radius: 8px; font-weight: bold; }
.result-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding: 15px; background: white; border-radius: 12px; border: 1px solid #e2e8f0;}
.result-header h2 { margin: 0; font-size: 1.4em; }
.route-name { color: #2563eb; font-weight: 900; }
.playback-controls { display: flex; align-items: center; gap: 15px; font-weight: bold; color: #475569;}
.slider { width: 200px; cursor: pointer; }
.visual-dashboard { display: flex; gap: 30px; align-items: flex-start; }
.timeline { flex: 1; position: relative; height: 650px; }
.scroll-container { position: absolute; top:0; left:0; right:0; bottom:0; overflow-y: auto; padding-right: 10px; display: flex; flex-direction: column; gap: 10px; }
.step-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; border-left: 4px solid #e2e8f0; cursor: pointer; transition: 0.2s; opacity: 0.6;}
.step-card.active-step { opacity: 1; border-left-color: #3b82f6; box-shadow: 0 4px 10px rgba(59,130,246,0.15); transform: translateX(5px);}
.step-card.start-step.active-step { border-left-color: #10b981; }
.step-card.top-step.active-step { border-left-color: #ef4444; }
.step-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.step-num { font-weight: 900; color: #64748b; font-size: 0.85em; min-width: 45px;}
.target-hold { font-family: monospace; font-weight: bold; color: #0f172a; font-size: 1em;}
.shape-badge { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.75em; border: 1px solid #cbd5e1; font-weight: 900;}
.reasoning { color: #475569; font-size: 0.85em; margin: 0;}
.limb-badge { padding: 2px 6px; border-radius: 4px; font-size: 0.75em; font-weight: bold; }
.limb-badge.LF, .limb-badge.RF { background: #dbeafe; color: #1e3a8a; }
.limb-badge.LH, .limb-badge.RH { background: #fee2e2; color: #991b1b; }
.wall-container { flex: 0 0 540px; display: flex; flex-direction: column; }
.board-wrapper { display: flex; align-items: flex-start; margin-bottom: 10px; }
.y-axis-area { width: 30px; height: 600px; margin-right: 10px; padding: 10px 0; box-sizing: border-box;}
.y-axis-inner { position: relative; width: 100%; height: 100%; }
.y-label { position: absolute; right: 0; transform: translateY(50%); font-weight: bold; color: #94a3b8; font-size: 0.85em; }
.wall-main-col { display: flex; flex-direction: column; }
.wall-and-ruler { display: flex; align-items: stretch; }
.wall { width: 420px; height: 600px; background: #1e293b; border-radius: 12px; position: relative; box-shadow: inset 0 0 40px rgba(0,0,0,0.8); border: 10px solid #0f172a; overflow: hidden;}
.grid-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }
.t-nut-hole { position: absolute; width: 6px; height: 6px; background: #0b1120; border-radius: 50%; transform: translate(-50%, 50%); box-shadow: inset 0 1px 2px rgba(255,255,255,0.15); }
.mounted-hold { position: absolute; z-index: 10; transform: translate(-50%, 50%); }
.hold-shape-wrapper { width: 44px; height: 44px; display: flex; justify-content: center; align-items: center; }
.organic-hold { width: 100%; height: 100%; overflow: visible; }
.mounted-hold.is-start::before { content:''; position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); width: 60px; height: 60px; border-radius: 50%; border: 3px dashed #10b981; animation: spin 10s linear infinite; z-index: -1;}
.mounted-hold.is-top::before { content:''; position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); width: 60px; height: 60px; border-radius: 50%; border: 3px dashed #ef4444; animation: spin 10s linear infinite; z-index: -1;}
@keyframes spin { 100% { transform: translate(-50%,-50%) rotate(360deg); } }
.limb-marker { position: absolute; z-index: 20; width: 22px; height: 22px; border-radius: 50%; transform: translate(-50%, 50%); display: flex; justify-content: center; align-items: center; font-size: 10px; font-weight: bold; color: white; border: 2px solid white; box-shadow: 0 3px 8px rgba(0,0,0,0.6); transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1); }
.lh { background-color: #E91E63; } .rh { background-color: #9C27B0; } .lf { background-color: #3F51B5; } .rf { background-color: #00BCD4; }
.ruler-area { padding: 10px 0; margin-left: 15px; box-sizing: border-box;}
.height-ruler-container { position: relative; width: 60px; height: 100%; }
.ruler-line { position: absolute; bottom: 0; left: 20px; width: 2px; background: repeating-linear-gradient(to top, #94a3b8, #94a3b8 6px, transparent 6px, transparent 12px); }
.ruler-line::after { content: ''; position: absolute; top: 0; left: -15px; width: 32px; height: 2px; background: #ef4444; box-shadow: 0 0 8px rgba(239, 68, 68, 0.6); }
.ruler-label { position: absolute; top: -28px; left: 50%; transform: translateX(-50%); background: #0f172a; color: #f8fafc; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold; white-space: nowrap; box-shadow: 0 4px 6px rgba(0,0,0,0.2); }
.x-axis-area { width: 420px; padding: 0 10px; box-sizing: border-box; margin-top: 10px;}
.x-axis-inner { position: relative; width: 100%; height: 20px; }
.x-label { position: absolute; transform: translateX(-50%); font-weight: bold; color: #94a3b8; font-size: 0.85em; }
</style>