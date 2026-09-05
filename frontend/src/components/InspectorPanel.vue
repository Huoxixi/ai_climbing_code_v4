<template>
  <aside class="inspector">
    <section v-if="activeSection === 'all' || activeSection === 'board'" class="panel">
      <div class="panel-heading">
        <h3>当前岩板</h3>
        <span>{{ board.board_spec?.cellLabel }}</span>
      </div>
      <label>线路名称</label>
      <el-input v-model="board.route_name" placeholder="输入岩板或线路名称" @input="$emit('dirty')" />
      <label>定线说明</label>
      <el-input v-model="board.setter_commentary" type="textarea" :rows="3" placeholder="记录定线目标、风格或注意事项" @input="$emit('dirty')" />
      <label>动作标签</label>
      <el-checkbox-group :model-value="selectedStyleTags" class="route-tag-editor" @change="updateTags">
        <el-checkbox v-for="tag in manualTagOptions" :key="tag.id" :value="tag.id">{{ tag.label }}</el-checkbox>
      </el-checkbox-group>
      <div class="compact-stats">
        <span>{{ board.placed_holds?.length || 0 }} 岩点</span>
        <span>{{ board.beta_sequence?.length || 0 }} Beta</span>
      </div>
    </section>

    <section v-if="activeSection === 'all' || activeSection === 'hold'" class="panel">
      <div class="panel-heading">
        <h3>选中岩点</h3>
        <span>{{ selectedHold?.id || '未选择' }}</span>
      </div>
      <template v-if="selectedHold">
        <label>类型</label>
        <el-select :model-value="selectedHold.hold_type" @change="update({ hold_type: $event, type: $event })">
          <el-option v-for="type in holdTypes" :key="type" :label="type" :value="type" />
        </el-select>
        <label>旋转</label>
        <el-slider :model-value="selectedHold.rotation || 0" :min="0" :max="359" @input="update({ rotation: $event })" />
        <label>缩放</label>
        <el-slider :model-value="selectedHold.scale || 1" :min="0.5" :max="2" :step="0.05" @input="update({ scale: $event })" />
        <el-checkbox :model-value="Boolean(selectedHold.is_start)" @change="update({ is_start: $event })">设为起点</el-checkbox>
        <el-button type="danger" plain @click="$emit('delete-hold')">删除岩点</el-button>
      </template>
      <div v-else class="empty-text">在画布上选择一个岩点后，可在这里编辑属性。</div>
    </section>

    <section v-if="activeSection === 'all' || activeSection === 'beta'" class="panel">
      <div class="panel-heading">
        <h3>Beta 序列</h3>
        <span>{{ routeSteps.length }}</span>
      </div>
      <div class="beta-form">
        <el-select v-model="betaForm.limb">
          <el-option label="左手" value="LH" />
          <el-option label="右手" value="RH" />
          <el-option label="左脚" value="LF" />
          <el-option label="右脚" value="RF" />
        </el-select>
        <el-select v-model="betaForm.hold_id" placeholder="目标岩点">
          <el-option v-for="hold in board.placed_holds" :key="hold.id" :label="hold.id" :value="hold.id" />
        </el-select>
        <el-checkbox v-model="betaForm.is_top">终点</el-checkbox>
        <el-button type="primary" @click="$emit('add-beta')">添加动作</el-button>
      </div>
      <div class="beta-list">
        <div v-for="(step, index) in routeSteps" :key="`${step.step}-${step.hold_id}-${index}`" class="beta-item">
          <span>{{ index + 1 }}</span>
          <strong>{{ limbName(step.limb) }}</strong>
          <em>{{ step.hold_id }}</em>
          <el-button text type="danger" @click="$emit('delete-beta', index)">删除</el-button>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { MANUAL_BOARD_TAG_IDS, ROUTE_TAG_LABELS } from '../constants/routeTags'

const emit = defineEmits(['update-hold', 'delete-hold', 'add-beta', 'delete-beta', 'dirty'])

const props = defineProps({
  board: { type: Object, required: true },
  selectedHold: { type: Object, default: null },
  routeSteps: { type: Array, default: () => [] },
  betaForm: { type: Object, required: true },
  holdTypes: { type: Array, required: true },
  activeSection: { type: String, default: 'all' },
})

const manualTagOptions = MANUAL_BOARD_TAG_IDS.map((id) => ({ id, label: ROUTE_TAG_LABELS[id] }))
const selectedStyleTags = computed(() => (props.board.tags || []).filter((tag) => MANUAL_BOARD_TAG_IDS.includes(tag)))

function update(patch) {
  emit('update-hold', patch)
}

function updateTags(selectedTags) {
  const retainedTags = (props.board.tags || []).filter((tag) => !MANUAL_BOARD_TAG_IDS.includes(tag))
  props.board.tags = [...new Set([...retainedTags, ...selectedTags])]
  emit('dirty')
}

function limbName(limb) {
  return { LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' }[limb] || limb
}
</script>
