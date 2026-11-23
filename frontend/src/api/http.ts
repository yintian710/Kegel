import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'

export interface ApiEnvelope<T> {
  code: number
  data: T
  msg: string
}

export class ApiError extends Error {
  readonly code: number
  readonly status: number

  constructor(message: string, code: number, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

function isEnvelope(value: unknown): value is ApiEnvelope<unknown> {
  return typeof value === 'object' && value !== null
    && typeof (value as Partial<ApiEnvelope<unknown>>).code === 'number'
    && typeof (value as Partial<ApiEnvelope<unknown>>).msg === 'string'
    && 'data' in value
}

export const http = axios.create({
  // 默认 /api；子路径部署（如测试环境 /box）用 VITE_API_BASE=/box/api 覆盖。
  baseURL: import.meta.env.VITE_API_BASE || '/api',
  withCredentials: true,
  timeout: 30_000,
})

http.interceptors.response.use(
  (response: AxiosResponse<ApiEnvelope<unknown>>) => {
    const envelope = response.data
    if (isEnvelope(envelope)) {
      if (envelope.code !== 0) {
        throw new ApiError(envelope.msg || '请求失败', envelope.code, response.status)
      }
      response.data = envelope.data as never
    }
    return response
  },
  (error: AxiosError) => {
    const status = error.response?.status ?? 0
    const body = error.response?.data
    if (isEnvelope(body)) {
      return Promise.reject(new ApiError(body.msg || '请求失败', body.code, status))
    }
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return Promise.reject(new ApiError('请求超时，请稍后重试。', status || 408, status))
    }
    if (!error.response) {
      return Promise.reject(new ApiError('网络连接失败，请检查网络后重试。', 0, 0))
    }
    return Promise.reject(new ApiError(`服务请求失败（${status}），请稍后重试。`, status, status))
  },
)

export type RequestConfig = AxiosRequestConfig
