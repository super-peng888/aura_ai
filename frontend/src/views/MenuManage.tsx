import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { api } from "@/api/client"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import PageHeader from "@/components/layout/PageHeader"
import {
  Plus,
  Trash2,
  Pencil,
  Eye,
  EyeOff,
  FolderOpen,
  LayoutDashboard,
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
  Loader2,
  GripVertical,
} from "lucide-react"

interface PermissionNode {
  id: string
  code: string
  name: string
  description?: string
  type: "menu" | "api" | "button"
  path?: string
  icon?: string
  parent_id?: string
  sort_order: number
  hidden: boolean
  created_at: string
  children?: PermissionNode[]
}

const iconMap: Record<string, React.ElementType> = {
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
  GripVertical,
}

function getIcon(name?: string | null) {
  if (!name) return FolderOpen
  return iconMap[name] || FolderOpen
}

export default function MenuManage() {
  const [tree, setTree] = useState<PermissionNode[]>([])
  const [flatList, setFlatList] = useState<PermissionNode[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showDialog, setShowDialog] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const [form, setForm] = useState({
    code: "",
    name: "",
    description: "",
    type: "menu" as "menu" | "api" | "button",
    path: "",
    icon: "",
    parent_id: "",
    sort_order: 0,
    hidden: false,
  })

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setIsLoading(true)
    try {
      const treeRes = await api.get<PermissionNode[]>("/roles/permissions/tree")
      const flatRes = await api.get<PermissionNode[]>("/roles/permissions/all")
      setTree(treeRes || [])
      setFlatList(flatRes || [])
    } catch {
      toast.error("加载菜单数据失败")
    } finally {
      setIsLoading(false)
    }
  }

  const openCreate = (parentId?: string) => {
    setEditingId(null)
    setForm({
      code: "",
      name: "",
      description: "",
      type: "menu",
      path: "",
      icon: "",
      parent_id: parentId || "",
      sort_order: 0,
      hidden: false,
    })
    setShowDialog(true)
  }

  const openEdit = (node: PermissionNode) => {
    setEditingId(node.id)
    setForm({
      code: node.code,
      name: node.name,
      description: node.description || "",
      type: node.type,
      path: node.path || "",
      icon: node.icon || "",
      parent_id: node.parent_id || "",
      sort_order: node.sort_order,
      hidden: node.hidden,
    })
    setShowDialog(true)
  }

  const handleSave = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      toast.error("请填写编码和名称")
      return
    }
    try {
      const payload = { ...form, parent_id: form.parent_id || undefined }
      if (editingId) {
        await api.put(`/roles/permissions/${editingId}`, payload)
        toast.success("菜单已更新")
      } else {
        await api.post("/roles/permissions", payload)
        toast.success("菜单已创建")
      }
      setShowDialog(false)
      loadData()
    } catch (err: any) {
      toast.error(err.message || "保存失败")
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除该权限吗？若有子权限将无法删除。")) return
    try {
      await api.delete(`/roles/permissions/${id}`)
      toast.success("已删除")
      loadData()
    } catch (err: any) {
      toast.error(err.message || "删除失败")
    }
  }

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const n = new Set(prev)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  const menuOptions = flatList.filter((p) => p.type === "menu")

  const typeLabel = (t: string) =>
    ({ menu: "菜单", api: "接口", button: "按钮" }[t] || t)

  const typeStyle = (t: string) =>
    ({
      menu: "bg-blue-50 text-blue-600 border-blue-100",
      api: "bg-emerald-50 text-emerald-600 border-emerald-100",
      button: "bg-amber-50 text-amber-600 border-amber-100",
    }[t] || "bg-[#f5f5f4] text-[#57534e] border-[#e7e5e4]")

  const renderTree = (nodes: PermissionNode[], depth = 0) => {
    return nodes.map((node) => {
      const Icon = getIcon(node.icon)
      const hasChildren = node.children && node.children.length > 0
      const isExpanded = expandedIds.has(node.id)

      return (
        <div key={node.id}>
          <div
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 border-b border-[#f5f5f4] hover:bg-[#fafaf9] transition-colors",
              depth > 0 && "bg-[#fafaf9]/50"
            )}
            style={{ paddingLeft: `${16 + depth * 28}px` }}
          >
            {hasChildren ? (
              <button
                onClick={() => toggleExpand(node.id)}
                className="w-5 h-5 rounded flex items-center justify-center text-[#a8a29e] hover:text-[#57534e] hover:bg-[#e7e5e4] transition-all"
              >
                {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              </button>
            ) : (
              <span className="w-5" />
            )}

            <Icon className={cn("size-4 flex-shrink-0", node.hidden ? "text-[#d6d3d1]" : "text-primary")} />

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={cn("text-sm font-medium truncate", node.hidden && "text-[#a8a29e] line-through")}>
                  {node.name}
                </span>
                <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium border", typeStyle(node.type))}>
                  {typeLabel(node.type)}
                </span>
                {node.hidden && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#f5f5f4] text-[#a8a29e] border border-[#e7e5e4] flex items-center gap-0.5">
                    <EyeOff className="size-3" />
                    隐藏
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3 mt-0.5">
                <span className="text-[10px] text-[#a8a29e]">{node.code}</span>
                {node.path && <span className="text-[10px] text-[#a8a29e]">{node.path}</span>}
                <span className="text-[10px] text-[#a8a29e]">排序 {node.sort_order}</span>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={() => openCreate(node.id)}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-primary/10 hover:text-primary transition-all"
                title="添加子项"
              >
                <Plus className="size-3.5" />
              </button>
              <button
                onClick={() => openEdit(node)}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#44403c] transition-all"
                title="编辑"
              >
                <Pencil className="size-3.5" />
              </button>
              <button
                onClick={() => handleDelete(node.id)}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
                title="删除"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          </div>
          {hasChildren && isExpanded && renderTree(node.children!, depth + 1)}
        </div>
      )
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader />

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#292524] tracking-tight">菜单管理</h2>
          <p className="text-sm text-[#a8a29e] mt-1">管理侧边栏菜单、API 权限和按钮权限</p>
        </div>
        <Button
          onClick={() => openCreate()}
          className="btn-primary-gradient rounded-xl px-4 flex items-center gap-2"
        >
          <Plus className="size-4" />
          新增权限
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-6 animate-spin text-primary" />
        </div>
      ) : tree.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
            <Shield className="size-8 text-[#a8a29e]" />
          </div>
          <h3 className="text-base font-semibold text-[#44403c] mb-1">暂无权限数据</h3>
          <Button onClick={() => openCreate()} className="btn-primary-gradient rounded-xl px-5 mt-4">
            <Plus className="size-4 mr-2" />
            新增权限
          </Button>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-[#e7e5e4] overflow-hidden">
          <div className="grid grid-cols-[auto_1fr_140px_80px_auto] gap-2 px-4 py-2.5 bg-[#fafaf9] border-b border-[#e7e5e4] text-[11px] font-semibold text-[#a8a29e] uppercase tracking-wider">
            <span className="w-5" />
            <span>名称 / 编码 / 路径</span>
            <span>类型</span>
            <span className="text-center">排序</span>
            <span className="text-right">操作</span>
          </div>
          {renderTree(tree)}
        </div>
      )}

      {/* Create / Edit Dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Shield className="size-5 text-primary" />
              {editingId ? "编辑权限" : "新增权限"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-[#44403c] mb-1.5 block">编码</label>
                <input
                  type="text"
                  value={form.code}
                  onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
                  placeholder="例如: menu-dashboard"
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-[#44403c] mb-1.5 block">名称</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="例如: 仪表盘"
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                />
              </div>
            </div>

            <div>
              <label className="text-sm font-medium text-[#44403c] mb-1.5 block">描述</label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="可选"
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-[#44403c] mb-1.5 block">类型</label>
                <select
                  value={form.type}
                  onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as any }))}
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
                >
                  <option value="menu">菜单</option>
                  <option value="api">接口</option>
                  <option value="button">按钮</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium text-[#44403c] mb-1.5 block">排序</label>
                <input
                  type="number"
                  min={0}
                  value={form.sort_order}
                  onChange={(e) => setForm((f) => ({ ...f, sort_order: Number(e.target.value) }))}
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                />
              </div>
            </div>

            {form.type === "menu" && (
              <>
                <div>
                  <label className="text-sm font-medium text-[#44403c] mb-1.5 block">路由路径</label>
                  <input
                    type="text"
                    value={form.path}
                    onChange={(e) => setForm((f) => ({ ...f, path: e.target.value }))}
                    placeholder="例如: /dashboard"
                    className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-[#44403c] mb-1.5 block">图标名称</label>
                  <select
                    value={form.icon}
                    onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
                  >
                    <option value="">不显示图标</option>
                    {Object.keys(iconMap).map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                </div>
              </>
            )}

            <div>
              <label className="text-sm font-medium text-[#44403c] mb-1.5 block">父级权限</label>
              <select
                value={form.parent_id}
                onChange={(e) => setForm((f) => ({ ...f, parent_id: e.target.value }))}
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
              >
                <option value="">无（顶级）</option>
                {menuOptions.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>

            <label className="flex items-center gap-2 text-sm text-[#44403c] cursor-pointer">
              <input
                type="checkbox"
                checked={form.hidden}
                onChange={(e) => setForm((f) => ({ ...f, hidden: e.target.checked }))}
                className="rounded border-[#d6d3d1] text-primary focus:ring-primary size-4"
              />
              隐藏（不在侧边栏显示）
            </label>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setShowDialog(false)}
              className="rounded-xl border-[#e7e5e4]"
            >
              取消
            </Button>
            <Button className="btn-primary-gradient rounded-xl" onClick={handleSave}>
              {editingId ? "保存修改" : "创建权限"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
