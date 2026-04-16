<template>
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
    </div>
  </aside>
  <button class="sidebar-toggle-btn" @click="toggleSidebar" :class="{ 'is-closed': !isSidebarOpen }">
    {{ isSidebarOpen ? '◀' : '▶' }}
  </button>
</template>

<script setup>
import { ref, reactive } from 'vue'

const isSidebarOpen = ref(true)

const profile = ref({ height: 175, arm_span: 180, target_difficulty: 'V1' })
const holdTypes = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot']

const recipeConfig = reactive({
  Jug: { count: 4, variant: 'random' },
  Crimp: { count: 2, variant: 'random' },
  Sloper: { count: 1, variant: 'random' },
  Pinch: { count: 1, variant: 'random' },
  Pocket: { count: 0, variant: 'random' },
  Foot: { count: 4, variant: 'random' }
})

const loading = ref(false)
const error = ref('')

const emit = defineEmits(['generate-route'])

const generateRoute = () => {
  emit('generate-route', {
    profile: profile.value,
    recipe: recipeConfig
  })
}

const toggleSidebar = () => {
  isSidebarOpen.value = !isSidebarOpen.value
}

const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981')

</script>

<style scoped>
.sidebar {
  width: 350px;
  background: #1e293b;
  border-right: 1px solid #334155;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow-y: auto;
  overflow-x: hidden;
  position: relative;
  flex-shrink: 0;
}
.sidebar.is-collapsed {
  width: 0;
  border-right: none;
}
.sidebar-content {
  width: 350px;
  padding: 20px;
  box-sizing: border-box;
}
.sidebar-toggle-btn {
  position: absolute;
  left: 350px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 50;
  width: 24px;
  height: 48px;
  background: #1e293b;
  border: 1px solid #334155;
  border-left: none;
  border-radius: 0 8px 8px 0;
  color: #94a3b8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}
.sidebar-toggle-btn:hover {
  background: #334155;
  color: white;
}
.sidebar-toggle-btn.is-closed {
  left: 0;
}
.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 30px;
}
.logo {
  font-size: 2rem;
}
.titles h1 {
  font-size: 1rem;
  margin: 0;
  color: #f1f5f9;
}
.titles p {
  font-size: 0.7rem;
  color: #94a3b8;
  margin: 0;
}
.config-group {
  background: #0f172a;
  padding: 15px;
  border-radius: 10px;
  margin-bottom: 20px;
}
.group-title {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #64748b;
  margin-bottom: 12px;
  border-bottom: 1px solid #334155;
  padding-bottom: 5px;
}
.input-row {
  display: flex;
  gap: 10px;
  width: 100%;
  box-sizing: border-box;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 10px;
  flex: 1;
  min-width: 0;
}
.field label {
  font-size: 0.75rem;
  font-weight: bold;
  color: #94a3b8;
}
.field input,
.field select {
  width: 100%;
  box-sizing: border-box;
  background: #1e293b;
  border: 1px solid #334155;
  color: white;
  padding: 8px;
  border-radius: 6px;
  outline: none;
  font-size: 0.85rem;
}
.recipe-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.recipe-item-container {
  background: #1e293b;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid #334155;
}
.recipe-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.hold-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  font-weight: bold;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.recipe-row input {
  width: 45px;
  background: #0f172a;
  border: 1px solid #334155;
  color: white;
  text-align: center;
  border-radius: 4px;
  padding: 4px;
}
.shape-variant-select {
  margin-top: 8px;
  border-top: 1px dashed #334155;
  padding-top: 8px;
}
.shape-variant-select select {
  width: 100%;
  background: #0f172a;
  border: 1px solid #334155;
  color: #94a3b8;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  outline: none;
}
.generate-btn {
  width: 100%;
  padding: 12px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
  transition: 0.3s;
  margin-top: 10px;
}
.generate-btn:hover:not(:disabled) {
  background: #2563eb;
  transform: translateY(-2px);
}
.generate-btn:disabled {
  background: #475569;
  cursor: not-allowed;
  opacity: 0.7;
}
</style>
