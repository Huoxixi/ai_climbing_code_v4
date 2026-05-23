<template>
  <aside class="inspector">
    <section class="panel">
      <div class="panel-heading">
        <h3>当前岩板</h3>
        <span>{{ board.board_spec?.cellLabel }}</span>
      </div>
      <el-input v-model="board.route_name" @input="$emit('dirty')" />
      <el-input v-model="board.setter_commentary" type="textarea" :rows="3" @input="$emit('dirty')" />
      <div class="compact-stats">
        <span>{{ board.placed_holds?.length || 0 }} 岩点</span>
        <span>{{ board.beta_sequence?.length || 0 }} Beta</span>
      </div>
    </section>

    <section class="panel">
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
      <div v-else class="empty-text">在画布上选择一个岩点后可编辑属性。</div>
    </section>

    <section class="panel">
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
defineProps({
  board: { type: Object, required: true },
  selectedHold: { type: Object, default: null },
  routeSteps: { type: Array, default: () => [] },
  betaForm: { type: Object, required: true },
  holdTypes: { type: Array, required: true },
})

const emit = defineEmits(['update-hold', 'delete-hold', 'add-beta', 'delete-beta', 'dirty'])

function update(patch) {
  emit('update-hold', patch)
}

function limbName(limb) {
  return { LH: '左手', RH: '右手', LF: '左脚', RF: '右脚' }[limb] || limb
}
</script>
