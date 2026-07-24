import React, { useMemo } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useAuth, type MenuItem } from "@/context/AuthContext"
import { useSidebar } from "./SidebarContext"
import { cn } from "@/lib/utils"
import {
  LayoutDashboard,
  FolderOpen,
  MessageSquare,
  Tags,
  LogOut,
  Settings,
  Shield,
  ShieldCheck,
  Users,
  Zap,
  X,
  Sparkles,
  BookOpen,
  Clock,
  BarChart3,
  ChevronRight,
  ChevronDown,
  SlidersHorizontal,
  Bot,
  type LucideIcon,
} from "lucide-react"

// Icon 名称到组件的映射（后端 menus.icon 字段使用这些名称）
const iconMap: Record<string, LucideIcon> = {
  LayoutDashboard,
  FolderOpen,
  MessageSquare,
  Tags,
  Sparkles,
  Settings,
  Shield,
  ShieldCheck,
  Users,
  BookOpen,
  Clock,
  BarChart3,
  ChevronRight,
  ChevronDown,
  SlidersHorizontal,
  Bot,
}

function getIcon(name?: string | null): LucideIcon {
  if (!name) return LayoutDashboard
  return iconMap[name] || LayoutDashboard
}

export default function AppNavbar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout, menus } = useAuth()
  const { collapsed, isMobile, mobileOpen, setMobileOpen } = useSidebar()

  // 兜底默认菜单：当数据库为空（新部署）时，确保系统管理页面始终可访问
  const defaultMenus: MenuItem[] = [
    { id: "default-dashboard", code: "dashboard", name: "仪表盘", type: "menu", path: "/", icon: "LayoutDashboard", sort_order: 1, hidden: false },
    { id: "default-kb", code: "knowledge_base", name: "文档中心", type: "menu", path: "/knowledge-base", icon: "FolderOpen", sort_order: 2, hidden: false },
    { id: "default-chat", code: "chat", name: "智能对话", type: "menu", path: "/chat", icon: "MessageSquare", sort_order: 3, hidden: false },
    { id: "default-category", code: "category", name: "分类管理", type: "menu", path: "/category", icon: "Tags", sort_order: 4, hidden: false },
    { id: "default-prompt", code: "prompt_market", name: "Prompt 市场", type: "menu", path: "/prompt-market", icon: "Sparkles", sort_order: 5, hidden: false },
    { id: "default-bi", code: "data_analysis", name: "数据分析", type: "menu", path: "/data-analysis", icon: "BarChart3", sort_order: 7, hidden: false },
    { id: "default-profile", code: "profile", name: "个人设置", type: "menu", path: "/profile", icon: "Settings", sort_order: 10, hidden: false },
    { id: "default-audit", code: "audit_log", name: "审计日志", type: "menu", path: "/audit-log", icon: "Clock", sort_order: 11, hidden: false },
    { id: "default-users", code: "user_manage", name: "用户管理", type: "menu", path: "/users", icon: "Users", sort_order: 12, hidden: false },
    { id: "default-roles", code: "role_manage", name: "角色权限", type: "menu", path: "/roles", icon: "ShieldCheck", sort_order: 13, hidden: false },
    { id: "default-menu", code: "menu_manage", name: "菜单管理", type: "menu", path: "/menu-manage", icon: "BookOpen", sort_order: 14, hidden: false },
    {
      id: "default-config-center", code: "menu-config-center", name: "配置中心", type: "menu", path: null, icon: "Settings", sort_order: 15, hidden: false,
      children: [
        { id: "default-model-config", code: "menu-model-config", name: "模型配置", type: "menu", path: "/model-config", icon: "Bot", sort_order: 1, hidden: false },
        { id: "default-parse", code: "parse_strategies", name: "解析策略", type: "menu", path: "/parse-strategies", icon: "BookOpen", sort_order: 2, hidden: false },
        { id: "default-retrieval", code: "menu-retrieval-config", name: "检索配置", type: "menu", path: "/retrieval-config", icon: "SlidersHorizontal", sort_order: 3, hidden: false },
      ],
    },
  ]

  // 优先使用后端返回的菜单树；如果为空或异常，使用兜底菜单
  const effectiveMenus = useMemo(() => {
    if (Array.isArray(menus) && menus.length > 0) return menus
    return defaultMenus
  }, [menus])

  // 保持树形结构，按顶层 sort_order 分组（<10 工作区，>=10 系统）
  const workMenus = useMemo(
    () => effectiveMenus.filter((m) => (m.sort_order ?? 0) < 10 && !m.hidden),
    [effectiveMenus]
  )
  const systemMenus = useMemo(
    () => effectiveMenus.filter((m) => (m.sort_order ?? 0) >= 10 && !m.hidden),
    [effectiveMenus]
  )

  const isActive = (path?: string | null) => {
    if (!path) return false
    if (path === "/") return location.pathname === "/"
    return location.pathname.startsWith(path)
  }

  const avatarUrl = user?.avatar_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=${user?.username || "guest"}`
  const displayName = user?.username || "Guest"

  // 移动端抽屉遮罩
  if (isMobile) {
    if (!mobileOpen) return null
    return (
      <>
        <div
          className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40"
          onClick={() => setMobileOpen(false)}
        />
        <aside className="fixed left-0 top-0 bottom-0 w-[260px] bg-white border-r border-[#e7e5e4] flex flex-col z-50 shadow-xl">
          <SidebarContent
            collapsed={false}
            isActive={isActive}
            navigate={(p) => { navigate(p); setMobileOpen(false) }}
            avatarUrl={avatarUrl}
            displayName={displayName}
            user={user}
            logout={logout}
            workMenus={workMenus}
            systemMenus={systemMenus}
            onClose={() => setMobileOpen(false)}
          />
        </aside>
      </>
    )
  }

  // 桌面端侧边栏
  return (
    <aside
      className={cn(
        "shrink-0 bg-white border-r border-[#e7e5e4] flex flex-col h-full transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
        collapsed ? "w-[72px]" : "w-[260px]"
      )}
    >
      <SidebarContent
        collapsed={collapsed}
        isActive={isActive}
        navigate={navigate}
        avatarUrl={avatarUrl}
        displayName={displayName}
        user={user}
        logout={logout}
        workMenus={workMenus}
        systemMenus={systemMenus}
      />
    </aside>
  )
}

// ============================================================================
// Sidebar Content (shared between desktop & mobile)
// ============================================================================

function NavItem({
  item,
  collapsed,
  isActive,
  navigate,
  depth = 0,
}: {
  item: MenuItem
  collapsed: boolean
  isActive: (path?: string | null) => boolean
  navigate: (path: string) => void
  depth?: number
}) {
  const active = isActive(item.path)
  const Icon = getIcon(item.icon)
  const hasChildren = item.children && item.children.length > 0
  // 子菜单命中当前路由时默认展开，避免激活项被折叠隐藏
  const [expanded, setExpanded] = React.useState(
    () => item.children?.some((child) => isActive(child.path)) ?? false
  )

  return (
    <>
      <button
        onClick={() => {
          if (hasChildren && !collapsed) {
            setExpanded(!expanded)
          } else if (item.path) {
            navigate(item.path)
          }
        }}
        title={collapsed ? item.name : undefined}
        className={cn(
          "w-full flex items-center gap-3 rounded-xl text-sm font-medium transition-all relative",
          collapsed ? "justify-center px-0 py-3" : "px-3 py-2.5",
          active
            ? "bg-accent text-[#1e40af]"
            : "text-[#57534e] hover:bg-[#f5f5f4] hover:text-[#292524]"
        )}
        style={{ paddingLeft: collapsed ? undefined : `${12 + depth * 16}px` }}
      >
        <Icon className={cn("size-4 flex-shrink-0", active ? "text-primary" : "text-[#a8a29e]")} />
        {!collapsed && (
          <>
            <span className="truncate flex-1 text-left">{item.name}</span>
            {hasChildren && (
              <span className="text-[#a8a29e]">
                {expanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              </span>
            )}
            {active && !hasChildren && (
              <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary breathe-effect flex-shrink-0" />
            )}
          </>
        )}
        {collapsed && active && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 w-1 h-4 rounded-full bg-primary" />
        )}
      </button>
      {hasChildren && expanded && !collapsed && (
        <div className="space-y-0.5">
          {item.children!.map((child) => (
            <NavItem
              key={child.id}
              item={child}
              collapsed={collapsed}
              isActive={isActive}
              navigate={navigate}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </>
  )
}

function SidebarContent({
  collapsed,
  isActive,
  navigate,
  avatarUrl,
  displayName,
  user,
  logout,
  workMenus,
  systemMenus,
  onClose,
}: {
  collapsed: boolean
  isActive: (path?: string | null) => boolean
  navigate: (path: string) => void
  avatarUrl: string
  displayName: string
  user: any
  logout: () => void
  workMenus: MenuItem[]
  systemMenus: MenuItem[]
  onClose?: () => void
}) {
  return (
    <>
      {/* Logo */}
      <div className={cn("border-b border-[#f5f5f4] flex items-center", collapsed ? "px-3 py-5 justify-center" : "px-6 py-5")}>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary to-[#1e40af] flex items-center justify-center shadow-[0_0_20px_rgba(37,99,235,0.15)] flex-shrink-0">
            <Zap className="size-4 text-white" />
          </div>
          {!collapsed && (
            <div>
              <h1 className="text-base font-bold text-[#292524] tracking-tight leading-none">Aura AI</h1>
              <p className="text-[11px] text-[#a8a29e] mt-0.5 tracking-widest uppercase">Enterprise</p>
            </div>
          )}
        </div>
        {onClose && (
          <button onClick={onClose} className="ml-auto w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-colors">
            <X className="size-4" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-5 space-y-1 overflow-y-auto overflow-x-hidden">
        {workMenus.length > 0 && !collapsed && (
          <p className="px-3 text-[11px] font-semibold text-[#a8a29e] uppercase tracking-wider mb-3">工作区</p>
        )}
        {workMenus.map((item) => (
          <NavItem key={item.id} item={item} collapsed={collapsed} isActive={isActive} navigate={navigate} />
        ))}

        {systemMenus.length > 0 && !collapsed && (
          <p className="px-3 text-[11px] font-semibold text-[#a8a29e] uppercase tracking-wider mt-6 mb-3">系统</p>
        )}
        {systemMenus.map((item) => (
          <NavItem key={item.id} item={item} collapsed={collapsed} isActive={isActive} navigate={navigate} />
        ))}
      </nav>

      {/* User */}
      <div className={cn("border-t border-[#f5f5f4]", collapsed ? "p-3 flex justify-center" : "p-4")}>
        <div
          className={cn(
            "rounded-xl hover:bg-[#f5f5f4] cursor-pointer transition-colors group",
            collapsed ? "p-2" : "flex items-center gap-3 p-2"
          )}
          title={collapsed ? displayName : undefined}
        >
          <img
            src={avatarUrl}
            alt={displayName}
            className="w-9 h-9 rounded-full object-cover border border-[#e7e5e4] flex-shrink-0"
          />
          {!collapsed && (
            <>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[#44403c] truncate">{displayName}</p>
                <p className="text-xs text-[#a8a29e] truncate">{user?.email || "User"}</p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  logout()
                }}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg hover:bg-[#e7e5e4] text-[#a8a29e] hover:text-destructive"
                title="退出登录"
              >
                <LogOut className="size-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    </>
  )
}
