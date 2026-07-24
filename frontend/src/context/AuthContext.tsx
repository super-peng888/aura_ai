/**
 * 认证状态管理
 *
 * 提供全局用户状态、登录、注册、登出能力。
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react"
import { toast } from "sonner"
import { api, setToken, clearToken } from "@/api/client"

export interface UserInfo {
  id: string
  username: string
  email?: string | null
  phone?: string | null
  avatar_url?: string | null
  role: string
  token_quota_monthly?: number
  token_used_monthly?: number
  token_reset_at?: string | null
  default_model_id?: string | null
  created_at: string
}

export interface PermissionItem {
  id: string
  code: string
  name: string
  description?: string | null
}

export interface MenuItem {
  id: string
  name: string
  code: string
  path?: string | null
  icon?: string | null
  type?: string
  parent_id?: string | null
  sort_order?: number
  hidden?: boolean
  children?: MenuItem[]
}

interface AuthContextType {
  user: UserInfo | null
  isLoading: boolean
  isAuthenticated: boolean
  permissions: string[]
  menus: MenuItem[]
  hasPermission: (code: string) => boolean
  login: (username: string, password: string) => Promise<void>
  register: (data: RegisterData) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

export interface RegisterData {
  username: string
  password: string
  email?: string
  phone?: string
}

const AuthContext = createContext<AuthContextType | null>(null)

const PERMISSIONS_KEY = "aura_permissions"
const MENUS_KEY = "aura_menus"

function loadPermissions(): string[] {
  try {
    const raw = localStorage.getItem(PERMISSIONS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function savePermissions(perms: string[]) {
  localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(perms))
}

function clearPermissions() {
  localStorage.removeItem(PERMISSIONS_KEY)
}

function loadMenus(): MenuItem[] {
  try {
    const raw = localStorage.getItem(MENUS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveMenus(menus: MenuItem[]) {
  localStorage.setItem(MENUS_KEY, JSON.stringify(menus))
}

function clearMenus() {
  localStorage.removeItem(MENUS_KEY)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [permissions, setPermissions] = useState<string[]>(loadPermissions)
  const [menus, setMenus] = useState<MenuItem[]>(loadMenus)
  const [isLoading, setIsLoading] = useState(true)

  const isAuthenticated = !!user

  const hasPermission = useCallback((code: string) => {
    // admin 拥有全部权限
    if (user?.role === "admin") return true
    return permissions.includes(code)
  }, [user, permissions])

  const refreshPermissions = useCallback(async () => {
    try {
      const res = await api.get<PermissionItem[]>("/auth/permissions")
      const codes = (res || []).map((p) => p.code)
      setPermissions(codes)
      savePermissions(codes)
    } catch {
      setPermissions([])
      clearPermissions()
    }
  }, [])

  const refreshMenus = useCallback(async () => {
    try {
      const res = await api.get<MenuItem[]>("/auth/menus")
      const tree = Array.isArray(res) ? res : []
      setMenus(tree)
      saveMenus(tree)
    } catch {
      setMenus([])
      clearMenus()
    }
  }, [])

  const refreshUser = useCallback(async () => {
    try {
      const res = await api.get<UserInfo>("/auth/me")
      setUser(res)
      // 使用 allSettled 避免权限/菜单任一接口失败导致整体中断
      await Promise.allSettled([refreshPermissions(), refreshMenus()])
    } catch (err) {
      setUser(null)
      clearToken()
      clearPermissions()
      clearMenus()
    }
  }, [refreshPermissions, refreshMenus])

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api.post<{
        access_token: string; expires_in: number
      }>("/auth/login", { username, password })
      setToken(res.access_token)
      await refreshUser()
      toast.success("登录成功")
    },
    [refreshUser]
  )

  const register = useCallback(
    async (data: RegisterData) => {
      await api.post("/auth/register", data)
      toast.success("注册成功，请登录")
    },
    []
  )

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
    clearPermissions()
    setPermissions([])
    clearMenus()
    setMenus([])
    toast.info("已退出登录")
    window.location.href = "/login"
  }, [])

  // 初始化：检查本地 token 并自动获取用户信息
  useEffect(() => {
    const init = async () => {
      const token = localStorage.getItem("aura_token")
      if (token) {
        await refreshUser()
      }
      setIsLoading(false)
    }
    init()
  }, [refreshUser])

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated,
        permissions,
        menus,
        hasPermission,
        login,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
