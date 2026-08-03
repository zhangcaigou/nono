import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios'
import { ApiErrorResponse } from '@/types'

// 开发模式使用 Vite 代理（同源请求，避免 CORS），生产模式使用完整 URL
const API_BASE_URL = import.meta.env.DEV
  ? ''
  : (import.meta.env.VITE_API_BASE_URL || 'http://10.71.199.207:8080')

// 创建 axios 实例
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：可添加 token 等
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 从 localStorage 读取 token（如果需要）
    // const token = localStorage.getItem('access_token')
    // if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一处理错误格式
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorResponse>) => {
    // 如果后端返回了标准错误格式，我们直接抛出整个 error，方便上层处理
    // 也可以在此处统一转为自定义 Error
    return Promise.reject(error)
  }
)

export default apiClient