import { useState, useEffect, useCallback } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import PageHeader from "@/components/layout/PageHeader"
import {
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  FileText,
  Plus,
  Edit3,
  Trash2,
  Search,
  Loader2,
} from "lucide-react"
import { categoryApi, type CategoryTreeNode, type DocumentItem } from "@/api/category"
import { toast } from "sonner"

function CategoryNode({
  node,
  selectedId,
  onSelect,
  expandedIds,
  onToggle,
  level = 0,
}: {
  node: CategoryTreeNode
  selectedId: string | null
  onSelect: (id: string) => void
  expandedIds: Set<string>
  onToggle: (id: string) => void
  level?: number
}) {
  const isExpanded = expandedIds.has(node.id)
  const isSelected = selectedId === node.id
  const hasChildren = node.children && node.children.length > 0
  const indent = level * 16

  return (
    <div>
      <button
        onClick={() => onSelect(node.id)}
        className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-left transition-all duration-200 ${
          isSelected
            ? "bg-primary/10 text-primary font-semibold border border-primary/15"
            : "text-foreground hover:bg-[#f5f5f4]"
        }`}
        style={{ paddingLeft: `${12 + indent}px` }}
      >
        {hasChildren ? (
          <button
            onClick={(e) => { e.stopPropagation(); onToggle(node.id) }}
            className="p-0.5 rounded hover:bg-[#f5f5f4] transition-colors shrink-0"
          >
            {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <div
          className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
            isSelected ? "bg-primary/10" : "bg-secondary/10"
          }`}
        >
          {isExpanded ? (
            <FolderOpen
              className="size-4"
              style={{ color: isSelected ? "#2563eb" : "#57534e" }}
            />
          ) : (
            <Folder
              className="size-4"
              style={{ color: isSelected ? "#2563eb" : "#57534e" }}
            />
          )}
        </div>
        <span className="text-sm flex-1 truncate">{node.name}</span>
        <span className="text-[10px] font-bold text-muted-foreground bg-[#f5f5f4] px-2 py-0.5 rounded-full shrink-0">
          {node.doc_count}
        </span>
      </button>
      {hasChildren && isExpanded && (
        <div className="mt-0.5">
          {node.children.map((child) => (
            <CategoryNode
              key={child.id}
              node={child}
              selectedId={selectedId}
              onSelect={onSelect}
              expandedIds={expandedIds}
              onToggle={onToggle}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) return "今天"
  if (days === 1) return "昨天"
  if (days < 7) return `${days}天前`
  if (days < 30) return `${Math.floor(days / 7)}周前`
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export default function CategoryManage() {
  const [categories, setCategories] = useState<CategoryTreeNode[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)

  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [docLoading, setDocLoading] = useState(false)
  const [docTotal, setDocTotal] = useState(0)

  const [showDialog, setShowDialog] = useState(false)
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create")
  const [editId, setEditId] = useState<string | null>(null)
  const [formName, setFormName] = useState("")
  const [formDescription, setFormDescription] = useState("")
  const [formParentId, setFormParentId] = useState<string>("")
  const [dialogLoading, setDialogLoading] = useState(false)

  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [deleteMoveToId, setDeleteMoveToId] = useState<string>("")
  const [deleteLoading, setDeleteLoading] = useState(false)

  // 加载分类树
  const loadCategories = useCallback(async () => {
    setLoading(true)
    try {
      const tree = await categoryApi.getTree()
      setCategories(tree)
      // 默认展开所有根分类
      const rootIds = new Set(tree.map((c) => c.id))
      setExpandedIds(rootIds)
      // 默认选中第一个
      if (tree.length > 0 && !selectedId) {
        setSelectedId(tree[0].id)
      }
    } catch {
      toast.error("加载分类失败")
    } finally {
      setLoading(false)
    }
  }, [selectedId])

  useEffect(() => {
    loadCategories()
  }, [loadCategories])

  // 选中分类时加载文档
  useEffect(() => {
    if (!selectedId) {
      setDocuments([])
      return
    }
    setDocLoading(true)
    categoryApi
      .getDocuments(selectedId)
      .then((res) => {
        setDocuments(res.items)
        setDocTotal(res.total)
      })
      .catch(() => toast.error("加载文档失败"))
      .finally(() => setDocLoading(false))
  }, [selectedId])

  const toggleExpand = (id: string) => {
    const next = new Set(expandedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpandedIds(next)
  }

  const openCreateDialog = () => {
    setDialogMode("create")
    setEditId(null)
    setFormName("")
    setFormDescription("")
    setFormParentId(selectedId || "")
    setShowDialog(true)
  }

  const openEditDialog = (cat: CategoryTreeNode) => {
    setDialogMode("edit")
    setEditId(cat.id)
    setFormName(cat.name)
    setFormDescription(cat.description || "")
    setFormParentId(cat.parent_id || "")
    setShowDialog(true)
  }

  const handleDialogSubmit = async () => {
    if (!formName.trim()) {
      toast.error("请输入分类名称")
      return
    }
    setDialogLoading(true)
    try {
      const payload = {
        name: formName.trim(),
        description: formDescription.trim() || undefined,
        parent_id: formParentId || undefined,
      }
      if (dialogMode === "create") {
        await categoryApi.create(payload)
        toast.success("分类创建成功")
      } else if (editId) {
        await categoryApi.update(editId, payload)
        toast.success("分类更新成功")
      }
      setShowDialog(false)
      loadCategories()
    } catch {
      toast.error(dialogMode === "create" ? "创建分类失败" : "更新分类失败")
    } finally {
      setDialogLoading(false)
    }
  }

  const openDeleteDialog = (id: string) => {
    setDeleteId(id)
    setDeleteMoveToId("")
    setShowDeleteDialog(true)
  }

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleteLoading(true)
    try {
      const moveTo = deleteMoveToId || undefined
      await categoryApi.delete(deleteId, moveTo)
      toast.success("分类删除成功")
      setShowDeleteDialog(false)
      if (selectedId === deleteId) setSelectedId(null)
      loadCategories()
    } catch {
      toast.error("删除分类失败")
    } finally {
      setDeleteLoading(false)
    }
  }

  // 收集所有分类用于 Parent 下拉选择
  const flattenCategories = (nodes: CategoryTreeNode[]): CategoryTreeNode[] => {
    const result: CategoryTreeNode[] = []
    const walk = (list: CategoryTreeNode[]) => {
      for (const n of list) {
        result.push(n)
        if (n.children) walk(n.children)
      }
    }
    walk(nodes)
    return result
  }

  const allCategories = flattenCategories(categories)
  const selectedCategory = allCategories.find((c) => c.id === selectedId)

  // 统计
  const totalCategories = allCategories.length
  const rootCount = categories.length

  return (
    <div className="space-y-6">
      <PageHeader />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Category Tree */}
        <Card className="glass-card rounded-[10px] border-[#e7e5e4] p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-foreground">分类管理</h3>
            <Button
              size="sm"
              className="btn-primary-gradient rounded-full h-8 px-3"
              onClick={openCreateDialog}
            >
              <Plus className="size-4" />
            </Button>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-6 animate-spin text-primary" />
            </div>
          ) : categories.length === 0 ? (
            <div className="text-center py-12 text-sm text-muted-foreground">
              暂无分类，点击右上角创建
            </div>
          ) : (
            <div className="space-y-1">
              {categories.map((cat) => (
                <CategoryNode
                  key={cat.id}
                  node={cat}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  expandedIds={expandedIds}
                  onToggle={toggleExpand}
                />
              ))}
            </div>
          )}
        </Card>

        {/* Document List */}
        <Card className="lg:col-span-2 glass-card rounded-[10px] border-[#e7e5e4]">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-foreground">
                {selectedCategory ? `${selectedCategory.name} 的文档` : "文档列表"}
              </h3>
              {selectedId && (
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 px-2"
                    onClick={() => openEditDialog(selectedCategory!)}
                  >
                    <Edit3 className="size-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 px-2 text-destructive hover:text-destructive"
                    onClick={() => openDeleteDialog(selectedId)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              )}
            </div>

            {docLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="size-6 animate-spin text-primary" />
              </div>
            ) : documents.length === 0 ? (
              <div className="text-center py-12 text-sm text-muted-foreground">
                {selectedId ? "该分类下暂无文档" : "请选择一个分类"}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#e7e5e4]">
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">名称</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">状态</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">大小</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">更新时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#f5f5f4]">
                    {documents.map((doc) => (
                      <tr key={doc.id} className="hover:bg-primary/[0.04] transition-colors">
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <FileText className="size-4 text-muted-foreground" />
                            <span className="text-sm text-foreground">{doc.original_name}</span>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <span
                            className={`chip-${
                              doc.parse_status === "completed"
                                ? "lime"
                                : doc.parse_status === "failed"
                                ? "red"
                                : doc.parse_status === "running"
                                ? "blue"
                                : "gray"
                            }`}
                          >
                            {doc.parse_status === "completed"
                              ? "已完成"
                              : doc.parse_status === "failed"
                              ? "失败"
                              : doc.parse_status === "running"
                              ? "解析中"
                              : "待处理"}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-sm text-muted-foreground">
                          {formatFileSize(doc.file_size)}
                        </td>
                        <td className="py-3 px-4 text-sm text-muted-foreground">
                          {formatDate(doc.updated_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {docTotal > documents.length && (
                  <div className="text-center py-3 text-xs text-muted-foreground">
                    共 {docTotal} 条，当前展示 {documents.length} 条
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Bottom Stats */}
      <div className="flex items-center gap-4 glass-card rounded-full px-6 py-3 border-[#e7e5e4]">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Folder className="size-4 text-primary" />
          <span>
            <strong className="text-foreground">{rootCount}</strong> 根分类
          </span>
        </div>
        <div className="w-px h-4 bg-[#f5f5f4]" />
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <FolderOpen className="size-4 text-secondary" />
          <span>
            <strong className="text-foreground">{totalCategories - rootCount}</strong> 子分类
          </span>
        </div>
        <div className="w-px h-4 bg-[#f5f5f4]" />
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <FileText className="size-4 text-tertiary" />
          <span>
            <strong className="text-foreground">{docTotal}</strong> 文档
          </span>
        </div>
      </div>

      {/* Create / Edit Dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="glass-card-strong rounded-[10px] border-[#e7e5e4]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Folder className="size-5 text-primary" />
              {dialogMode === "create" ? "新建分类" : "编辑分类"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <label className="text-sm font-medium text-foreground mb-1.5 block">名称</label>
              <input
                type="text"
                placeholder="分类名称"
                className="input-pill"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-foreground mb-1.5 block">描述</label>
              <input
                type="text"
                placeholder="分类描述（可选）"
                className="input-pill"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-foreground mb-1.5 block">父分类</label>
              <select
                className="input-pill appearance-none bg-white"
                value={formParentId}
                onChange={(e) => setFormParentId(e.target.value)}
              >
                <option value="">无（根分类）</option>
                {allCategories
                  .filter((c) => c.id !== editId) // 不能选自己作为父分类
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {"  ".repeat(c.parent_id ? 2 : 0)}{c.name}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          <DialogFooter className="border-t border-[#e7e5e4] pt-4">
            <Button variant="ghost" onClick={() => setShowDialog(false)}>
              取消
            </Button>
            <Button
              className="btn-primary-gradient rounded-full"
              onClick={handleDialogSubmit}
              disabled={dialogLoading}
            >
              {dialogLoading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : dialogMode === "create" ? (
                "创建"
              ) : (
                "保存"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent className="glass-card-strong rounded-[10px] border-[#e7e5e4]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <Trash2 className="size-5" />
              删除分类
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <p className="text-sm text-muted-foreground">
              删除分类后，该分类下的文档可以移动到其他分类，或保留为未分类。
            </p>
            <div>
              <label className="text-sm font-medium text-foreground mb-1.5 block">
                移动文档到
              </label>
              <select
                className="input-pill appearance-none bg-white"
                value={deleteMoveToId}
                onChange={(e) => setDeleteMoveToId(e.target.value)}
              >
                <option value="">不移动（设为未分类）</option>
                {allCategories
                  .filter((c) => c.id !== deleteId)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          <DialogFooter className="border-t border-[#e7e5e4] pt-4">
            <Button variant="ghost" onClick={() => setShowDeleteDialog(false)}>
              取消
            </Button>
            <Button
              variant="destructive"
              className="rounded-full"
              onClick={handleDelete}
              disabled={deleteLoading}
            >
              {deleteLoading ? <Loader2 className="size-4 animate-spin" /> : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
