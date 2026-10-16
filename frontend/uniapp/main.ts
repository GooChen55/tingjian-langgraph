import App from "./App";
import { createSSRApp } from "vue";
// #ifdef H5
import { createApp as createDockApp } from 'vue';
import AssistantDock from './components/AssistantDock.vue';
// #endif
import { createPinia } from "pinia";
import piniaPersist from "pinia-plugin-persist-uni";
import { useUpdateUserInfo } from "./hooks/useUpdateUserInfo"
// 引入全局事件总线mitt
import  "./utils/mitt"
const pinia = createPinia();
pinia.use(piniaPersist);
/* 全局挂载请求库 */
import GraceRequest from "@/Grace6/js/request.js";
uni.gRequest = GraceRequest;

export function createApp() {
  const app = createSSRApp(App);
  app.use(pinia);
  // 进入页面自动触发请求的数据
  let { updateUserInfo } = useUpdateUserInfo()
  updateUserInfo()
  // #ifdef H5
  queueMicrotask(() => {
    if (!document.getElementById('listening-assistant-root')) {
      const host = document.createElement('div');
      host.id = 'listening-assistant-root';
      document.body.appendChild(host);
      createDockApp(AssistantDock).use(pinia).mount(host);
    }
  });
  // #endif
  return {
    app,
  };
}
