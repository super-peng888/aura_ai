/**
 * HTTP 客户端封装（基于 Axios）
 *
 * 统一处理 baseURL、Token 注入、错误拦截、SSE 流式请求。
 */

import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
} from "axios"
import { toast } from "sonner"

const TOKEN_KEY = "aura_token"

function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// ============================================================================
// Axios 实例
// ============================================================================

class HttpClient {
  private instance: AxiosInstance

  constructor() {
    this.instance = axios.create({
      baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
      timeout: 30000,
      headers: {
        "Content-Type": "application/json",
      },
    })

    this.setupInterceptors()
  }

  private setupInterceptors() {
    // 请求拦截器：注入 Token
    this.instance.interceptors.request.use(
      (config) => {
        const token = getToken()
        if (token && config.headers) {
          config.headers.Authorization = `Bearer ${token}`
        }
        return config
      },
      (error) => {
        return Promise.reject(error)
      }
    )

    // 响应拦截器：统一错误处理
    this.instance.interceptors.response.use(
      (response: AxiosResponse) => {
        // 后端统一返回 BaseResponse { code, message, data }
        const data = response.data
        if (data && typeof data === "object" && "code" in data && data.code !== 0) {
          const message = data.message || "请求失败"
          toast.error(message)
          return Promise.reject(new Error(message))
        }
        return response
      },
      (error) => {
        if (axios.isCancel(error)) {
          return Promise.reject(error)
        }

        // 处理 401 未授权
        if (error.response?.status === 401) {
          clearToken()
          toast.error("登录已过期，请重新登录")
          window.location.href = "/login"
          return Promise.reject(new Error("登录已过期"))
        }

        // 其他错误
        const message =
          error.response?.data?.message ||
          error.response?.data?.detail ||
          error.message ||
          "网络请求失败"
        toast.error(message)
        return Promise.reject(new Error(message))
      }
    )
  }

  get<T>(url: string, config?: AxiosRequestConfig) {
    return this.instance.get<T, AxiosResponse<T>>(url, config)
  }

  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
    return this.instance.post<T, AxiosResponse<T>>(url, data, config)
  }

  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
    return this.instance.put<T, AxiosResponse<T>>(url, data, config)
  }

  delete<T>(url: string, config?: AxiosRequestConfig) {
    return this.instance.delete<T, AxiosResponse<T>>(url, config)
  }

  getAxiosInstance() {
    return this.instance
  }
}

const httpClient = new HttpClient()

/**
 * 封装后的 API 方法
 *
 * 自动解包后端 BaseResponse 的 data 字段，直接返回业务数据。
 */
function unwrap<T>(res: any): T {
  if (res && typeof res === "object" && "code" in res && "data" in res) {
    return res.data as T
  }
  return res as T
}

export const api = {
  get<T>(url: string, config?: AxiosRequestConfig) {
    return httpClient.get<T>(url, config).then((res) => unwrap<T>(res.data))
  },
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
    return httpClient.post<T>(url, data, config).then((res) => unwrap<T>(res.data))
  },
  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
    return httpClient.put<T>(url, data, config).then((res) => unwrap<T>(res.data))
  },
  delete<T>(url: string, config?: AxiosRequestConfig) {
    return httpClient.delete<T>(url, config).then((res) => unwrap<T>(res.data))
  },
}

// ============================================================================
// SSE 流式请求（原生 fetch，Axios 不支持 ReadableStream）
// ============================================================================

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1"

export async function fetchStream(
  path: string,
  body?: unknown
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const url = `${BASE_URL}${path}`
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  }
  const token = getToken()
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `请求失败: ${response.status}`)
  }

  if (!response.body) {
    throw new Error("响应体为空")
  }

  return response.body.getReader()
}

/**
 * SSE EventSource 解析器
 * 将 ReadableStream 解析为异步生成器，逐条产出 { event, data } 对象
 */
export async function* parseSSEStream(reader: ReadableStreamDefaultReader<Uint8Array>): AsyncGenerator<{ event: string; data: any }> {
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split("\n")
    buffer = lines.pop() || ""

    let currentEvent = "message"
    let currentData = ""

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim()
      } else if (line.startsWith("data:")) {
        currentData += line.slice(5).trim()
      } else if (line === "" && currentData) {
        try {
          yield { event: currentEvent, data: JSON.parse(currentData) }
        } catch {
          yield { event: currentEvent, data: currentData }
        }
        currentEvent = "message"
        currentData = ""
      }
    }
  }

  // 处理剩余 buffer
  if (buffer.trim()) {
    const lines = buffer.split("\n")
    let currentEvent = "message"
    let currentData = ""
    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim()
      } else if (line.startsWith("data:")) {
        currentData += line.slice(5).trim()
      }
    }
    if (currentData) {
      try {
        yield { event: currentEvent, data: JSON.parse(currentData) }
      } catch {
        yield { event: currentEvent, data: currentData }
      }
    }
  }
}
