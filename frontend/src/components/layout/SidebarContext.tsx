import { createContext, useContext, useState, useEffect, useCallback } from "react"
import { useLocation } from "react-router-dom"

interface SidebarContextValue {
  collapsed: boolean
  setCollapsed: (v: boolean) => void
  toggle: () => void
  isMobile: boolean
  mobileOpen: boolean
  setMobileOpen: (v: boolean) => void
}

const SidebarContext = createContext<SidebarContextValue | null>(null)

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const location = useLocation()

  // 桌面端折叠状态（持久化到 localStorage）
  const [collapsed, setCollapsedState] = useState(() => {
    const saved = localStorage.getItem("aura_sidebar_collapsed")
    return saved ? saved === "true" : false
  })

  // 移动端抽屉状态
  const [isMobile, setIsMobile] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  const setCollapsed = useCallback((v: boolean) => {
    setCollapsedState(v)
    localStorage.setItem("aura_sidebar_collapsed", String(v))
  }, [])

  const toggle = useCallback(() => {
    setCollapsedState((prev) => {
      const next = !prev
      localStorage.setItem("aura_sidebar_collapsed", String(next))
      return next
    })
  }, [])

  // 响应式检测
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 1024)
    check()
    window.addEventListener("resize", check)
    return () => window.removeEventListener("resize", check)
  }, [])

  return (
    <SidebarContext.Provider value={{ collapsed, setCollapsed, toggle, isMobile, mobileOpen, setMobileOpen }}>
      {children}
    </SidebarContext.Provider>
  )
}

export function useSidebar() {
  const ctx = useContext(SidebarContext)
  if (!ctx) throw new Error("useSidebar must be used within SidebarProvider")
  return ctx
}
