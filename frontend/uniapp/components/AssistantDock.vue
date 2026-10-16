<template>
  <div class="assistant-root">
    <NativeButton v-if="!state.open" class="assistant-launch" aria-label="打开听见助手" @click="open">
      <span class="spark">✦</span><span>听见助手</span><span class="launch-dot"></span>
    </NativeButton>
    <section v-show="state.open" :class="['assistant-panel', { fullscreen: state.full }]" role="dialog" :aria-modal="state.full" aria-label="听见助手">
      <header class="assistant-header">
        <span class="assistant-symbol">✦</span><div class="assistant-heading"><strong>听见助手</strong><span>{{ state.busy ? '正在为你查找…' : '让每一次聆听，都有回应' }}</span></div>
        <NativeButton class="icon-button" aria-label="新建对话" :disabled="state.busy" @click="assistant.newConversation">＋</NativeButton>
        <NativeButton class="icon-button" :aria-label="state.full ? '退出全屏' : '全屏助手'" @click="state.full = !state.full">{{ state.full ? '↙' : '⤢' }}</NativeButton>
        <NativeButton class="icon-button" aria-label="收起助手" @click="close">×</NativeButton>
      </header>
      <div v-if="user.token" class="knowledge-scope"><label>检索范围 <ScopeSelect :value="state.knowledgeSpaceId||''" :spaces="state.spaces" :disabled="state.busy" @change-scope="assistant.selectKnowledgeSpace($event||null)" /></label><NativeButton @click="personalLibrary">我的知识空间 ↗</NativeButton></div>
      <div ref="messageArea" class="assistant-messages" aria-live="polite">
        <div v-if="!state.messages.length" class="assistant-welcome">
          <div class="welcome-mark">✦</div><span class="eyebrow">YOUR LISTENING COMPANION</span><h2>想听什么，<br>或者想了解什么？</h2>
          <p>一起探索书中的世界，也可以帮你找回收听进度、查询会员和订单。</p>
          <template v-if="state.knowledgeScope==='personal'"><p>当前只检索你选择的私人空间。可以提问自己的笔记、书签和上传资料。</p><NativeButton class="task-start" @click="assistant.send('查看我的听书回顾')">查看我的听书回顾</NativeButton></template>
          <div v-else class="prompt-grid"><NativeButton v-for="prompt in prompts" :key="prompt.title" @click="assistant.send(prompt.text)"><span>{{ prompt.icon }}</span><strong>{{ prompt.title }}</strong><small>{{ prompt.subtitle }}</small></NativeButton></div>
          <div v-if="!user.token" class="login-tip">登录后开始你的专属对话 <NativeButton @click="login">去登录 →</NativeButton></div>
        </div>
        <article v-for="(message, index) in state.messages" :key="index" :class="['chat-message', message.role]">
          <span class="message-avatar">{{ message.role === 'user' ? '你' : '✦' }}</span><div class="message-body"><span class="message-label">{{ message.role === 'user' ? '你' : '听见助手' }}</span><div class="message-text">{{ message.text }}</div>
            <details v-for="(source, sourceIndex) in message.sources || []" :key="sourceIndex" class="evidence"><summary>{{ source.citation ? '[' + source.citation + '] ' : '' }}{{ source.title || source.source || '资料来源' }} · 原文</summary><p>{{ source.quote || source.source }}</p></details>
            <NativeButton v-for="source in (message.sources||[]).filter((s:any)=>s.space_id)" :key="source.chunk_id" class="personal-source" @click="personalSource(source)">查看我的资料 · {{source.title}}</NativeButton>
            <details v-if="message.graphTrace?.length" class="evidence"><summary>查看查询步骤</summary><p>{{ message.graphTrace.map((node: string) => ({ model: '选择查询方式', tools: '读取查询结果', guard: '检查执行次数' }[node] || node)).join(' → ') }}</p></details>
          </div>
        </article>
        <section v-if="state.task" class="evidence task-card"><p>{{state.task.paused?'办理已暂停，可先咨询其他问题。':state.task.text}}</p>
          <template v-if="!state.task.paused"><div v-for="order in state.task.choices||[]" :key="order.id"><NativeButton :disabled="state.busy" @click="assistant.taskAction('reply',order.id)">{{order.title}} · ¥{{order.amount}} · {{order.orderNo}}</NativeButton></div>
          <p v-if="state.task.draft">订单：{{state.task.draft.orderNo}}<br>金额：¥{{state.task.draft.amount}}<br>原因：{{state.task.draft.reason}}</p>
          <NativeButton v-if="state.task.field==='confirmation'" :disabled="state.busy" @click="confirmTask">确认提交人工审核</NativeButton>
          <NativeButton :disabled="state.busy" @click="assistant.taskAction('pause')">先问别的</NativeButton></template>
          <NativeButton v-else :disabled="state.busy" @click="assistant.taskAction('resume')">继续办理</NativeButton>
          <NativeButton :disabled="state.busy" @click="assistant.taskAction('cancel')">取消办理</NativeButton>
        </section>
        <div v-if="state.busy" class="thinking"><span></span><span></span><span></span> {{state.progress||'正在查询，请稍候'}}</div>
      </div>
      <footer class="assistant-composer">
        <div v-if="state.error" class="assistant-error" role="alert">{{ state.error }} <NativeButton v-if="!user.token" @click="login">去登录</NativeButton></div>
        <div class="composer-box"><NativeTextarea data-assistant-input ref="editor" v-model="state.draft" rows="2" maxlength="2000" aria-label="给听见助手发送消息" placeholder="问问书籍、收听进度或订单…" @keydown="onKeydown"></NativeTextarea><NativeButton class="send-button" aria-label="发送消息" :disabled="state.busy || !state.draft.trim()" @click="assistant.send()">{{ state.busy ? '•••' : '↑' }}</NativeButton></div>
        <div class="composer-caption"><NativeButton class="task-start" :disabled="state.busy||!!state.task||!user.token||state.knowledgeScope==='personal'" @click="assistant.taskAction('start')">办理售后</NativeButton><label v-if="state.knowledgeScope!=='personal'" class="web-option"><NativeCheckbox v-model="state.allowWeb" :disabled="state.busy" aria-label="允许联网补充" />联网补充（有用量）</label><span v-else>私人资料对话 · 联网关闭</span><span class="keyboard-hint">Enter 发送</span></div>
      </footer>
    </section>
  </div>
