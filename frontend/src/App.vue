<template>
  <div class="symbiosis-app">
    <div v-if="loading" class="loading-overlay">
      <div class="loading-content">
        <div class="progress-circle">
          <svg viewBox="0 0 100 100">
            <circle class="bg" cx="50" cy="50" r="45"></circle>
            <circle class="pulse" cx="50" cy="50" r="45"></circle>
          </svg>
          <div class="agent-avatar">AI</div>
        </div>
        <div class="reflection-log">
          <p class="log-line animate-pulse">{{ currentReflectionMsg }}</p>
        </div>
      </div>
    </div>

    <div class="main-layout">
      <aside class="sidebar" :class="{ 'is-collapsed': !isSidebarOpen }">
        <div class="sidebar-content">
          <header class="brand">
            <div class="logo">🧗‍♂️</div>
            <div class="titles">
              <h1>智行通途 / ZXT</h1>
              <p>AI Agent Creator Engine v5.0</p>
            </div>
          </header>

          <section class="config-group">
            <h3 class="group-title">👤 攀爬者孪生体</h3>
            <div class="input-row">
              <div class="field">
                <label>身高 (cm)</label>
                <input type="number" v-model="profile.height" />
              </div>
              <div class="field">
                <label>臂展 (cm)</label>
                <input type="number" v-model="profile.arm_span" />
              </div>
            </div>
            <div class="field">
              <label>空间拓扑难度 (Target Difficulty)</label>
              <select v-model="profile.target_difficulty">
                <option value="V0">V0 - 新手稳定型</option>
                <option value="V1">V1 - 基础入门型</option>
                <option value="V2">V2 - 进阶拉伸型</option>
                <option value="V3">V3 - 极限爆发型</option>
              </select>
            </div>
          </section>

          <section class="config-group">
            <h3 class="group-title">🧪 物质配方投影</h3>
            <div class="recipe-list">
              <div v-for="type in holdTypes" :key="type" class="recipe-item-container">
                <div class="recipe-row">
                  <div class="hold-indicator">
                    <span class="dot" :style="{ backgroundColor: getShapeColor(type) }"></span>
                    <span class="name">{{ type }}</span>
                  </div>
                  <input type="number" v-model.number="recipeConfig[type].count" min="0" max="20" />
                </div>
                
                <div class="shape-variant-select" v-if="recipeConfig[type].count > 0">
                  <select v-model="recipeConfig[type].variant">
                    <option value="random">随机形状 (AI 推断)</option>
                    <option value="01">经典型 01</option>
                    <option value="02">变体型 02</option>
                    <option value="03">变体型 03</option>
                    <option value="04">变体型 04</option>
                  </select>
                </div>
              </div>
            </div>
          </section>

          <footer class="actions">
            <button @click="generateRoute" :disabled="loading" class="generate-btn">
              🚀 触发造物意图
            </button>
            <div v-if="error" class="error-toast">{{ error }}</div>
          </footer>

          <section v-if="routeSteps.length" class="timeline-section">
            <h3 class="group-title">📜 攀爬动作序列 (Beta)</h3>
            <div class="step-scroll-area">
              <div v-for="(m, idx) in routeSteps" :key="idx"
                   class="step-item"
                   :class="{ 'is-active': idx === currentIndex, 'is-top': m.is_top }"
                   @click="currentIndex = idx">
                <div class="step-meta">
                  <span class="badge" :class="m.limb.toLowerCase()">{{ m.limb }}</span>
                  <span class="id">➔ {{ m.hold_id }}</span>
                </div>
                <p class="intent">{{ m.intent || '上墙起步' }}</p>
              </div>
            </div>
          </section>
        </div>
      </aside>

      <button class="sidebar-toggle-btn" @click="isSidebarOpen = !isSidebarOpen" :class="{ 'is-closed': !isSidebarOpen }">
        {{ isSidebarOpen ? '◀' : '▶' }}
      </button>

      <main class="stage">
        <div class="stage-header" v-if="routeData">
          <h2>{{ routeData.route_name }}</h2>
          <div class="controls">
            <span>动作: {{ routeSteps.length > 0 ? currentIndex + 1 : 0 }} / {{ routeSteps.length }}</span>
            <input type="range" v-model.number="currentIndex" min="0" :max="maxIndex" />
          </div>
        </div>

        <div class="wall-display">
          <div class="wall-frame">
            <div class="grid-backdrop">
              <template v-for="y in 18" :key="'y-'+y">
                <div v-for="(x, xi) in 'ABCDEFGHIJK'.split('')" :key="x+y" 
                     class="hole" :style="getCoord(x+y)"></div>
              </template>
            </div>

            <div v-for="hold in placedHolds" :key="hold.id"
                 class="hold-entity"
                 :class="{ 'start-glow': isStart(hold.id), 'top-glow': isTop(hold.id) }"
                 :style="getCoord(hold.id)">
              <div class="hold-svg" :style="{ color: getShapeColor(hold.hold_type), transform: `rotate(${hold.rotation}deg)` }">
                <div class="geometric-shape" :class="hold.hold_type.toLowerCase()"></div>
              </div>
            </div>

            <div v-for="(pos, limb) in currentLimbs" :key="limb"
                 class="limb-cursor" :class="limb.toLowerCase()"
                 :style="getCoord(pos.id)">
              {{ limb }}
            </div>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive } from 'vue'
