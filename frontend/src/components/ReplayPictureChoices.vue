<template>
  <fieldset class="picture-choices" :aria-label="includeData ? '导出内容' : '画面内容'">
    <legend>{{ includeData ? '导出内容' : '画面' }}</legend>
    <label v-for="item in items" :key="item.key">
      <input type="checkbox" :checked="modelValue[item.key]" :disabled="disabled || blocked(item.key)"
        @change="change(item.key, $event.target.checked)" />{{ item.label }}
    </label>
    <label v-if="includeData"><input type="checkbox" :checked="modelValue.include_data" :disabled="disabled"
      @change="change('include_data', $event.target.checked)" />资料</label>
    <p v-if="backgroundMessage" class="background-message" role="status">{{ backgroundMessage }}</p>
  </fieldset>
</template>
<script setup>
const props=defineProps({modelValue:{type:Object,required:true},includeData:Boolean,backgroundReady:Boolean,backgroundMessage:String,disabled:Boolean})
const emit=defineEmits(['update:modelValue'])
const items=[{key:'show_skeleton',label:'骨架'},{key:'show_human',label:'真人'},{key:'show_diagram',label:'动作示意图'}]
function blocked(key){
  const value=props.modelValue
  if(key==='show_skeleton' && !value.show_skeleton && !value.show_human && !props.backgroundReady)return true
  if(key==='show_human' && value.show_human && value.show_skeleton && !props.backgroundReady)return true
  return !props.includeData && value[key] && items.filter(item=>value[item.key]).length===1
}
function change(key,value){
  if(blocked(key)||props.disabled)return
  emit('update:modelValue',{...props.modelValue,[key]:value})
}
</script>
<style scoped>
.picture-choices{border:0;margin:0;padding:8px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:0 20px;min-width:0}
legend{float:left;line-height:44px;margin-right:20px;padding:0;font-size:13px;color:var(--ui-ink-muted,#606060)}
label{display:flex;align-items:center;gap:8px;min-height:44px;font-size:14px;cursor:pointer}
input{accent-color:var(--ui-focus,#806000);width:16px;height:16px;margin:0}
input:focus-visible{outline:2px solid var(--ui-focus,#806000);outline-offset:3px}
label:has(input:disabled){color:var(--ui-ink-muted,#606060);cursor:default}
.background-message{flex-basis:100%;margin:0 0 4px;font-size:13px;line-height:1.6;color:var(--ui-ink-muted,#606060)}
</style>
