<template>
  <section class="section-block" aria-labelledby="board-template-heading">
    <div class="section-heading">
      <div>
        <h3 id="board-template-heading">岩板规格</h3>
      </div>
      <el-button plain @click="expanded = !expanded">{{ expanded ? '收起' : '选择其他规格' }}</el-button>
    </div>
    <dl v-if="selectedTemplate" class="template-spec-list">
      <div><dt>规格</dt><dd>{{ selectedTemplate.label }}</dd></div>
      <div><dt>角度</dt><dd>{{ selectedTemplate.angleLabel }}</dd></div>
      <div><dt>网格</dt><dd>{{ selectedTemplate.spacingLabel }}</dd></div>
      <div><dt>尺寸</dt><dd>{{ selectedTemplate.physicalLabel }}</dd></div>
      <div><dt>模式</dt><dd>{{ selectedTemplate.ai_supported ? 'AI 与手工定线' : '手工定线' }}</dd></div>
    </dl>
    <div v-if="expanded" class="template-grid" role="radiogroup" aria-label="岩板规格">
      <button
        v-for="template in templates"
        :key="template.id"
        type="button"
        class="template-card"
        :class="{ active: modelValue === template.id }"
        role="radio"
        :aria-checked="modelValue === template.id"
        @click="$emit('update:modelValue', template.id)"
      >
        <span>{{ template.cellLabel }}</span>
        <strong>{{ template.label }}</strong>
        <small>{{ template.physicalLabel || template.angleLabel }}</small>
        <small>{{ template.ai_supported ? '支持 AI 组合与审核' : '仅支持手工定线' }}</small>
      </button>
    </div>
    <el-button v-if="expanded" class="template-confirm" type="primary" :icon="DocumentChecked" @click="$emit('confirm', modelValue)">使用此规格新建岩板</el-button>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { DocumentChecked } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: String, required: true },
  templates: { type: Array, default: () => [] },
})

defineEmits(['update:modelValue', 'confirm'])

const selectedTemplate = computed(() => (
  props.templates.find((template) => template.id === props.modelValue) || props.templates[0] || null
))
const expanded = ref(false)
</script>
