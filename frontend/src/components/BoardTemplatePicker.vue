<template>
  <section class="board-template-picker">
    <div class="template-picker-header">
      <div>
        <span>Board Templates</span>
        <h3>选择底层岩板模板</h3>
      </div>
      <small>{{ templates.length }} 种规格可用</small>
    </div>

    <div class="template-card-grid">
      <button
        v-for="template in templates"
        :key="template.id"
        type="button"
        class="template-card"
        :class="{ active: activeTemplateId === template.id }"
        @click="$emit('select', template.id)"
      >
        <span class="template-name">{{ template.label }}</span>
        <strong>{{ template.cellLabel || `${template.columns} × ${template.rows}` }}</strong>
        <small>{{ template.angleLabel }} · {{ template.material }}</small>
        <em>{{ template.description }}</em>
      </button>
    </div>
  </section>
</template>

<script setup>
defineProps({
  templates: {
    type: Array,
    default: () => [],
  },
  activeTemplateId: {
    type: String,
    default: '',
  },
})

defineEmits(['select'])
</script>

<style scoped>
.board-template-picker {
  padding: 20px;
  border-radius: 24px;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.14);
  box-shadow: 0 20px 55px rgba(0, 0, 0, 0.22);
  margin: 18px 0;
}

.template-picker-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 14px;
}

.template-picker-header span {
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 1.6px;
  font-weight: 900;
  font-size: 0.68rem;
}

.template-picker-header h3 {
  margin: 4px 0 0;
  color: #f8fafc;
}

.template-picker-header small {
  color: #94a3b8;
  font-size: 0.74rem;
}

.template-card-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.template-card {
  min-height: 152px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 7px;
  padding: 15px;
  border-radius: 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.8);
  color: #cbd5e1;
  cursor: pointer;
  text-align: left;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.template-card:hover {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.62);
  background: rgba(30, 41, 59, 0.86);
}

.template-card.active {
  border-color: rgba(16, 185, 129, 0.74);
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(37, 99, 235, 0.18));
}

.template-name {
  color: #93c5fd;
  font-size: 0.78rem;
  font-weight: 900;
}

.template-card strong {
  color: #fff;
  font-size: 1.35rem;
}

.template-card small {
  color: #a7f3d0;
  font-size: 0.72rem;
  line-height: 1.45;
}

.template-card em {
  color: #94a3b8;
  font-size: 0.72rem;
  font-style: normal;
  line-height: 1.5;
}

@media (max-width: 1180px) {
  .template-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .template-card-grid {
    grid-template-columns: 1fr;
  }
}
</style>