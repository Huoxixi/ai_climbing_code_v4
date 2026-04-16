<template>
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
           @click="updateIndex(idx)">
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
</template>

<script setup>
const props = defineProps({
  routeSteps: {
    type: Array,
    default: () => []
  },
  currentIndex: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['update:currentIndex'])

const updateIndex = (index) => {
  emit('update:currentIndex', index)
}

const getLimbName = (limb) => ({ LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' }[limb] || limb)
</script>

<style scoped>
.timeline-section {
  background: #0f172a;
  padding: 15px;
  border-radius: 10px;
  margin-top: 20px;
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
.step-scroll-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 15px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 10px;
}
.step-item {
  display: flex;
  gap: 15px;
  background: #1e293b;
  padding: 12px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
  border: 1px solid transparent;
  opacity: 0.7;
}
.step-item:hover {
  background: #334155;
  transform: translateX(5px);
}
.step-item.is-active {
  opacity: 1;
  border-color: #3b82f6;
  background: #334155;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}
.step-item.is-start {
  border-left: 4px solid #10b981;
}
.step-item.is-top {
  border-left: 4px solid #ef4444;
}
.step-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
}
.step-line {
  width: 2px;
  height: 100%;
  background: #334155;
  position: absolute;
  left: 21px;
  top: 0;
  z-index: 1;
}
.step-number {
  width: 20px;
  height: 20px;
  background: #0f172a;
  border: 2px solid #475569;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: bold;
  color: #94a3b8;
  z-index: 2;
  position: relative;
}
.is-active .step-number {
  border-color: #3b82f6;
  color: #3b82f6;
  background: #1e293b;
}
.step-content {
  flex: 1;
}
.step-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.limb-tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 800;
  color: white;
  text-transform: uppercase;
}
.lh {
  background: #E91E63;
}
.rh {
  background: #9C27B0;
}
.lf {
  background: #3F51B5;
}
.rf {
  background: #00BCD4;
}
.hold-id {
  font-size: 0.85rem;
  font-weight: 800;
  color: #f1f5f9;
}
.intent {
  font-size: 0.75rem;
  color: #94a3b8;
  margin: 0;
  line-height: 1.4;
}
.top-medal {
  font-size: 1.2rem;
}
</style>
