import { useUserStore } from "../stores/user"

// H5 联调端口；真机运行需改为开发机局域网地址并配置小程序合法域名。
export const ASSISTANT_BASE_URL = "http://127.0.0.1:29183"

export function assistantChat(text: string, sessionId: string | null, progress?: (nodes:string[])=>void,allowWeb=false,knowledgeScope='platform',spaceId:string|null=null): Promise<any> {
  // #ifdef H5
  return streamChat(text,sessionId,progress,allowWeb,knowledgeScope,spaceId)
  // #endif
  // #ifndef H5
  return new Promise((resolve, reject) => {
    uni.request({
      url: ASSISTANT_BASE_URL + "/api/assistant/chat",
      method: "POST",
      header: { token: useUserStore().token || "", "Content-Type": "application/json" },
      data: { text, session_id: sessionId,allow_web:allowWeb,knowledge_scope:knowledgeScope,knowledge_space_id:spaceId },
      timeout: 120000,
      success: res => {
        const body = res.data as any
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(body)
        else reject(new Error(body.detail || "助手暂时不可用"))
      },
      fail: () => reject(new Error("无法连接助手，请检查服务地址"))
    })
  })
  // #endif
}

async function streamChat(text:string,sessionId:string|null,progress?: (nodes:string[])=>void,allowWeb=false,knowledgeScope='platform',spaceId:string|null=null){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),120000)
 try{
  const response=await fetch(ASSISTANT_BASE_URL+'/api/assistant/chat/stream',{method:'POST',headers:{token:useUserStore().token||'','Content-Type':'application/json'},body:JSON.stringify({text,session_id:sessionId,allow_web:allowWeb,knowledge_scope:knowledgeScope,knowledge_space_id:spaceId}),signal:controller.signal})
  if(!response.ok){const error=await response.json();throw Error(error.detail||'助手请求失败')}
  if(!response.body)throw Error('浏览器不支持流式响应')
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result:any
  while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let boundary
   while((boundary=buffer.indexOf('\n\n'))>=0){const event=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);const type=event.split('\n').find(v=>v.startsWith('event:'))?.slice(6).trim(),data=event.split('\n').find(v=>v.startsWith('data:'))?.slice(5).trim();if(!data)continue;const payload=JSON.parse(data);if(type==='progress')progress?.(payload.nodes||[]);if(type==='result')result=payload;if(type==='error')throw Error(payload.detail||'助手执行失败')}
  }
  if(!result)throw Error('响应提前结束，请重新查询');return result
 }finally{clearTimeout(timer)}
}

export async function assistantTask(payload:any){
 const response=await fetch(ASSISTANT_BASE_URL+'/api/assistant/tasks',{method:'POST',headers:{token:useUserStore().token||'','Content-Type':'application/json'},body:JSON.stringify(payload)})
 const body=await response.json();if(!response.ok)throw Error(body.detail||'办理请求失败');return body
}
