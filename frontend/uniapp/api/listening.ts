import { useUserStore } from '../stores/user'
import { BASE_URL } from '../config/confjg'
export function listeningRequest(path:string,method:'GET'|'POST'='GET',data?:any):Promise<any>{
 const requestToken=useUserStore().token||'';
 return new Promise((resolve,reject)=>uni.request({url:BASE_URL+path,method,data,header:{token:requestToken,'Content-Type':'application/json'},timeout:120000,
 success:res=>{const body=res.data as any;if(res.statusCode>=200&&res.statusCode<300)resolve(body);else{if(res.statusCode===401&&useUserStore().token===requestToken){useUserStore().token='';uni.removeStorageSync('token')}reject(new Error(typeof body.detail==='string'?body.detail:'请求失败'))}},
 fail:()=>reject(new Error('无法连接听书服务'))}));
}
