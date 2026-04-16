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
          <div class="config-group">
             <h3 class="group-title">🛠️ 岩点库管理</h3>
             <div class="upload-section">
                <div class="field">
                  <label>岩点类型</label>
                  <select v-model="uploadInfo.hold_type">
                    <option v-for="type in holdTypes" :key="type" :value="type">{{ type }}</option>
                  </select>
                </div>
                <div class="field">
                  <label>变体</label>
                  <select v-model="uploadInfo.variant">
                    <option value="default">默认</option>
                    <option value="01">01</option>
                    <option value="02">02</option>
                    <option value="03">03</option>
                    <option value="04">04</option>
                  </select>
                </div>
                <input type="file" @change="onFileChange" accept="image/*" />
                <button @click="uploadImage" :disabled="!uploadInfo.file">上传</button>
             </div>
          </div>

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
                    <option value="01">经典型 01 {{ holdImageMap[type] && holdImageMap[type]['01'] ? ' (已录入)' : ' (暂未录入)' }}</option>
                    <option value="02">变体型 02 {{ holdImageMap[type] && holdImageMap[type]['02'] ? ' (已录入)' : ' (暂未录入)' }}</option>
                    <option value="03">变体型 03 {{ holdImageMap[type] && holdImageMap[type]['03'] ? ' (已录入)' : ' (暂未录入)' }}</option>
                    <option value="04">变体型 04 {{ holdImageMap[type] && holdImageMap[type]['04'] ? ' (已录入)' : ' (暂未录入)' }}</option>
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
                   :class="{ 
                     'is-active': idx === currentIndex, 
                     'is-top': m.is_top,
                     'is-start': m.step === 0 
                   }"
                   @click="currentIndex = idx">
                <div class="step-indicator">
                   <div class="step-line"></div>
                   <div class="step-number">{{ m.step }}</div>
                </div>
                <div class="step-content">
                  <div class="step-meta">
                    <span class="limb-tag" :class="m.limb.toLowerCase()">{{ getLimbName(m.limb) }}</span>
                    <span class="hold-id">{{ m.hold_id }}</span>
                  </div>
                  <p class="intent" v-if="m.intent">{{ m.intent }}</p>
                  <p class="intent" v-else-if="m.step === 0">上墙起步</p>
                </div>
                <div v-if="m.is_top" class="top-medal">🏆</div>
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
            <input type="range" v-model.number="currentIndex" min="0" :max="maxIndex" class="modern-slider" />
          </div>
        </div>

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

// --- 🌟 岩点图片映射 ---
const holdImageMap = reactive({})

// 从后端加载映射
const API_BASE_URL = 'http://127.0.0.1:8000'

const fetchHoldMapping = async () => {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/holds/mapping`)
    Object.assign(holdImageMap, response.data)
  } catch (error) {
    console.error("无法加载岩点图片映射:", error)
  }
}
fetchHoldMapping() // 初始化时加载

const uploadInfo = reactive({
  hold_type: 'Jug',
  variant: 'default',
  file: null
})

const onFileChange = (e) => {
  uploadInfo.file = e.target.files[0]
}

const uploadImage = async () => {
  if (!uploadInfo.file) return

  const formData = new FormData()
  formData.append('hold_type', uploadInfo.hold_type)
  formData.append('variant', uploadInfo.variant)
  formData.append('file', uploadInfo.file)

  try {
    await axios.post(`${API_BASE_URL}/api/holds/upload`, formData)
    // Refresh mapping
    await fetchHoldMapping()
    alert('上传成功!')
  } catch (error) {
    console.error('上传失败:', error)
    alert('上传失败!')
  }
}

const getHoldImage = (hold) => {
  const typeMap = holdImageMap[hold.hold_type]
  if (!typeMap) return null
  const imageUrl = typeMap[hold.variant] || typeMap['default']
  return imageUrl ? `${API_BASE_URL}${imageUrl}` : null
}

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
      climber_height_cm: profile.value.height,
      climber_span_cm: profile.value.arm_span,
      target_difficulty: profile.value.target_difficulty,
      recipe: backendRecipePayload
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

// 计算骨架连线
const skeletonLines = computed(() => {
  const limbs = currentLimbs.value
  if (!limbs.LH && !limbs.RH && !limbs.LF && !limbs.RF) return {}

  const getPos = (id) => {
    const coords = getCoord(id)
    return {
      x: parseFloat(coords.left),
      y: 100 - parseFloat(coords.bottom)
    }
  }

  const res = {}
  const p = {
    lh: limbs.LH ? getPos(limbs.LH.id) : null,
    rh: limbs.RH ? getPos(limbs.RH.id) : null,
    lf: limbs.LF ? getPos(limbs.LF.id) : null,
    rf: limbs.RF ? getPos(limbs.RF.id) : null
  }

  // 虚拟重心 (Center of Mass) - 简化为四肢中心
  const activeLimbs = [p.lh, p.rh, p.lf, p.rf].filter(i => i)
  if (activeLimbs.length < 2) return {}
  
  const com = {
    x: activeLimbs.reduce((acc, curr) => acc + curr.x, 0) / activeLimbs.length,
    y: activeLimbs.reduce((acc, curr) => acc + curr.y, 0) / activeLimbs.length
  }

  if (p.lh) res.lh = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.lh.x}%`, y2: `${p.lh.y}%` }
  if (p.rh) res.rh = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.rh.x}%`, y2: `${p.rh.y}%` }
  if (p.lf) res.lf = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.lf.x}%`, y2: `${p.lf.y}%` }
  if (p.rf) res.rf = { x1: `${com.x}%`, y1: `${com.y}%`, x2: `${p.rf.x}%`, y2: `${p.rf.y}%` }

  // 躯干：连接手重心和脚重心
  const hands = [p.lh, p.rh].filter(i => i)
  const feet = [p.lf, p.rf].filter(i => i)
  if (hands.length && feet.length) {
    const handCom = {
      x: hands.reduce((acc, curr) => acc + curr.x, 0) / hands.length,
      y: hands.reduce((acc, curr) => acc + curr.y, 0) / hands.length
    }
    const footCom = {
      x: feet.reduce((acc, curr) => acc + curr.x, 0) / feet.length,
      y: feet.reduce((acc, curr) => acc + curr.y, 0) / feet.length
    }
    res.body = { x1: `${handCom.x}%`, y1: `${handCom.y}%`, x2: `${footCom.x}%`, y2: `${footCom.y}%` }
  }

  return res
})