import axios from 'axios'

// --- 基础状态 ---
const isSidebarOpen = ref(true) // 控制侧边栏显隐
const profile = ref({ height: 175, arm_span: 180, target_difficulty: 'V1' })
const holdTypes = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot']

const recipeConfig = reactive({
  Jug: { count: 4, variant: 'random' },    // 4个把手：2起步+1中继+1完攀
  Crimp: { count: 2, variant: 'random' },  // 2个抠口：中段难点
  Sloper: { count: 1, variant: 'random' }, // 1个斜面：打破发力惯性
  Pinch: { count: 1, variant: 'random' },  // 1个捏点：增加姿态张力
  Pocket: { count: 0, variant: 'random' }, // 指洞容易受伤，默认关闭
  Foot: { count: 4, variant: 'random' }    // 4个脚点：配合手脚复用足够了
})

const loading = ref(false)
const error = ref('')
const routeData = ref(null)

// 🌟 核心修复：用 currentIndex 取代 currentStep，强制按数组绝对索引逐个播放！
const currentIndex = ref(0)
const currentReflectionMsg = ref('')

const reflectionMessages = [
  "正在初始化物理 Agent...",
  "分析 11x18 空间拓扑结构...",
  "尝试生成第 1 版岩点布局...",
  "物理裁判正在核验人体极限...",
  "检测到跨度风险，正在自我重构...",
  "优化 Beta 动作连贯性...",
  "最终渲染定线方案..."
]

let autoPlayTimer = null // 动画播放器

const generateRoute = async () => {
  loading.value = true; error.value = ''; routeData.value = null; currentIndex.value = 0
  if (autoPlayTimer) clearInterval(autoPlayTimer) // 清除上一次的动画
  
  let msgIdx = 0
  const msgTimer = setInterval(() => {
    currentReflectionMsg.value = reflectionMessages[msgIdx % reflectionMessages.length]
    msgIdx++
  }, 1200)

  // 整理传给后端的 Payload：为了避免后端 Pydantic 报错，目前仅提取数量
  const backendRecipePayload = {}
  Object.keys(recipeConfig).forEach(type => {
    if (recipeConfig[type].count > 0) {
      backendRecipePayload[type] = recipeConfig[type].count
    }
  })

  try {
    const response = await axios.post('http://127.0.0.1:8000/api/generate', {
      climber: { height_cm: profile.value.height, span_cm: profile.value.arm_span },
      target_difficulty: profile.value.target_difficulty,
      recipe: backendRecipePayload // 提取数量发送
    })
    routeData.value = response.data
    
    // 🌟 核心修复：严格按照动作数组的长度，一秒只走一步！
    let idx = 0
    autoPlayTimer = setInterval(() => {
      if (idx < maxIndex.value) { currentIndex.value = ++idx }
      else { clearInterval(autoPlayTimer) }
    }, 1000)
  } catch (err) {
    error.value = err.response?.data?.detail || err.message
  } finally {
    clearInterval(msgTimer)
    loading.value = false
  }
}

// --- 计算属性 ---
const placedHolds = computed(() => routeData.value?.placed_holds || [])
const routeSteps = computed(() => routeData.value?.beta_sequence || [])

