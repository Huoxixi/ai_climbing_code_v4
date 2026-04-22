<template>
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
        <span class="step-counter">动作序列 {{ (routeSteps?.length || 0) > 0 ? currentIndex + 1 : 0 }} / {{ routeSteps?.length || 0 }}</span>
        <span class="difficulty-tag">{{ profile?.target_difficulty }}</span>
      </div>
      <input type="range" :value="currentIndex" @input="$emit('update:currentIndex', parseInt($event.target.value))" min="0" :max="maxIndex" class="modern-slider" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  routeData: Object,
  routeSteps: {
    type: Array,
    default: () => []
  },
  profile: {
    type: Object,
    default: () => ({})
  },
  currentIndex: {
    type: Number,
    default: 0
  },
});

defineEmits(['update:currentIndex']);

const maxIndex = computed(() => Math.max(0, (props.routeSteps?.length || 0) - 1));
</script>

<style scoped>
/* Styles from App.vue */
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
</style>