const getCoord = (id) => {
  if (!id) return { left: '50%', bottom: '50%' }
  const xIdx = id.charCodeAt(0) - 65
  const yIdx = parseInt(id.substring(1)) - 1
  return { left: `${8 + (xIdx / 10) * 84}%`, bottom: `${8 + (yIdx / 17) * 84}%` }
}
const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981')
const getLimbName = (limb) => ({ LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' }[limb] || limb)
const getLimbEmoji = (limb) => ({ LH: '✋', RH: '✋', LF: '🦶', RF: '🦶' }[limb] || limb)
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

.config-group { 
  background: rgba(15, 23, 42, 0.6); padding: 18px; border-radius: 12px; margin-bottom: 24px; 
  border: 1px solid rgba(51, 65, 85, 0.4);
}
.group-title { 
  font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; color: #94a3b8; 
  margin-bottom: 16px; border-bottom: 2px solid #3b82f6; display: inline-block; padding-bottom: 4px;
}

.input-row { display: flex; gap: 12px; width: 100%; box-sizing: border-box; }
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
  width: 100%; padding: 14px; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); 
  color: white; border: none; border-radius: 10px;
  font-weight: 800; font-size: 1rem; cursor: pointer; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
  margin-top: 10px; box-shadow: 0 4px 14px rgba(59, 130, 246, 0.4);
  text-transform: uppercase; letter-spacing: 1px;
}
.generate-btn:hover:not(:disabled) { 
  transform: translateY(-2px); 
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.6);
  filter: brightness(1.1);
}
.generate-btn:active:not(:disabled) { transform: translateY(0); }
.generate-btn:disabled { background: #475569; cursor: not-allowed; opacity: 0.6; box-shadow: none; }

.upload-section { display: flex; flex-direction: column; gap: 10px; }
.upload-section input[type="file"] { font-size: 0.8rem; }

/* 时间轴样式 */
.timeline-section { margin-top: 30px; }
.step-scroll-area { 
  display: flex; flex-direction: column; gap: 10px; margin-top: 15px; 
  max-height: 450px; overflow-y: auto; padding-right: 10px;
  scrollbar-width: thin; scrollbar-color: #334155 transparent;
}
.step-scroll-area::-webkit-scrollbar { width: 6px; }
.step-scroll-area::-webkit-scrollbar-track { background: transparent; }
.step-scroll-area::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }

.step-item { 
  display: flex; gap: 12px; background: #0f172a; padding: 14px; border-radius: 10px; 
  cursor: pointer; transition: all 0.2s ease; position: relative;
  border: 1px solid rgba(51, 65, 85, 0.5); opacity: 0.8;
}
.step-item:hover { background: #334155; transform: translateX(5px); }
.step-item.is-active { opacity: 1; border-color: #3b82f6; background: #334155; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2); }
.step-item.is-start { border-left: 4px solid #10b981; }
.step-item.is-top { border-left: 4px solid #ef4444; }

.step-indicator { display: flex; flex-direction: column; align-items: center; width: 20px; }
.step-line { width: 2px; height: 100%; background: #334155; position: absolute; left: 21px; top: 0; z-index: 1; }
.step-number { 
  width: 20px; height: 20px; background: #0f172a; border: 2px solid #475569; 
  border-radius: 50%; display: flex; align-items: center; justify-content: center; 
  font-size: 10px; font-weight: bold; color: #94a3b8; z-index: 2; position: relative;
}
.is-active .step-number { border-color: #3b82f6; color: #3b82f6; background: #1e293b; }

.step-content { flex: 1; }
.step-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.limb-tag { 
  padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; font-weight: 800; color: white;
  text-transform: uppercase;
}
.lh { background: #E91E63; }
.rh { background: #9C27B0; }
.lf { background: #3F51B5; }
.rf { background: #00BCD4; }

.hold-id { font-size: 0.85rem; font-weight: 800; color: #f1f5f9; }
.intent { font-size: 0.75rem; color: #94a3b8; margin: 0; line-height: 1.4; }
.top-medal { font-size: 1.2rem; }

/* 舞台样式 */
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

@keyframes rotate { 100% { transform: rotate(360deg); } }

/* 🌟 核心修复：独立、鲜艳的四肢游标设计，拒绝黏连 */
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
