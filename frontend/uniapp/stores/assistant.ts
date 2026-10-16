import { defineStore } from 'pinia'
import { reactive, watch } from 'vue'
import { useUserStore } from './user'
import { assistantChat,assistantTask,ASSISTANT_BASE_URL } from '../api/assistant'

export const useAssistantStore = defineStore('listening-assistant', () => {
  const state = reactiveState()
  const user = useUserStore()
  let generation = 0
  watch(() => user.token, () => { generation++; reset();state.knowledgeScope='platform';state.knowledgeSpaceId=null;state.spaces=[];state.allowWeb=false;loadSpaces() }, { flush: 'sync' })
  function storageKey(){return 'listening-assistant-session-'+(user.user?.id||'anonymous')+(state.knowledgeScope==='personal'?'-personal-'+state.knowledgeSpaceId:'')}
  async function loadSpaces(){
    if(!user.token)return
    const token=user.token
    try{const response=await fetch(ASSISTANT_BASE_URL+'/api/personal/spaces',{headers:{token}});if(response.ok){const data=await response.json();if(token===user.token)state.spaces=data.records}}catch{}
  }
  async function selectKnowledgeSpace(id:string|null){
    if(state.busy)return
    if(id){await loadSpaces();if(!state.spaces.some((s:any)=>s.id===id))throw Error('该知识空间不可访问')}
    generation++;reset();state.knowledgeScope=id?'personal':'platform';state.knowledgeSpaceId=id;state.allowWeb=false;await restore()
  }
  async function restore(){
    if(typeof sessionStorage==='undefined'||!user.token)return
    const sid=sessionStorage.getItem(storageKey());if(!sid)return
    const current=generation
    try{
      const headers={token:user.token},response=await fetch(ASSISTANT_BASE_URL+'/api/history/'+sid,{headers})
      if(!response.ok){sessionStorage.removeItem(storageKey());return}
      const body=await response.json(),pending=await fetch(ASSISTANT_BASE_URL+'/api/assistant/tasks/current/'+sid,{headers})
      const task=await pending.json()
      if(generation!==current)return
      state.sessionId=sid;state.messages=body.messages;state.task=task.task?.task||null
    }catch{}
  }
  restore()
  loadSpaces()
  function reset() {
    state.messages = []
    state.sessionId = null
    state.draft = ''
    state.busy = false
    state.error = ''
    state.task = null;state.progress=''
  }
  async function send(prompt?: string) {
    const text = (prompt ?? state.draft).trim()
    if (!text || state.busy) return
    if (!user.token) { state.error = '登录听书账号后，即可开始对话。'; return }
    const current = generation
    state.draft = ''; state.error = '';state.progress=''; state.busy = true
    state.messages.push({ role: 'user', text })
    try {
      const result = state.task&&!state.task.paused
        ? await assistantTask({action:'reply',task_id:state.task.id,session_id:state.sessionId,text})
        : await assistantChat(text, state.sessionId,nodes=>{if(generation===current)state.progress=nodes.map(n=>({model:'正在选择工具',tools:'已读取查询结果',guard:'正在检查执行次数'}[n]||n)).join('、')},state.allowWeb,state.knowledgeScope,state.knowledgeSpaceId)
      if (generation !== current) return
      state.sessionId = result.session_id
      if(Object.prototype.hasOwnProperty.call(result,'task'))state.task=result.task||null
      if(typeof sessionStorage!=='undefined')sessionStorage.setItem(storageKey(),result.session_id)
      state.messages.push({ role: 'assistant', text: result.text, sources: result.sources || [], graphTrace: result.graph_trace || [] })
    } catch (error: any) {
      if (generation === current) { state.error = error.message || '请求失败，请稍后重试'; state.draft = text }
    } finally { if (generation === current) state.busy = false }
  }
  async function taskAction(action:string,text=''){
    if(state.busy||!user.token)return
    if(state.knowledgeScope==='personal'){state.error='办理售后请先切换到平台助手';return}
    const current=generation;state.busy=true;state.error=''
    try{
      const result=await assistantTask({action,task_id:state.task?.id,session_id:state.sessionId,text,...(action==='confirm'?{draft_id:state.task?.draft?.id,confirmed:true}:{})})
      if(current!==generation)return
      state.sessionId=result.session_id;state.task=result.task||null
      state.messages.push({role:'assistant',text:result.text,sources:[],graphTrace:result.graph_trace||[]})
      if(typeof sessionStorage!=='undefined')sessionStorage.setItem(storageKey(),result.session_id)
    }catch(error:any){if(current===generation)state.error=error.message}
    finally{if(current===generation)state.busy=false}
  }
  function newConversation() { if (!state.busy) { if(typeof sessionStorage!=='undefined')sessionStorage.removeItem(storageKey());generation++; reset() } }
  return { state, send,taskAction, newConversation,selectKnowledgeSpace,loadSpaces }
})

function reactiveState() {
  return reactive({ open: false, full: false, draft: '', busy: false, error: '',progress:'',allowWeb:false,knowledgeScope:'platform',knowledgeSpaceId:null as string|null,spaces:[] as any[],task:null as any, sessionId: null as string | null, messages: [] as any[] })
}

export function openAssistant(full = false) {
  // #ifdef H5
  const assistant = useAssistantStore()
  assistant.state.open = true
  assistant.state.full = full
  return
  // #endif
  // #ifndef H5
  uni.navigateTo({ url: '/pages/assistant/assistant' })
  // #endif
}