// 🌟 核心修复：最大帧数就是数组长度减一
const maxIndex = computed(() => Math.max(0, routeSteps.value.length - 1))

const isStart = (id) => routeSteps.value.some(s => s.step === 0 && s.hold_id === id)
const isTop = (id) => routeSteps.value.some(s => s.is_top && s.hold_id === id)

// 🌟 核心修复：按数组切片 (slice) 截取肢体位置，彻底解决多步杂糅问题
const currentLimbs = computed(() => {
  const limbs = {}
  routeSteps.value.slice(0, currentIndex.value + 1).forEach(m => {
    limbs[m.limb] = { id: m.hold_id }
  })
  return limbs
})

const getCoord = (id) => {
  if (!id) return { left: '50%', bottom: '50%' }
  const xIdx = id.charCodeAt(0) - 65
  const yIdx = parseInt(id.substring(1)) - 1
  return { left: `${8 + (xIdx / 10) * 84}%`, bottom: `${8 + (yIdx / 17) * 84}%` }
}
const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981')
</script>

<style scoped>
.symbiosis-app {
  height: 100vh; width: 100vw; background: #0f172a; color: #f8fafc;
  font-family: 'Inter', -apple-system, sans-serif; overflow: hidden;
}

.main-layout { display: flex; height: 100%; position: relative; }

.sidebar {
  width: 350px; background: #1e293b; border-right: 1px solid #334155;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow-y: auto; overflow-x: hidden; position: relative;
  flex-shrink: 0;
}
.sidebar.is-collapsed { width: 0; border-right: none; }

.sidebar-content { width: 350px; padding: 20px; box-sizing: border-box; }

