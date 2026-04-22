<template>
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
          <p>AI Agent Creator Engine v6.0</p>
        </div>
      </header>

      <section class="config-group">
        <h3 class="group-title">👤 攀爬者孪生体</h3>
        <div class="input-row">
          <div class="field">
            <label>身高 (cm)</label>
            <input type="number" :value="profile.height" @input="$emit('update:profile', { ...profile, height: $event.target.value })" />
          </div>
          <div class="field">
            <label>臂展 (cm)</label>
            <input type="number" :value="profile.arm_span" @input="$emit('update:profile', { ...profile, arm_span: $event.target.value })" />
          </div>
        </div>
        <div class="field">
          <label>空间拓扑难度 (Target Difficulty)</label>
          <select :value="profile.target_difficulty" @change="$emit('update:profile', { ...profile, target_difficulty: $event.target.value })">
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
              <input type="number" :value="recipeConfig[type].count" @input="updateRecipeCount(type, $event.target.value)" min="0" max="20" />
            </div>
            
            <div class="shape-variant-select" v-if="recipeConfig[type].count > 0">
              <select :value="recipeConfig[type].variant" @change="updateRecipeVariant(type, $event.target.value)">
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
        <button @click="$emit('generate-route')" :disabled="loading" class="generate-btn">
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
               @click="$emit('update:currentIndex', idx)">
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

  <button class="sidebar-toggle-btn" @click="$emit('toggle-sidebar')" :class="{ 'is-closed': !isSidebarOpen }">
    {{ isSidebarOpen ? '◀' : '▶' }}
  </button>
</template>

<script setup>
import { ref, reactive } from 'vue';
import axios from 'axios';

const props = defineProps({
  isSidebarOpen: Boolean,
  profile: Object,
  recipeConfig: Object,
  holdImageMap: Object,
  loading: Boolean,
  error: String,
  routeSteps: Array,
  currentIndex: Number,
});

const emit = defineEmits([
  'update:profile',
  'update:recipeConfig',
  'update:currentIndex',
  'generate-route',
  'toggle-sidebar',
  'fetch-mapping'
]);

const holdTypes = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot'];
const API_BASE_URL = 'http://127.0.0.1:8000';

const uploadInfo = reactive({
  hold_type: 'Jug',
  variant: 'default',
  file: null
});

const onFileChange = (e) => {
  uploadInfo.file = e.target.files[0];
};

const uploadImage = async () => {
  if (!uploadInfo.file) return;

  const formData = new FormData();
  formData.append('hold_type', uploadInfo.hold_type);
  formData.append('variant', uploadInfo.variant);
  formData.append('file', uploadInfo.file);

  try {
    await axios.post(`${API_BASE_URL}/api/holds/upload`, formData);
    emit('fetch-mapping');
    alert('上传成功!');
  } catch (error) {
    console.error('上传失败:', error);
    alert('上传失败!');
  }
};

const updateRecipeCount = (type, count) => {
  const newConfig = { ...props.recipeConfig };
  newConfig[type].count = parseInt(count, 10);
  emit('update:recipeConfig', newConfig);
};

const updateRecipeVariant = (type, variant) => {
  const newConfig = { ...props.recipeConfig };
  newConfig[type].variant = variant;
  emit('update:recipeConfig', newConfig);
};

const getShapeColor = (type) => ({ Jug: '#10b981', Crimp: '#ef4444', Sloper: '#f59e0b', Pinch: '#8b5cf6', Pocket: '#3b82f6', Foot: '#94a3b8' }[type] || '#10b981');
const getLimbName = (limb) => ({ LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' }[limb] || limb);

</script>

<style scoped>
/* Styles from App.vue */
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
</style>