</template>
<script setup lang="ts">
import { defineComponent, h, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAssistantStore } from '../stores/assistant'
import { useUserStore } from '../stores/user'
const NativeButton = defineComponent({ inheritAttrs: false, setup(_, { attrs, slots }) { return () => h('button', { type: 'button', ...attrs }, slots.default?.()) } })
const ScopeSelect=defineComponent({props:['value','spaces','disabled'],emits:['change-scope'],setup(p,{emit}){return()=>h('select',{'aria-label':'助手知识范围',value:p.value,disabled:p.disabled,onChange:(e:any)=>emit('change-scope',e.target.value)},[h('option',{value:''},'平台资料与业务'),...p.spaces.map((s:any)=>h('option',{value:s.id},'私人 · '+s.name))])}})
const NativeCheckbox = defineComponent({ inheritAttrs: false, props: { modelValue: Boolean }, emits: ['update:modelValue'], setup(props, { attrs, emit }) {
  return () => h('input', { ...attrs, type: 'checkbox', checked: props.modelValue, onChange: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).checked) })
} })
const NativeTextarea = defineComponent({ inheritAttrs: false, props: { modelValue: String }, emits: ['update:modelValue'], setup(props, { attrs, emit, expose }) {
  const control = ref<HTMLTextAreaElement>()
  expose({ focus: () => control.value?.focus() })
  return () => h('textarea', { ...attrs, ref: control, value: props.modelValue, onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLTextAreaElement).value) })
} })
const assistant = useAssistantStore(), state = assistant.state, user = useUserStore()
const messageArea = ref<HTMLElement>(), editor = ref<{ focus: () => void }>()
let previousFocus: HTMLElement | null = null
const prompts = [
  { icon: '◷', title: '找回收听进度', subtitle: '从上次停下的地方继续', text: '查询我的收听进度' },
  { icon: '≋', title: '探索书中世界', subtitle: '带原文依据的资料问答', text: '《三体》用户评论中提到的阅读门槛是什么？' },
  { icon: '◇', title: '我的会员', subtitle: '查询当前会员状态', text: '查询我的会员状态' },
  { icon: '▤', title: '订单与售后', subtitle: '了解订单和申请状态', text: '查询我的订单和售后记录' },
]
function open() { state.open = true; state.full = false;assistant.loadSpaces() }
function personalLibrary(){state.open=false;uni.navigateTo({url:'/pages/knowledge/knowledge'})}
function personalSource(source:any){state.open=false;uni.navigateTo({url:'/pages/knowledge/knowledge?space='+source.space_id+(source.item_id?'&item='+source.item_id:'&tab=review')})}
function close() { state.open = false; previousFocus?.focus() }
function login() { state.open = false; uni.navigateTo({ url: '/pages/login/login' }) }
function confirmTask(){if(window.confirm('确认将订单 '+state.task.draft.orderNo+' 的售后申请提交人工审核？此操作不会直接退款。'))assistant.taskAction('confirm')}
function onKeydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); assistant.send() } }
function keyboard(event: KeyboardEvent) {
  if (event.key === 'Escape' && state.open) { event.preventDefault(); if (state.full) state.full = false; else close() }
  if (event.key === 'Tab' && state.open && state.full) {
    const panel = document.querySelector('.assistant-panel')!
    const elements = Array.from(panel.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea, summary')).filter(element => element.getClientRects().length)
    const first = elements[0], last = elements[elements.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
}
watch(() => state.open, async open => { if (open) { previousFocus = document.activeElement as HTMLElement; await nextTick(); editor.value?.focus() } })
watch(() => [state.messages.length, state.busy, state.open, state.full], async () => { await nextTick(); if (messageArea.value) messageArea.value.scrollTop = state.messages.length ? messageArea.value.scrollHeight : 0 })
onMounted(() => document.addEventListener('keydown', keyboard))
onUnmounted(() => document.removeEventListener('keydown', keyboard))
</script>
<style>
.assistant-root{font-family:Inter,"PingFang SC","Microsoft YaHei",sans-serif;color:#203d36;font-size:14px;--accent:#285a4b}.assistant-root *{box-sizing:border-box}.assistant-root [type="button"]{font:inherit;cursor:pointer;margin:0;line-height:normal}.assistant-root [type="button"]:after{display:none}.assistant-root [type="button"]:disabled{opacity:.4;cursor:default}.assistant-root [type="button"]:focus-visible,.assistant-root [data-assistant-input]:focus-visible,.assistant-root summary:focus-visible{outline:3px solid #9ac4b2;outline-offset:3px}.assistant-launch{position:fixed;right:28px;bottom:100px;z-index:1000;border:1px solid #386a57;border-radius:100px;background:#285a4b;color:#fff;padding:14px 20px;display:flex;gap:12px;align-items:center;box-shadow:0 8px 30px #153d3529;transition:transform .2s}.assistant-launch:hover{transform:translateY(-3px)}.spark{font-size:23px;color:#e4dbb5}.launch-dot{width:6px;height:6px;border-radius:50%;background:#b9d6b5}.assistant-panel{position:fixed;right:24px;bottom:24px;z-index:1001;width:420px;height:min(740px,calc(100dvh - 48px));background:#fffefa;border:1px solid #d7e2d7;border-radius:24px;box-shadow:0 22px 90px #203d3630;display:flex;flex-direction:column;overflow:hidden}.assistant-panel.fullscreen{inset:0;width:100%;height:100dvh;border-radius:0;background:#f7f8f3}.assistant-header{display:flex;align-items:center;gap:10px;padding:20px 18px;border-bottom:1px solid #e4e9e1;background:#fffefa;flex-shrink:0}.assistant-symbol{width:38px;height:38px;background:#eaf0e6;border-radius:12px;display:grid;place-items:center;font-size:26px;color:#285a4b}.assistant-heading{flex:1;min-width:0;display:flex;flex-direction:column;gap:4px}.assistant-heading strong{font-size:16px}.assistant-heading>span{font-size:11px;color:#7c8b80}.assistant-root .icon-button{width:30px;height:30px;border:0;background:transparent;color:#486052;border-radius:8px;font-size:23px;padding:0}.assistant-root .icon-button:hover{background:#edf1e8}.assistant-messages{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:24px 20px;scroll-behavior:smooth}.assistant-welcome{text-align:center;padding:12px 0}.welcome-mark{margin:0 auto 16px;width:64px;height:64px;border-radius:22px;background:linear-gradient(135deg,#e2ead9,#f2eddb);display:grid;place-items:center;color:#285a4b;font-size:38px}.eyebrow{font-size:9px;letter-spacing:2px;color:#7b927f}.assistant-welcome h2{font-size:25px;font-weight:500;line-height:1.5;margin:12px 0}.assistant-welcome p{font-size:12px;line-height:1.9;color:#7c8b80;max-width:310px;margin:0 auto 24px}.prompt-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;text-align:left}.assistant-root .prompt-grid [type="button"]{padding:15px 12px;display:flex;flex-direction:column;gap:7px;border:1px solid #e0e6db;background:#fffefa;border-radius:13px;text-align:left;color:#375448}.prompt-grid [type="button"]>span{font-size:19px;color:#789a82}.prompt-grid strong{font-size:12px;font-weight:500}.prompt-grid small{font-size:10px;color:#8a9489}.prompt-grid [type="button"]:hover{border-color:#9fb59f;background:#f0f4ec}.login-tip{padding-top:20px;font-size:12px;color:#889386}.assistant-root .login-tip [type="button"],.assistant-root .assistant-error [type="button"]{border:0;background:transparent;color:#285a4b;font-size:12px;display:inline;padding:4px}.chat-message{display:flex;gap:10px;margin:0 0 23px}.message-avatar{width:28px;height:28px;display:grid;place-items:center;background:#e6ece0;color:#285a4b;border-radius:9px;flex-shrink:0;font-size:16px}.message-body{min-width:0;flex:1}.message-label{display:block;font-size:10px;color:#849283;margin:3px 0 8px}.message-text{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.9}.chat-message.user{flex-direction:row-reverse}.user .message-body{text-align:right}.user .message-text{display:inline-block;background:#285a4b;color:#fff;padding:12px 16px;border-radius:15px 3px 15px 15px;text-align:left}.user .message-avatar{background:#ece9dd;color:#8a7858;font-size:11px}.evidence{margin-top:12px;border:1px solid #dce6d7;border-radius:10px;background:#edf3e8;font-size:11px}.evidence summary{cursor:pointer;padding:10px;overflow-wrap:anywhere;color:#456850}.evidence p{white-space:pre-wrap;padding:0 10px 10px;line-height:1.8;max-height:240px;overflow:auto;margin:0}.assistant-composer{flex-shrink:0;padding:14px 16px 18px;border-top:1px solid #e4e9e1;background:#fffefa}.composer-box{border:1px solid #d9e1d2;border-radius:14px;padding:12px;display:flex;align-items:flex-end;background:#f7f8f2;gap:8px}.composer-box [data-assistant-input]{border:0;outline:none;background:transparent;resize:none;flex:1;height:54px;padding:0;min-width:0;line-height:1.7;font:inherit;color:#203d36}.assistant-root .send-button{width:34px;height:34px;border:0;border-radius:10px;background:#285a4b;color:white;font-size:22px;padding:0}.composer-caption{display:flex;justify-content:space-between;font-size:9px;color:#96a18f;margin-top:10px;gap:6px}.assistant-error{color:#9b5340;background:#fbefe7;font-size:12px;padding:8px 10px;margin-bottom:10px;border-radius:8px}.thinking{font-size:12px;color:#889884;display:flex;gap:5px;align-items:center}.thinking>span{width:5px;height:5px;background:#8ba27b;border-radius:50%;animation:pulse 1s infinite alternate}.thinking>span:nth-child(2){animation-delay:.2s}.thinking>span:nth-child(3){animation-delay:.4s}@keyframes pulse{to{opacity:.2}}.fullscreen .assistant-messages{padding:40px max(24px,calc((100vw - 790px)/2))}.fullscreen .assistant-welcome{padding-top:35px;max-width:660px;margin:auto}.fullscreen .assistant-welcome h2{font-size:36px}.fullscreen .prompt-grid{gap:14px}.fullscreen .prompt-grid [type="button"]{padding:22px}.fullscreen .assistant-composer{padding:20px max(24px,calc((100vw - 790px)/2)) 24px}.fullscreen .message-text{font-size:15px}.fullscreen .assistant-header{padding:18px 30px}.fullscreen .assistant-welcome p{max-width:470px;font-size:14px}.fullscreen .prompt-grid strong{font-size:14px}.fullscreen .prompt-grid small{font-size:12px}
.assistant-panel:not(.fullscreen) .assistant-welcome{padding:0}.assistant-panel:not(.fullscreen) .welcome-mark{width:48px;height:48px;font-size:30px;border-radius:16px;margin-bottom:12px}.assistant-panel:not(.fullscreen) .assistant-welcome h2{font-size:23px;margin:10px 0;line-height:1.4}.assistant-panel:not(.fullscreen) .assistant-welcome p{line-height:1.7;margin-bottom:16px}.assistant-panel:not(.fullscreen) .prompt-grid [type="button"]{padding:12px;gap:5px}.assistant-panel:not(.fullscreen) .login-tip{padding-top:12px}
@media(max-width:600px){.assistant-launch{right:16px;bottom:94px;padding:12px 16px}.assistant-panel{right:10px;bottom:10px;width:calc(100vw - 20px);height:min(650px,calc(100dvh - 20px));border-radius:20px}.assistant-header{padding:16px 12px}.assistant-messages{padding:18px 16px}.assistant-panel.fullscreen{width:100%;height:100dvh}.fullscreen .assistant-messages{padding:24px 16px}.fullscreen .assistant-composer{padding:14px 16px max(16px,env(safe-area-inset-bottom))}.fullscreen .assistant-header{padding:16px 12px}.fullscreen .assistant-welcome{padding-top:16px}.fullscreen .assistant-welcome h2{font-size:28px}.fullscreen .prompt-grid [type="button"]{padding:16px 12px}.keyboard-hint{display:none}}@media(prefers-reduced-motion:reduce){.assistant-messages{scroll-behavior:auto}.thinking>span{animation:none}.assistant-launch{transition:none}}
</style>
<style>
.assistant-root .task-start,.assistant-root .task-card [type="button"]{border:1px solid #b9cbb9;background:#f0f5ec;color:#285a4b;border-radius:8px;padding:8px 12px;font-size:12px;line-height:1.5;white-space:normal;text-align:left}
.knowledge-scope{padding:9px 16px;border-bottom:1px solid #e4e9e1;display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:11px;flex-wrap:wrap;background:#fffefa}.knowledge-scope select{max-width:230px;border:1px solid #d9e2d3;border-radius:7px;background:#f6f8ef;padding:6px;color:#365a45;font:inherit}.assistant-root .knowledge-scope button,.assistant-root .personal-source{border:0;background:transparent;color:#365a45;font-size:11px;padding:6px}.assistant-root .personal-source{margin-top:8px}.knowledge-scope label{display:flex;align-items:center;gap:6px}
.assistant-root .task-start:hover,.assistant-root .task-card [type="button"]:hover{background:#e3eddd}.task-card{padding:12px;display:flex;flex-wrap:wrap;gap:8px}.task-card>p,.task-card>div{width:100%}.task-card p{padding:0;margin:0 0 4px}.task-card>div [type="button"]{width:100%;overflow-wrap:anywhere}.composer-caption{align-items:center;flex-wrap:wrap}.web-option{display:flex;align-items:center;gap:6px;font-size:11px;cursor:pointer;color:#6b806d}.web-option input[type="checkbox"]{width:15px;height:15px;accent-color:#285a4b;margin:0}.assistant-root input:focus-visible{outline:3px solid #9ac4b2;outline-offset:3px}
</style>
