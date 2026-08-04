import { useLocation, useNavigate } from "react-router-dom"
import { cn } from "@/lib/utils"
import { useSidebar } from "./SidebarContext"
import {
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Bell,
  Home,
  ChevronRight,
} from "lucide-react"

const pathMap: Record<string, { label: string; parent?: string }> = {
  "/": { label: "仪表盘" },
  "/knowledge-base": { label: "文档中心" },
  "/chat": { label: "智能对话" },
  "/category": { label: "分类管理" },
  "/profile": { label: "个人设置" },
  "/llm-config": { label: "模型配置", parent: "/profile" },
  "/config-center": { label: "配置中心" },
  "/model-config": { label: "模型配置", parent: "/config-center" },
  "/parse-strategies": { label: "解析策略", parent: "/config-center" },
  "/retrieval-config": { label: "检索配置", parent: "/config-center" },
  "/mcp-config": { label: "MCP 工具", parent: "/config-center" },
}

export default function PageHeader({ className }: { className?: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { collapsed, toggle, isMobile, setMobileOpen } = useSidebar()

  const pathname = location.pathname
  const config = pathMap[pathname]

  const breadcrumbItems = [{ label: "首页", path: "/" }]
  if (config?.parent && pathMap[config.parent]) {
    breadcrumbItems.push({ label: pathMap[config.parent].label, path: config.parent })
  }
  if (config) {
    breadcrumbItems.push({ label: config.label, path: pathname })
  }

  return (
    <div className={cn("flex items-center justify-between mb-6", className)}>
      {/* 左侧：折叠按钮 + 面包屑 */}
      <div className="flex items-center gap-3 min-w-0">
        {/* 移动端汉堡菜单 */}
        {isMobile && (
          <button
            onClick={() => setMobileOpen(true)}
            className="w-9 h-9 rounded-xl flex items-center justify-center text-[#57534e] hover:bg-[#f5f5f4] transition-colors flex-shrink-0"
          >
            <Menu className="size-5" />
          </button>
        )}

        {/* 桌面端折叠按钮 */}
        {!isMobile && (
          <button
            onClick={toggle}
            title={collapsed ? "展开侧边栏" : "折叠侧边栏"}
            className="w-9 h-9 rounded-xl flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-colors flex-shrink-0"
          >
            {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          </button>
        )}

        {/* 面包屑 */}
        <nav className="flex items-center gap-1.5 text-xs text-[#a8a29e] min-w-0">
          {breadcrumbItems.map((item, idx) => (
            <div key={item.path} className="flex items-center gap-1.5">
              {idx > 0 && <ChevronRight className="size-3 flex-shrink-0" />}
              {idx === breadcrumbItems.length - 1 ? (
                <span className="font-medium text-[#292524] truncate">{item.label}</span>
              ) : (
                <button
                  onClick={() => navigate(item.path)}
                  className="hover:text-primary transition-colors flex items-center gap-1 flex-shrink-0"
                >
                  {idx === 0 && <Home className="size-3" />}
                  <span className="hidden sm:inline">{item.label}</span>
                </button>
              )}
            </div>
          ))}
        </nav>
      </div>

      {/* 右侧：仅保留通知（系统级公用） */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <button className="relative w-9 h-9 rounded-xl flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all">
          <Bell className="size-4" />
          <span className="absolute top-2 right-2.5 w-1.5 h-1.5 rounded-full bg-red-500 ring-2 ring-white" />
        </button>
      </div>
    </div>
  )
}
