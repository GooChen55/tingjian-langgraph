<template>
  <view class="page">
    <view class="intro">了解书籍 · 查询会员 · 找回收听进度</view>
    <button size="mini" @click="go('/pages/business/business')">我的订单与售后</button>
    <button v-if="!store.token" size="mini" @click="go('/pages/login/login')">账号登录</button>
    <scroll-view scroll-y class="messages" :scroll-top="scrollTop">
      <view v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
        <view class="label">{{ message.role === 'user' ? '你' : '听见助手' }}</view>
        <text selectable class="text">{{ message.text }}</text>
        <view v-for="source in message.sources || []" :key="source.chunk_id || source.source || source.title" class="source"><text @click="source.expanded=!source.expanded">{{source.citation?'['+source.citation+'] ':''}}{{ source.title || source.source }} · 展开原文</text><text v-if="source.expanded" style="display:block;white-space:pre-wrap">{{source.quote||source.source}}</text></view>
      </view>
    </scroll-view>
    <view class="compose"><input v-model="input" :maxlength="2000" placeholder="问问书籍或收听进度" @confirm="send" /><button :disabled="busy" @click="send">{{ busy ? '处理中' : '发送' }}</button></view>
  </view>
</template>
<script setup lang="ts">
// #ifdef H5
import {onLoad} from '@dcloudio/uni-app'
import {openAssistant} from '../../stores/assistant'
onLoad(()=>uni.redirectTo({url:'/pages/index/index',success:()=>openAssistant(true)}))
// #endif

import { ref } from "vue"
import { assistantChat } from "../../api/assistant"
import {useUserStore} from "../../stores/user"
const store=useUserStore();function go(url:string){uni.navigateTo({url})}
const input = ref(''), busy = ref(false), sessionId = ref<string | null>(null), scrollTop = ref(0)
const messages = ref<any[]>([{role:'assistant', text:'你好，我可以查书籍资料、收听进度、会员、订单和售后记录。回答中的资料可以展开核对原文。'}])
async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  busy.value = true; input.value = ''; messages.value.push({role:'user', text})
  try {
    const result = await assistantChat(text, sessionId.value)
    sessionId.value = result.session_id
    messages.value.push({role:'assistant', text:result.text, sources:result.sources})
  } catch (error:any) { messages.value.push({role:'assistant', text:error.message}) }
  finally { busy.value = false; scrollTop.value += 10000 }
}
</script>
<style scoped>
.page{padding:24rpx;background:#f3f5ef;min-height:100vh}.intro{color:#647e72;padding:20rpx}.messages{height:72vh}.message{margin:24rpx 0;padding:24rpx;background:white;border-radius:18rpx}.user{background:#244f45;color:white;margin-left:60rpx}.label{font-size:22rpx;opacity:.65;margin-bottom:12rpx}.text{white-space:pre-wrap;line-height:1.8;font-size:28rpx}.source{font-size:22rpx;color:#678474;margin-top:16rpx}.compose{display:flex;gap:16rpx;align-items:center;padding:18rpx 0}.compose input{flex:1;background:white;padding:22rpx;border-radius:14rpx}.compose button{background:#244f45;color:white;font-size:26rpx}
</style>