.sidebar-toggle-btn {
  position: absolute; left: 350px; top: 50%; transform: translateY(-50%);
  z-index: 50; width: 24px; height: 48px; background: #1e293b; border: 1px solid #334155;
  border-left: none; border-radius: 0 8px 8px 0; color: #94a3b8; cursor: pointer;
  display: flex; align-items: center; justify-content: center; transition: all 0.3s ease;
}
.sidebar-toggle-btn:hover { background: #334155; color: white; }
.sidebar-toggle-btn.is-closed { left: 0; }

.brand { display: flex; gap: 12px; align-items: center; margin-bottom: 30px; }
.logo { font-size: 2rem; }
.titles h1 { font-size: 1rem; margin: 0; color: #f1f5f9; }
.titles p { font-size: 0.7rem; color: #94a3b8; margin: 0; }

.config-group { background: #0f172a; padding: 15px; border-radius: 10px; margin-bottom: 20px; }
.group-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: #64748b; margin-bottom: 12px; border-bottom: 1px solid #334155; padding-bottom: 5px; }

.input-row { display: flex; gap: 10px; width: 100%; box-sizing: border-box; }
.field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 10px; flex: 1; min-width: 0; }
.field label { font-size: 0.75rem; font-weight: bold; color: #94a3b8; }
.field input, .field select { 
  width: 100%; box-sizing: border-box;
  background: #1e293b; border: 1px solid #334155; color: white; 
  padding: 8px; border-radius: 6px; outline: none; font-size: 0.85rem;
}

.recipe-list { display: flex; flex-direction: column; gap: 12px; }
.recipe-item-container { background: #1e293b; padding: 8px 10px; border-radius: 8px; border: 1px solid #334155; }
.recipe-row { display: flex; justify-content: space-between; align-items: center; }
.hold-indicator { display: flex; align-items: center; gap: 8px; font-size: 0.8rem; font-weight: bold;}
.dot { width: 8px; height: 8px; border-radius: 50%; }
.recipe-row input { width: 45px; background: #0f172a; border: 1px solid #334155; color: white; text-align: center; border-radius: 4px; padding: 4px; }

.shape-variant-select { margin-top: 8px; border-top: 1px dashed #334155; padding-top: 8px; }
.shape-variant-select select {
  width: 100%; background: #0f172a; border: 1px solid #334155; color: #94a3b8; 
  padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; outline: none;
}

.generate-btn {
  width: 100%; padding: 12px; background: #3b82f6; color: white; border: none; border-radius: 8px;
  font-weight: bold; cursor: pointer; transition: 0.3s; margin-top: 10px;
}
.generate-btn:hover:not(:disabled) { background: #2563eb; transform: translateY(-2px); }
.generate-btn:disabled { background: #475569; cursor: not-allowed; opacity: 0.7; }

/* 时间轴样式 */
.step-scroll-area { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; max-height: 250px; overflow-y: auto;}
.step-item { background: #1e293b; padding: 10px; border-radius: 6px; border-left: 3px solid #334155; cursor: pointer; transition: 0.2s; opacity: 0.6; }
.step-item.is-active { opacity: 1; border-left-color: #3b82f6; background: #334155; }
.step-item.is-top { border-left-color: #ef4444; }
.step-meta { display: flex; align-items: center; gap: 10px; font-weight: bold; font-size: 0.8rem; }
.badge { background: #475569; padding: 2px 6px; border-radius: 4px; }
.intent { font-size: 0.75rem; color: #94a3b8; margin: 5px 0 0 0; }

/* 舞台样式 */
.stage { flex: 1; display: flex; flex-direction: column; padding: 30px; position: relative; overflow: hidden; }
.stage-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.controls { display: flex; align-items: center; gap: 20px; background: #1e293b; padding: 10px 20px; border-radius: 30px; }
.controls input { cursor: pointer; }

.wall-display { flex: 1; display: flex; justify-content: center; align-items: center; }
.wall-frame {
  width: 450px; height: 650px; background: #020617; border-radius: 15px; position: relative;
  box-shadow: 0 0 50px rgba(0,0,0,0.5), inset 0 0 30px rgba(56,189,248,0.05); border: 10px solid #1e293b;
}

.hole { position: absolute; width: 4px; height: 4px; background: #334155; border-radius: 50%; transform: translate(-50%, 50%); }
.hold-entity { position: absolute; transform: translate(-50%, 50%); z-index: 10; }
.geometric-shape { width: 34px; height: 34px; background: currentColor; box-shadow: 0 0 10px currentColor; opacity: 0.8; }
.jug { border-radius: 40%; }
.crimp { height: 10px; border-radius: 2px; }
.sloper { border-radius: 50%; filter: blur(1px); }
.pinch { width: 10px; border-radius: 5px; }
.pocket { border-radius: 50%; background: transparent; border: 4px solid currentColor; }
.foot { width: 12px; height: 12px; clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%); }

.start-glow::after { content: ''; position: absolute; width: 50px; height: 50px; border: 2px dashed #10b981; border-radius: 50%; top:-8px; left:-8px; animation: rotate 10s linear infinite; }
.top-glow::after { content: ''; position: absolute; width: 50px; height: 50px; border: 2px dashed #ef4444; border-radius: 50%; top:-8px; left:-8px; animation: rotate 10s linear infinite; }
@keyframes rotate { 100% { transform: rotate(360deg); } }

/* 🌟 核心修复：独立、鲜艳的四肢游标设计，拒绝黏连 */
.limb-cursor {
  position: absolute; width: 22px; height: 22px; border-radius: 50%; z-index: 20;
  display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: bold;
  transform: translate(-50%, 50%); 
  box-shadow: 0 3px 8px rgba(0,0,0,0.6); border: 2px solid white; 
  transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.lh { background-color: #E91E63; color: white; } 
.rh { background-color: #9C27B0; color: white; } 
.lf { background-color: #3F51B5; color: white; } 
.rf { background-color: #00BCD4; color: white; }

.loading-overlay {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.85); z-index: 9999;
  display: flex; justify-content: center; align-items: center; backdrop-filter: blur(5px);
}
.loading-content { text-align: center; }
.progress-circle { position: relative; width: 100px; height: 100px; margin: 0 auto 20px auto; }
.progress-circle svg { transform: rotate(-90deg); width: 100px; height: 100px;}
.progress-circle circle { fill: none; stroke-width: 6; }
.progress-circle .bg { stroke: #334155; }
.progress-circle .pulse { stroke: #3b82f6; stroke-dasharray: 283; stroke-dashoffset: 200; animation: spin-circle 1.5s linear infinite; }
.agent-avatar { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 1.2rem; color: #3b82f6; }

@keyframes spin-circle { 0% { stroke-dashoffset: 283; } 100% { stroke-dashoffset: -283; } }
.reflection-log { color: #94a3b8; font-family: monospace; font-size: 0.9rem; }
.animate-pulse { animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>