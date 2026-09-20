<template>
  <section class="community-page">
    <div class="community-copy">
      <span class="community-state"><Lock />封闭准备中</span>
      <h1>抱石社区</h1>
      <p>社区只展示用户主动发布的公开副本，不会读取私人照片、草稿和攀爬备注。</p>
      <button type="button" @click="$emit('open-records')">先整理我的记录</button>
    </div>
    <aside aria-label="社区开放条件">
      <h2>开放前必须完成</h2>
      <ul>
        <li><Check />发布前预览公开内容</li>
        <li><Check />公开副本与私人记录隔离</li>
        <li><Check />下架、举报和审核可用</li>
      </ul>
    </aside>
  </section>
</template>

<script setup>
import { Check, Lock } from '@element-plus/icons-vue'
defineEmits(['open-records'])
</script>

<style scoped>
.community-page{box-sizing:border-box;width:min(1040px,calc(100% - 64px));min-height:calc(100dvh - 64px);margin:0 auto;padding:72px 0 100px;display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr);align-items:center;gap:72px;color:var(--ui-ink)}
.community-copy{max-width:620px}.community-state{width:fit-content;min-height:32px;padding:5px 9px;border-radius:var(--ui-radius-small);background:var(--ui-surface-subtle);color:var(--ui-ink-muted);display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:600}.community-state svg{width:15px}
.community-copy h1{margin:22px 0 0;font-size:38px;letter-spacing:-.02em}.community-copy p{max-width:54ch;margin:12px 0 0;color:var(--ui-ink-muted);font-size:16px;line-height:1.75}.community-copy button{min-height:46px;margin-top:28px;padding:0 20px;border:1px solid var(--ui-brand);border-radius:var(--ui-radius-control);background:var(--ui-brand);color:var(--ui-brand-ink);font:inherit;font-weight:700;cursor:pointer}.community-copy button:hover{background:var(--ui-brand-hover)}.community-copy button:focus-visible{outline:3px solid var(--ui-focus);outline-offset:2px}
.community-page aside{padding:26px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-card);background:var(--ui-surface)}.community-page aside h2{margin:0;font-size:18px}.community-page ul{margin:18px 0 0;padding:0;display:grid;gap:16px;list-style:none}.community-page li{display:grid;grid-template-columns:20px 1fr;align-items:center;gap:10px;color:var(--ui-ink-muted);font-size:13px}.community-page li svg{width:18px;color:var(--ui-success)}
@media(max-width:860px){.community-page{width:100%;min-height:auto;padding:48px 22px calc(48px + env(safe-area-inset-bottom));grid-template-columns:1fr;gap:38px}.community-copy h1{font-size:30px}.community-copy p{font-size:14px}.community-page aside{padding:20px;box-shadow:none}}
</style>
