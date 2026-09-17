<template>
  <main class="workspace-gateway">
    <section class="gateway-shell" aria-labelledby="workspace-title">
      <header class="gateway-heading">
        <div class="gateway-brand" aria-label="攀岩助手">
          <span class="gateway-brand-mark"><Grid /></span>
          <span><strong>攀岩助手</strong><small>CLIMB WORKSPACE</small></span>
        </div>
        <div class="gateway-account-state">
          <i />
          <span>{{ authenticated ? `${displayName || username || '当前账号'}已登录` : '选择项目后登录' }}</span>
        </div>
        <div class="gateway-title-copy">
          <p>选择工作区</p>
          <h1 id="workspace-title">今天要处理哪类项目？</h1>
          <span>两套项目各自保留独立入口和工具，账号与已保存数据不会改变。</span>
        </div>
      </header>

      <div class="workspace-options">
        <button class="workspace-card is-boulder" type="button" @click="emit('select', 'boulder')">
          <span class="workspace-card-topline"><span class="workspace-icon"><PictureFilled /></span><small>照片工作流</small></span>
          <span class="workspace-card-copy">
            <strong>抱石项目</strong>
            <span>从墙面照片识别岩点，复核颜色与轮廓，保存个人抱石线路。</span>
          </span>
          <span class="workspace-capabilities" aria-label="抱石项目功能">
            <span>照片识别</span><span>岩点复核</span><span>线路保存</span>
          </span>
          <span class="workspace-enter">进入抱石项目 <ArrowRight /></span>
        </button>

        <button class="workspace-card is-setter" type="button" @click="emit('select', 'setter')">
          <span class="workspace-card-topline"><span class="workspace-icon"><Platform /></span><small>岩板工作流</small></span>
          <span class="workspace-card-copy">
            <strong>定线项目</strong>
            <span>继续使用原有岩板、岩点、标准线路库与辅助审核工具。</span>
          </span>
          <span class="workspace-capabilities" aria-label="定线项目功能">
            <span>岩板定线</span><span>标准板库</span><span>AI 辅助</span>
          </span>
          <span class="workspace-enter">进入定线项目 <ArrowRight /></span>
        </button>
      </div>

      <p class="gateway-footnote">进入后可从顶部“返回项目选择”回到这里。</p>
    </section>
  </main>
</template>

<script setup>
import { ArrowRight, Grid, PictureFilled, Platform } from '@element-plus/icons-vue'

defineProps({
  authenticated: Boolean,
  username: { type: String, default: '' },
  displayName: { type: String, default: '' },
})
const emit = defineEmits(['select'])
</script>

<style scoped>
.workspace-gateway{min-height:100dvh;padding:32px;background:var(--ui-ground);display:grid;place-items:center}
.gateway-shell{box-sizing:border-box;width:min(1040px,100%);padding:42px;border:1px solid var(--ui-line);border-radius:24px;background:var(--ui-surface);box-shadow:0 18px 46px rgba(35,33,28,.09)}
.gateway-heading{display:grid;grid-template-columns:1fr auto;align-items:center;gap:24px}.gateway-brand{display:flex;align-items:center;gap:12px}.gateway-brand-mark{width:46px;height:46px;border-radius:13px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;transform:rotate(-2deg)}.gateway-brand-mark svg{width:22px}.gateway-brand>span:last-child{display:grid}.gateway-brand strong{font-size:19px;line-height:1.3}.gateway-brand small{color:var(--ui-ink-muted);font-size:9px;font-weight:600;letter-spacing:.15em}
.gateway-account-state{min-height:34px;padding:6px 10px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-small);color:var(--ui-ink-muted);display:flex;align-items:center;gap:7px;font-size:12px}.gateway-account-state i{width:7px;height:7px;border-radius:50%;background:var(--ui-success)}
.gateway-title-copy{grid-column:1/-1;max-width:680px;margin-top:14px}.gateway-title-copy p{margin:0 0 5px;color:var(--ui-warning);font-size:12px;font-weight:600}.gateway-title-copy h1{font-size:30px}.gateway-title-copy>span{display:block;margin-top:8px;color:var(--ui-ink-muted);font-size:14px}
.workspace-options{margin-top:30px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.workspace-card{position:relative;min-width:0;min-height:310px;padding:24px;border:1px solid var(--ui-line);border-radius:16px;background:var(--ui-surface-raised);color:var(--ui-ink);display:flex;flex-direction:column;align-items:stretch;text-align:left;cursor:pointer;overflow:hidden;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}.workspace-card::after{content:"";position:absolute;right:-34px;bottom:-52px;width:150px;height:150px;border:22px solid var(--ui-surface-subtle);border-radius:50%;opacity:.7}.workspace-card:hover{border-color:var(--ui-line-strong);box-shadow:var(--ui-shadow-float);transform:translateY(-3px)}.workspace-card:focus-visible{outline:3px solid var(--ui-focus);outline-offset:3px}.workspace-card.is-boulder:hover{border-color:var(--ui-brand)}
.workspace-card-topline{display:flex;align-items:center;justify-content:space-between}.workspace-card-topline small{color:var(--ui-ink-muted);font-size:12px;font-weight:500}.workspace-icon{width:48px;height:48px;border-radius:13px;background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;place-items:center}.is-setter .workspace-icon{background:var(--ui-surface-subtle);color:var(--ui-ink)}.workspace-icon svg{width:23px;height:23px}
.workspace-card-copy{margin-top:25px;display:grid;gap:8px}.workspace-card-copy strong{font-size:24px;line-height:1.35}.workspace-card-copy>span{max-width:32ch;color:var(--ui-ink-muted);font-size:14px;line-height:1.65}
.workspace-capabilities{position:relative;z-index:1;margin-top:20px;display:flex;flex-wrap:wrap;gap:7px}.workspace-capabilities span{padding:5px 8px;border:1px solid var(--ui-line);border-radius:999px;background:var(--ui-surface);color:var(--ui-ink-muted);font-size:11px}
.workspace-enter{position:relative;z-index:1;margin-top:auto;padding-top:24px;display:flex;align-items:center;justify-content:space-between;font-size:14px;font-weight:600}.workspace-enter svg{width:18px}.gateway-footnote{margin:22px 0 0;color:var(--ui-ink-faint);font-size:12px;text-align:center}
@media(max-width:700px){.workspace-gateway{padding:0;place-items:start stretch}.gateway-shell{min-height:100dvh;padding:24px 18px 32px;border:0;border-radius:0;box-shadow:none}.gateway-heading{grid-template-columns:1fr}.gateway-account-state{display:none}.gateway-title-copy{margin-top:14px}.gateway-title-copy h1{font-size:26px}.gateway-title-copy>span{font-size:13px}.workspace-options{margin-top:24px;grid-template-columns:1fr;gap:12px}.workspace-card{min-height:238px;padding:20px}.workspace-card-copy{margin-top:18px}.workspace-card-copy strong{font-size:22px}.workspace-capabilities{margin-top:14px}.workspace-enter{padding-top:18px}}
@media(prefers-reduced-motion:reduce){.workspace-card{transition:none}}
</style>
