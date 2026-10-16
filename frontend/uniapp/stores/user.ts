import { defineStore } from "pinia"
import { TOKEN_KEY, USER_KEY } from "../utils/constant"
import { order, user } from "../api"
import { UpdateUserInfoInterface, UserInfoInterface, WechatUserInfoInterface } from "../api/user/interfaces"
import { clearRedirectUrl, getRedirectUrl } from "../utils/utils"
import { listeningRequest } from '../api/listening'

export const useUserStore = defineStore("user", {
  state: () => {
    return {
      user: JSON.parse(uni.getStorageSync(USER_KEY) || "{}") as UserInfoInterface,
      token: uni.getStorageSync(TOKEN_KEY),
      amount: 0,
    }
  },
  actions: {
    async loginWithPassword(username:string,password:string){
      const result=await listeningRequest('/api/account/login','POST',{username,password});
      this.token=result.token;uni.setStorageSync(TOKEN_KEY,result.token);await this.getUserInfo();
    },
    // 微信登陆
    loginWithWechat() {
      uni.login({
        provider: "weixin",
        success: async (loginRes:{code:string}) => {
          await this.getToken(loginRes.code)
          // 登录成功，获取用户信息
          await this.getUserInfo()
          const redirectUrl = getRedirectUrl()
          console.log('redirectUrl',redirectUrl)
          uni.redirectTo({
            url: redirectUrl ? redirectUrl : "/pages/index/index"
          })
          // 清空重定向url
          clearRedirectUrl()
          // 获取账户可用余额
          await this.getAccountBalance()
        },
        fail: (err:any) => {
          console.log(err)
        }
      })
    },
    // 获取token
    async getToken(code: string) {
      try {
        const res = await user.getLogin(code)
        if (res.data.token) {
          // 本地保存token
          uni.setStorageSync(TOKEN_KEY, res.data.token)
          this.token = res.data.token
        }
      } catch (error) {
        console.log(error)
      }
    },
    // 获取用户信息
    async getUserInfo() {
      const profile=await listeningRequest('/api/me');
      this.user=profile;uni.setStorageSync(USER_KEY,JSON.stringify(profile));
    },
    // 更新用户信息
    async updateUserInfo(userInfo: UpdateUserInfoInterface) {
      try {
        const res = await user.updateUserInfo(userInfo)
      }
      catch (error) {
        console.log(error)
      }
    },
    // 获取账户可用余额
    async getAccountBalance() {
      try {
        const res = await order.getAccountBalance()
        this.amount = res.data
      }
      catch (error) {
        console.log(error)
      }
    },
    // 退出登陆
    async logout() {
      try{await listeningRequest('/api/account/logout','POST')}catch(error){console.warn('退出登录时连接失败')}
      uni.removeStorageSync(TOKEN_KEY)
      uni.removeStorageSync(USER_KEY)
      // uni.clearStorageSync()  // 清空所有缓存 可能有些缓存不需要清理，先留着，以后看情况再说
      this.user = {} as UserInfoInterface
      this.token = ""
      // 回到首页
      uni.navigateTo({
        url: '/pages/index/index'
      })
    }
  }
})
