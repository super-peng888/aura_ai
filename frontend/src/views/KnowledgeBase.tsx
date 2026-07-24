import React, { useEffect, useState, useRef, useMemo } from "react"
import { useLocation } from "react-router-dom"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { api } from "@/api/client"
import { categoryApi, type CategoryTreeNode } from "@/api/category"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import PageHeader from "@/components/layout/PageHeader"
import {
  FileText,
  FileSpreadsheet,
  Image,
  FileCode,
  CheckCircle,
  AlertCircle,
  Clock,
  Plus,
  Search,
  Trash2,
  Upload,
  Loader2,
  Grid3X3,
  List,
  FileSearch,
  X,
  FolderOpen,
  Zap,
  Layers,
  Info,
  History,
  ChevronDown,
  ChevronUp,
  FlaskConical,
} from "lucide-react"

const tabs = ["全部", "PDF", "Word", "Excel", "其他"]

const typeIcons: Record<string, React.ElementType> = {
  pdf: FileText,
  docx: FileText,
  xlsx: FileSpreadsheet,
  png: Image,
  jpg: Image,
  md: FileCode,
  sql: FileCode,
  default: FileText,
}

const typeColors: Record<string, { bg: string; text: string }> = {
  pdf: { bg: "bg-red-50", text: "text-red-500" },
  docx: { bg: "bg-blue-50", text: "text-blue-500" },
  xlsx: { bg: "bg-emerald-50", text: "text-emerald-500" },
  png: { bg: "bg-purple-50", text: "text-purple-500" },
  jpg: { bg: "bg-purple-50", text: "text-purple-500" },
  md: { bg: "bg-surface-100", text: "text-[#57534e]" },
  sql: { bg: "bg-surface-100", text: "text-[#57534e]" },
  default: { bg: "bg-surface-100", text: "text-[#57534e]" },
}

type DocStatus = "pending" | "running" | "completed" | "failed"

interface DocumentItem {
  id: string
  filename: string
  original_name: string
  category_id?: string
  parse_status: DocStatus
  parse_mode?: string
  chunk_size?: number
  chunk_overlap?: number
  dimension?: number
  file_size: number
  updated_at: string
  mime_type?: string
  type?: string
}

// ========== 检索测试（POST /documents/search，与后端 SearchResponse 一致）==========
interface SearchResultItem {
  chunk_id: string
  document_id: string
  content: string
  page_number?: number | null
  score: number
  search_type: string
  image_ids?: string[]
}

interface SearchTestResponse {
  query: string
  rewritten_query?: string | null
  results: SearchResultItem[]
}

// 用户解析策略（/parse-strategies，用于上传与解析配置下拉）
interface ParseStrategyOption {
  id: string
  name: string
  parse_mode: string
  is_default: boolean
}

const statusConfig: Record<DocStatus, { label: string; style: string; icon: React.ElementType }> = {
  completed: {
    label: "已索引",
    style: "bg-emerald-50 text-emerald-600 border-emerald-100",
    icon: CheckCircle,
  },
  running: {
    label: "解析中",
    style: "bg-amber-50 text-amber-600 border-amber-100",
    icon: Loader2,
  },
  pending: {
    label: "待处理",
    style: "bg-[#f5f5f4] text-[#78716c] border-[#e7e5e4]",
    icon: Clock,
  },
  failed: {
    label: "解析失败",
    style: "bg-red-50 text-red-600 border-red-100",
    icon: AlertCircle,
  },
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

function getFileType(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() || ""
  if (["pdf"].includes(ext)) return "pdf"
  if (["doc", "docx"].includes(ext)) return "docx"
  if (["xls", "xlsx", "csv"].includes(ext)) return "xlsx"
  if (["png", "jpg", "jpeg", "gif"].includes(ext)) return "png"
  if (["md", "markdown"].includes(ext)) return "md"
  if (["sql"].includes(ext)) return "sql"
  return "default"
}

// 后端 mode_used 展示文案
const modeUsedLabels: Record<string, string> = {
  text: "纯文本",
  pymupdf: "PyMuPDF",
  paddleocr: "PaddleOCR",
  ocr: "PaddleOCR",
  vlm: "VLM 视觉理解",
}

// 内容中的图片占位符 [IMG:xxx] 显示为友好标记（图片缩略图单独回显）
function stripImgPlaceholders(content: string): string {
  return (content || "").replace(/\[IMG:[a-zA-Z0-9_]+\]/g, "[图片]")
}

export default function KnowledgeBase() {
  const [activeTab, setActiveTab] = useState("全部")
  const [showUploadDialog, setShowUploadDialog] = useState(false)
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [categories, setCategories] = useState<CategoryTreeNode[]>([])
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null)
  const [uploadCategoryId, setUploadCategoryId] = useState<string>("")
  const [showVersionDialog, setShowVersionDialog] = useState(false)
  const [versionDocId, setVersionDocId] = useState<string | null>(null)
  const [versions, setVersions] = useState<any[]>([])
  const [versionLoading, setVersionLoading] = useState(false)
  const [autoParse, setAutoParse] = useState<boolean>(true)
  // 分块预览
  const [showChunkPreview, setShowChunkPreview] = useState(false)
  const [previewDocId, setPreviewDocId] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<any>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  // 解析策略选择（上传 / 手动解析）
  const [parseStrategies, setParseStrategies] = useState<ParseStrategyOption[]>([])
  const [uploadStrategyId, setUploadStrategyId] = useState<string>("")
  // 解析配置对话框
  const [showParseConfig, setShowParseConfig] = useState(false)
  const [parseConfigDocId, setParseConfigDocId] = useState<string | null>(null)
  const [parseConfigStrategyId, setParseConfigStrategyId] = useState<string>("")
  const [showCustomParams, setShowCustomParams] = useState(false)
  const [pcParseMode, setPcParseMode] = useState("")
  const [pcChunkSize, setPcChunkSize] = useState("")
  const [pcChunkOverlap, setPcChunkOverlap] = useState("")
  const [pcSplitMethod, setPcSplitMethod] = useState("")
  const [pcExtractImages, setPcExtractImages] = useState("")
  const [isParseStarting, setIsParseStarting] = useState(false)
  // 抽屉内文档图片映射（image_ref_id / id -> oss_url）
  const [drawerImageMap, setDrawerImageMap] = useState<Record<string, string>>({})
  // 检索测试
  const [showSearchTest, setShowSearchTest] = useState(false)
  const [searchTestQuery, setSearchTestQuery] = useState("")
  const [searchTestTopK, setSearchTestTopK] = useState(10)
  const [searchTestLoading, setSearchTestLoading] = useState(false)
  const [searchTestResult, setSearchTestResult] = useState<SearchTestResponse | null>(null)
  const [expandedChunks, setExpandedChunks] = useState<Set<string>>(new Set())
  // 视图模式与批量操作
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid")
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [isBatchMode, setIsBatchMode] = useState(false)
  // 详情抽屉
  const [showDetailDrawer, setShowDetailDrawer] = useState(false)
  const [drawerDocId, setDrawerDocId] = useState<string | null>(null)
  const [drawerTab, setDrawerTab] = useState<"overview" | "chunks" | "versions">("overview")
  const [drawerLoading, setDrawerLoading] = useState(false)
  const [drawerDoc, setDrawerDoc] = useState<any>(null)
  const [drawerChunks, setDrawerChunks] = useState<any[]>([])
  const [drawerVersions, setDrawerVersions] = useState<any[]>([])
  // 拖拽上传
  const [isDragging, setIsDragging] = useState(false)
  const dragCounter = useRef(0)
  const drawerDocIdRef = useRef<string | null>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const location = useLocation()

  // Auto-focus search when navigated via Ctrl+K
  useEffect(() => {
    if (location.state?.focusSearch && searchInputRef.current) {
      searchInputRef.current.focus()
      window.history.replaceState({}, document.title)
    }
  }, [location])

  // 加载分类列表
  useEffect(() => {
    categoryApi.getTree().then(setCategories).catch(() => {})
  }, [])

  // 加载用户解析策略（上传 / 解析配置下拉）
  useEffect(() => {
    api
      .get<ParseStrategyOption[]>("/parse-strategies")
      .then((res) => setParseStrategies(res || []))
      .catch(() => {})
  }, [])

  // 同步抽屉文档 id 到 ref（供解析轮询回调读取最新值）
  useEffect(() => {
    drawerDocIdRef.current = drawerDocId
  }, [drawerDocId])

  // 加载文档列表
  useEffect(() => {
    loadDocuments()
  }, [selectedCategoryId])

  const loadDocuments = async () => {
    setIsLoading(true)
    try {
      const res = await api.get<{ items: DocumentItem[]; total: number }>(
        "/documents",
        {
          params: selectedCategoryId
            ? { category_id: selectedCategoryId, page: 1, page_size: 100 }
            : { page: 1, page_size: 100 },
        }
      )
      setDocuments(res.items || [])
    } catch {
      toast.error("加载文档失败")
    } finally {
      setIsLoading(false)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) setUploadFile(file)
  }

  const handleUpload = async () => {
    if (!uploadFile) {
      toast.error("请先选择文件")
      return
    }
    setIsUploading(true)
    try {
      const formData = new FormData()
      formData.append("file", uploadFile)
      formData.append("auto_parse", String(autoParse))
      if (uploadCategoryId) formData.append("category_id", uploadCategoryId)
      if (uploadStrategyId) formData.append("strategy_id", uploadStrategyId)

      const uploadRes = await fetch("/api/v1/uploads/document", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("aura_token") || ""}`,
        },
        body: formData,
      })
      const uploadData = await uploadRes.json()
      if (!uploadRes.ok || uploadData.code !== 0) {
        throw new Error(uploadData.message || "上传失败")
      }

      if (!autoParse) {
        toast.success("文档已上传（未自动解析）")
      } else {
        toast.success("文档已上传并开始解析")
        pollDocumentStatus(uploadData.data.document_id)
      }
      setShowUploadDialog(false)
      setUploadFile(null)
      loadDocuments()
    } catch (err: any) {
      toast.error(err.message || "上传失败")
    } finally {
      setIsUploading(false)
    }
  }

  // ========== 解析配置（策略选择 + 自定义参数 + 预览/开始） ==========
  const openParseConfig = (docId: string) => {
    setParseConfigDocId(docId)
    setParseConfigStrategyId("")
    setShowCustomParams(false)
    setPcParseMode("")
    setPcChunkSize("")
    setPcChunkOverlap("")
    setPcSplitMethod("")
    setPcExtractImages("")
    setShowParseConfig(true)
  }

  // 组装 DocumentParseRequest / ChunkPreviewRequest 请求体（空值不覆盖策略）
  const buildParseBody = () => {
    const body: Record<string, any> = {}
    if (parseConfigStrategyId) body.strategy_id = parseConfigStrategyId
    if (showCustomParams) {
      if (pcParseMode) body.parse_mode = pcParseMode
      if (pcChunkSize) body.chunk_size = Number(pcChunkSize)
      if (pcChunkOverlap !== "") body.chunk_overlap = Number(pcChunkOverlap)
      if (pcSplitMethod) body.split_method = pcSplitMethod
      if (pcExtractImages) body.extract_images = pcExtractImages === "true"
    }
    return body
  }

  const handleParseConfirm = async () => {
    if (!parseConfigDocId) return
    setIsParseStarting(true)
    try {
      await api.post(`/documents/${parseConfigDocId}/parse`, buildParseBody())
      toast.success("解析任务已启动")
      setShowParseConfig(false)
      pollDocumentStatus(parseConfigDocId)
      loadDocuments()
    } catch {
      toast.error("启动解析失败")
    } finally {
      setIsParseStarting(false)
    }
  }

  const handleParsePreview = async () => {
    if (!parseConfigDocId) return
    const docId = parseConfigDocId
    setPreviewDocId(docId)
    setPreviewLoading(true)
    setShowParseConfig(false)
    setShowChunkPreview(true)
    try {
      const res = await api.post(`/documents/${docId}/chunks/preview`, buildParseBody())
      setPreviewData(res)
    } catch {
      toast.error("预览分块失败")
      setShowChunkPreview(false)
    } finally {
      setPreviewLoading(false)
    }
  }

  // 已完成文档的快捷预览（默认策略参数，不覆盖）
  const handlePreviewChunks = async (docId: string) => {
    setPreviewDocId(docId)
    setPreviewLoading(true)
    setShowChunkPreview(true)
    try {
      const res = await api.post(`/documents/${docId}/chunks/preview`, {})
      setPreviewData(res)
    } catch {
      toast.error("预览分块失败")
      setShowChunkPreview(false)
    } finally {
      setPreviewLoading(false)
    }
  }

  // ========== 检索测试 ==========
  const handleSearchTest = async () => {
    const query = searchTestQuery.trim()
    if (!query) {
      toast.error("请输入测试查询")
      return
    }
    setSearchTestLoading(true)
    try {
      const res = await api.post<SearchTestResponse>("/documents/search", {
        query,
        top_k: searchTestTopK,
        knowledge_base_ids: [],
        filters: {},
      })
      setSearchTestResult(res)
      setExpandedChunks(new Set())
    } catch {
      // 错误已在 api client 中 toast
    } finally {
      setSearchTestLoading(false)
    }
  }

  const toggleChunkExpand = (chunkId: string) => {
    setExpandedChunks((prev) => {
      const n = new Set(prev)
      if (n.has(chunkId)) n.delete(chunkId)
      else n.add(chunkId)
      return n
    })
  }

  const pollDocumentStatus = async (documentId: string) => {
    const maxAttempts = 30
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const res = await api.get<{ parse_status: DocStatus; parse_error?: string }>(`/documents/${documentId}/status`)
        const status = res.parse_status
        if (status === "completed") {
          toast.success("文档解析完成")
          // 完成后刷新文档列表与抽屉分块，形成"解析后回显分块"闭环
          loadDocuments()
          if (drawerDocIdRef.current === documentId) loadDrawerChunks(documentId)
          break
        } else if (status === "failed") {
          toast.error("文档解析失败: " + (res.parse_error || "未知错误"))
          loadDocuments()
          break
        }
      } catch {
        break
      }
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除该文档吗？")) return
    try {
      await api.delete(`/documents/${id}`)
      setDocuments((prev) => prev.filter((d) => d.id !== id))
      setSelectedIds((prev) => { const n = new Set(prev); n.delete(id); return n })
      toast.success("文档已删除")
    } catch {
      // 错误已在 api client 中 toast
    }
  }

  // ========== 批量操作 ==========
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const n = new Set(prev)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  }

  const selectAll = () => {
    setSelectedIds(new Set(filteredDocs.map((d) => d.id)))
  }

  const clearSelection = () => {
    setSelectedIds(new Set())
    setIsBatchMode(false)
  }

  const handleBatchDelete = async () => {
    if (!confirm(`确定要删除选中的 ${selectedIds.size} 个文档吗？`)) return
    try {
      await api.post("/documents/batch-delete", { document_ids: Array.from(selectedIds) })
      setDocuments((prev) => prev.filter((d) => !selectedIds.has(d.id)))
      toast.success(`已删除 ${selectedIds.size} 个文档`)
      clearSelection()
    } catch {
      toast.error("批量删除失败")
    }
  }

  const handleBatchParse = async () => {
    const ids = Array.from(selectedIds)
    let started = 0
    for (const id of ids) {
      try {
        await api.post(`/documents/${id}/parse`)
        started++
      } catch {
        // 忽略单个失败
      }
    }
    toast.success(`已启动 ${started} 个解析任务`)
    ids.forEach((id) => pollDocumentStatus(id))
    clearSelection()
  }

  const handleBatchMove = async (categoryId: string) => {
    try {
      await api.post("/documents/batch-move", { document_ids: Array.from(selectedIds), category_id: categoryId })
      setDocuments((prev) =>
        prev.map((d) => (selectedIds.has(d.id) ? { ...d, category_id: categoryId } : d))
      )
      toast.success("批量移动完成")
      clearSelection()
    } catch {
      toast.error("批量移动失败")
    }
  }

  // ========== 详情抽屉 ==========
  const openDetailDrawer = async (docId: string) => {
    setDrawerDocId(docId)
    setShowDetailDrawer(true)
    setDrawerTab("overview")
    setDrawerLoading(true)
    const doc = documents.find((d) => d.id === docId)
    setDrawerDoc(doc || null)
    // 并行加载所有数据
    await Promise.all([
      loadDrawerChunks(docId),
      loadDrawerVersions(docId),
      loadDrawerImages(docId),
    ])
    setDrawerLoading(false)
  }

  const loadDrawerChunks = async (docId: string) => {
    try {
      const res = await api.get<any[]>(`/documents/${docId}/chunks`)
      setDrawerChunks(res || [])
    } catch {
      setDrawerChunks([])
    }
  }

  const loadDrawerVersions = async (docId: string) => {
    try {
      const res = await api.get<any[]>(`/documents/${docId}/versions`)
      setDrawerVersions(res || [])
    } catch {
      setDrawerVersions([])
    }
  }

  // 加载文档图片，建立 image_id -> oss_url 映射供分块缩略图回显
  const loadDrawerImages = async (docId: string) => {
    try {
      const res = await api.get<any[]>(`/documents/${docId}/images`)
      const map: Record<string, string> = {}
      for (const img of res || []) {
        if (img.image_ref_id) map[img.image_ref_id] = img.oss_url
        if (img.id) map[img.id] = img.oss_url
      }
      setDrawerImageMap(map)
    } catch {
      setDrawerImageMap({})
    }
  }

  // ========== 拖拽上传 ==========
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current++
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true)
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current--
    if (dragCounter.current === 0) {
      setIsDragging(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current = 0
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setUploadFile(e.dataTransfer.files[0])
      setShowUploadDialog(true)
    }
  }

  const filteredDocs = useMemo(() => {
    return documents.filter((doc) => {
      if (activeTab !== "全部") {
        const t = getFileType(doc.original_name)
        if (activeTab === "Word" && t !== "docx") return false
        if (activeTab === "PDF" && t !== "pdf") return false
        if (activeTab === "Excel" && t !== "xlsx") return false
        if (activeTab === "其他" && ["pdf", "docx", "xlsx"].includes(t)) return false
      }
      if (searchQuery) {
        return doc.original_name.toLowerCase().includes(searchQuery.toLowerCase())
      }
      return true
    })
  }, [documents, activeTab, searchQuery])

  // 扁平化分类
  const allCategories = useMemo(() => {
    const flatten = (nodes: CategoryTreeNode[]): CategoryTreeNode[] => {
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
    return flatten(categories)
  }, [categories])

  const categoryNameMap = useMemo(() => {
    return new Map(allCategories.map((c) => [c.id, c.name]))
  }, [allCategories])

  const stats = useMemo(() => [
    { label: "全部文档", value: documents.length, icon: FileText, color: "text-blue-600", bg: "bg-blue-50" },
    { label: "已索引", value: documents.filter((d) => d.parse_status === "completed").length, icon: CheckCircle, color: "text-emerald-600", bg: "bg-emerald-50" },
    { label: "解析中", value: documents.filter((d) => d.parse_status === "pending" || d.parse_status === "running").length, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
    { label: "向量片段", value: "8.4k", icon: Grid3X3, color: "text-purple-600", bg: "bg-purple-50" },
  ], [documents])

  return (
    <div
      className="space-y-6 relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <PageHeader />

      {/* Page Title & Actions */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#292524] tracking-tight">文档中心</h2>
          <p className="text-sm text-[#a8a29e] mt-1">管理文档、分块与向量索引</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setShowSearchTest(true)}
            className="rounded-xl px-4 flex items-center gap-2 border-[#e7e5e4]"
          >
            <FlaskConical className="size-4" />
            检索测试
          </Button>
          <Button
            onClick={() => setShowUploadDialog(true)}
            className="btn-primary-gradient rounded-xl px-4 flex items-center gap-2"
          >
            <Upload className="size-4" />
            上传文档
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="bg-white rounded-2xl p-5 border border-[#e7e5e4] shadow-[0_1px_3px_rgba(0,0,0,0.04)] hover-lift cursor-pointer"
          >
            <div className="flex items-center justify-between mb-3">
              <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", stat.bg)}>
                <stat.icon className={cn("size-5", stat.color)} />
              </div>
            </div>
            <p className="text-2xl font-bold text-[#292524]">{stat.value}</p>
            <p className="text-xs text-[#a8a29e] mt-1">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
              activeTab === tab
                ? "bg-[#292524] text-white"
                : "bg-white border border-[#e7e5e4] text-[#78716c] hover:border-primary/40 hover:text-primary"
            )}
          >
            {tab}
          </button>
        ))}
        {categories.length > 0 && (
          <>
            <div className="w-px h-4 bg-[#e7e5e4]" />
            <button
              onClick={() => setSelectedCategoryId(null)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                selectedCategoryId === null
                  ? "bg-primary text-white"
                  : "bg-white border border-[#e7e5e4] text-[#78716c] hover:border-primary/40 hover:text-primary"
              )}
            >
              全部分类
            </button>
            {allCategories.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setSelectedCategoryId(cat.id)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                  selectedCategoryId === cat.id
                    ? "bg-primary text-white"
                    : "bg-white border border-[#e7e5e4] text-[#78716c] hover:border-primary/40 hover:text-primary"
                )}
              >
                {cat.name}
              </button>
            ))}
          </>
        )}
        <div className="flex-1" />
        {/* 批量模式切换 */}
        <button
          onClick={() => {
            setIsBatchMode((v) => !v)
            if (isBatchMode) clearSelection()
          }}
          className={cn(
            "px-3 py-1.5 rounded-lg text-xs font-medium transition-all border",
            isBatchMode
              ? "bg-primary text-white border-primary"
              : "bg-white border-[#e7e5e4] text-[#78716c] hover:border-primary/40 hover:text-primary"
          )}
        >
          {isBatchMode ? "退出批量" : "批量操作"}
        </button>
        {/* 视图切换 */}
        <div className="flex items-center bg-white rounded-lg border border-[#e7e5e4] p-0.5">
          <button
            onClick={() => setViewMode("grid")}
            className={cn(
              "p-1.5 rounded-md transition-all",
              viewMode === "grid" ? "bg-[#f5f5f4] text-[#292524]" : "text-[#a8a29e] hover:text-[#57534e]"
            )}
            title="网格视图"
          >
            <Grid3X3 className="size-4" />
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={cn(
              "p-1.5 rounded-md transition-all",
              viewMode === "list" ? "bg-[#f5f5f4] text-[#292524]" : "text-[#a8a29e] hover:text-[#57534e]"
            )}
            title="列表视图"
          >
            <List className="size-4" />
          </button>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="搜索文档..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-56 pl-9 pr-4 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
          />
        </div>
      </div>

      {/* Document Content */}
      {isLoading ? (
        viewMode === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="bg-white rounded-2xl border border-[#e7e5e4] p-5 animate-pulse">
                <div className="w-12 h-12 rounded-xl bg-[#f5f5f4] mb-4" />
                <div className="h-4 bg-[#f5f5f4] rounded w-3/4 mb-2" />
                <div className="h-3 bg-[#f5f5f4] rounded w-1/2 mb-4" />
                <div className="flex gap-2">
                  <div className="h-5 bg-[#f5f5f4] rounded w-16" />
                  <div className="h-5 bg-[#f5f5f4] rounded w-12" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-[#e7e5e4] overflow-hidden">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 px-5 py-3 animate-pulse border-b border-[#f5f5f4] last:border-0">
                <div className="w-8 h-8 rounded-lg bg-[#f5f5f4]" />
                <div className="flex-1 h-4 bg-[#f5f5f4] rounded w-1/3" />
                <div className="h-4 bg-[#f5f5f4] rounded w-20" />
                <div className="h-4 bg-[#f5f5f4] rounded w-16" />
              </div>
            ))}
          </div>
        )
      ) : filteredDocs.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
            <FileSearch className="size-8 text-[#a8a29e]" />
          </div>
          <h3 className="text-base font-semibold text-[#44403c] mb-1">
            {searchQuery ? "未找到匹配的文档" : "暂无文档"}
          </h3>
          <p className="text-sm text-[#a8a29e] mb-5 max-w-sm">
            {searchQuery
              ? "尝试更换搜索关键词，或上传新文档到知识库"
              : "知识库中还没有文档，上传第一个文档开始构建你的知识库吧"}
          </p>
          <Button
            onClick={() => {
              if (searchQuery) {
                setSearchQuery("")
                setActiveTab("全部")
              } else {
                setShowUploadDialog(true)
              }
            }}
            className="btn-primary-gradient rounded-xl px-5"
          >
            <Upload className="size-4 mr-2" />
            {searchQuery ? "清除搜索" : "上传文档"}
          </Button>
        </div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
          {filteredDocs.map((doc) => {
            const type = doc.type || getFileType(doc.original_name)
            const colors = typeColors[type] || typeColors.default
            const Icon = typeIcons[type] || typeIcons.default
            const status = statusConfig[doc.parse_status]
            const StatusIcon = status.icon
            const isSelected = selectedIds.has(doc.id)

            return (
              <div
                key={doc.id}
                onClick={() => {
                  if (isBatchMode) toggleSelect(doc.id)
                  else openDetailDrawer(doc.id)
                }}
                className={cn(
                  "group bg-white rounded-2xl border p-5 hover:border-primary/20 hover-lift cursor-pointer transition-all relative",
                  isSelected ? "border-primary ring-2 ring-primary/10" : "border-[#e7e5e4]"
                )}
              >
                {isBatchMode && (
                  <div className="absolute top-3 left-3 z-10">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(doc.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="rounded border-[#d6d3d1] text-primary focus:ring-primary size-4"
                    />
                  </div>
                )}
                <div className="flex items-start justify-between mb-4">
                  <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center", colors.bg)}>
                    <Icon className={cn("size-6", colors.text)} />
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    {doc.parse_status === "pending" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          openParseConfig(doc.id)
                        }}
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-emerald-600 hover:bg-emerald-50 transition-all"
                        title="解析配置"
                      >
                        <Zap className="size-3.5" />
                      </button>
                    )}
                    {doc.parse_status === "completed" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handlePreviewChunks(doc.id)
                        }}
                        className="w-7 h-7 rounded-lg flex items-center justify-center text-primary hover:bg-primary/10 transition-all"
                        title="预览分块"
                      >
                        <Grid3X3 className="size-3.5" />
                      </button>
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(doc.id)
                      }}
                      className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
                      title="删除"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                </div>

                <h3 className="text-sm font-semibold text-[#292524] truncate mb-1 group-hover:text-primary transition-colors">
                  {doc.original_name}
                </h3>
                <p className="text-xs text-[#a8a29e] mb-4">{formatFileSize(doc.file_size)} · {formatDate(doc.updated_at)}</p>

                <div className="flex items-center justify-between">
                  <div className="flex gap-1.5 flex-wrap">
                    <span className={cn("px-2 py-0.5 rounded-md text-[10px] font-medium border flex items-center gap-1", status.style)}>
                      <StatusIcon className={cn("size-3", doc.parse_status === "running" && "animate-spin")} />
                      {status.label}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-[#f5f5f4] text-[#57534e] text-[10px] font-medium border border-[#e7e5e4]">
                      {categoryNameMap.get(doc.category_id || "") || "未分类"}
                    </span>
                    {doc.parse_status === "completed" && doc.chunk_size && (
                      <span className="px-2 py-0.5 rounded-md bg-purple-50 text-purple-600 text-[10px] font-medium border border-purple-100">
                        chunk:{doc.chunk_size}/{doc.chunk_overlap}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )
          })}

          {/* Upload placeholder */}
          <button
            onClick={() => setShowUploadDialog(true)}
            className="rounded-2xl border-2 border-dashed border-[#d6d3d1] p-5 flex flex-col items-center justify-center text-[#a8a29e] hover:border-primary/40 hover:text-primary hover:bg-accent/30 transition-all cursor-pointer min-h-[200px]"
          >
            <div className="w-12 h-12 rounded-xl bg-[#f5f5f4] flex items-center justify-center mb-3">
              <Upload className="size-6" />
            </div>
            <p className="text-sm font-medium">上传新文档</p>
            <p className="text-xs text-[#a8a29e] mt-1">支持 PDF、Word、Excel</p>
          </button>
        </div>
      ) : (
        /* 列表视图 */
        <div className="bg-white rounded-2xl border border-[#e7e5e4] overflow-hidden">
          <div className="grid grid-cols-[auto_1fr_100px_100px_140px_100px_auto] gap-3 px-5 py-3 bg-[#fafaf9] border-b border-[#e7e5e4] text-[11px] font-semibold text-[#a8a29e] uppercase tracking-wider">
            {isBatchMode && <div className="w-8" />}
            <div>文件名</div>
            <div>大小</div>
            <div>状态</div>
            <div>分类</div>
            <div>更新时间</div>
            <div className="text-right">操作</div>
          </div>
          {filteredDocs.map((doc) => {
            const type = doc.type || getFileType(doc.original_name)
            const colors = typeColors[type] || typeColors.default
            const Icon = typeIcons[type] || typeIcons.default
            const status = statusConfig[doc.parse_status]
            const StatusIcon = status.icon
            const isSelected = selectedIds.has(doc.id)

            return (
              <div
                key={doc.id}
                onClick={() => {
                  if (isBatchMode) toggleSelect(doc.id)
                  else openDetailDrawer(doc.id)
                }}
                className={cn(
                  "grid grid-cols-[auto_1fr_100px_100px_140px_100px_auto] gap-3 px-5 py-3 items-center border-b border-[#f5f5f4] last:border-0 cursor-pointer transition-colors",
                  isSelected ? "bg-primary/5" : "hover:bg-[#fafaf9]"
                )}
              >
                {isBatchMode && (
                  <div className="w-8">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(doc.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="rounded border-[#d6d3d1] text-primary focus:ring-primary size-4"
                    />
                  </div>
                )}
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0", colors.bg)}>
                    <Icon className={cn("size-4", colors.text)} />
                  </div>
                  <span className="text-sm text-[#292524] font-medium truncate">{doc.original_name}</span>
                </div>
                <div className="text-xs text-[#78716c]">{formatFileSize(doc.file_size)}</div>
                <div>
                  <span className={cn("px-2 py-0.5 rounded-md text-[10px] font-medium border flex items-center gap-1 w-fit", status.style)}>
                    <StatusIcon className={cn("size-3", doc.parse_status === "running" && "animate-spin")} />
                    {status.label}
                  </span>
                </div>
                <div className="text-xs text-[#78716c]">{categoryNameMap.get(doc.category_id || "") || "未分类"}</div>
                <div className="text-xs text-[#a8a29e]">{formatDate(doc.updated_at)}</div>
                <div className="flex items-center justify-end gap-1">
                  {doc.parse_status === "pending" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); openParseConfig(doc.id) }}
                      className="w-7 h-7 rounded-lg flex items-center justify-center text-emerald-600 hover:bg-emerald-50 transition-all"
                      title="解析配置"
                    >
                      <Zap className="size-3.5" />
                    </button>
                  )}
                  {doc.parse_status === "completed" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handlePreviewChunks(doc.id) }}
                      className="w-7 h-7 rounded-lg flex items-center justify-center text-primary hover:bg-primary/10 transition-all"
                      title="预览分块"
                    >
                      <Grid3X3 className="size-3.5" />
                    </button>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(doc.id) }}
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
                    title="删除"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Version History Dialog */}
      <Dialog open={showVersionDialog} onOpenChange={setShowVersionDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Clock className="size-5 text-primary" />
              版本历史
            </DialogTitle>
          </DialogHeader>
          {versionLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-6 animate-spin text-primary" />
            </div>
          ) : versions.length === 0 ? (
            <div className="text-center py-12 text-sm text-[#a8a29e]">暂无版本记录</div>
          ) : (
            <div className="space-y-2 max-h-[360px] overflow-y-auto">
              {versions.map((v) => (
                <div key={v.id} className="flex items-center justify-between p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                  <div>
                    <p className="text-sm font-medium text-[#44403c]">版本 {v.version}</p>
                    <p className="text-[10px] text-[#a8a29e]">{formatFileSize(v.file_size)} · {formatDate(v.created_at)}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => {
                      api.post(`/documents/${versionDocId}/rollback`, { version_id: v.id })
                        .then(() => { toast.success("回滚成功"); loadDocuments(); setShowVersionDialog(false) })
                        .catch(() => toast.error("回滚失败"))
                    }}
                  >
                    回滚
                  </Button>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Upload Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Upload className="size-5 text-primary" />
              上传文档
            </DialogTitle>
          </DialogHeader>
          <div className="p-4 border-2 border-dashed border-[#e7e5e4] rounded-xl bg-[#fafaf9] text-center hover:border-primary/30 transition-colors">
            <input type="file" id="doc-upload" className="hidden" onChange={handleFileSelect} />
            <label htmlFor="doc-upload" className="cursor-pointer block">
              <FileText className="size-8 text-[#a8a29e] mx-auto mb-2" />
              {uploadFile ? (
                <p className="text-sm text-[#44403c] font-medium">{uploadFile.name}</p>
              ) : (
                <p className="text-sm text-[#a8a29e]">点击选择文件或拖拽到此处</p>
              )}
            </label>
          </div>
          {categories.length > 0 && (
            <div className="px-4">
              <label className="text-sm font-medium text-[#44403c] mb-1.5 block">所属分类</label>
              <select
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
                value={uploadCategoryId}
                onChange={(e) => setUploadCategoryId(e.target.value)}
              >
                <option value="">不分配分类</option>
                {allCategories.map((cat) => (
                  <option key={cat.id} value={cat.id}>{cat.name}</option>
                ))}
              </select>
            </div>
          )}

          <div className="px-4">
            <label className="text-sm font-medium text-[#44403c] mb-1.5 block">解析策略</label>
            <select
              className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
              value={uploadStrategyId}
              onChange={(e) => setUploadStrategyId(e.target.value)}
            >
              <option value="">系统默认</option>
              {parseStrategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}{s.is_default ? "（默认）" : ""}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-[#a8a29e]">
              txt / md / json / csv 等纯文本文件将自动按纯文本解析
            </p>
          </div>

          <div className="px-4">
            <label className="flex items-center gap-1.5 text-xs text-[#78716c] cursor-pointer">
              <input
                type="checkbox"
                checked={autoParse}
                onChange={(e) => setAutoParse(e.target.checked)}
                className="rounded border-[#d6d3d1] text-primary focus:ring-primary"
              />
              上传后立即解析
            </label>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setShowUploadDialog(false)
                setUploadFile(null)
              }}
              className="rounded-xl border-[#e7e5e4]"
            >
              取消
            </Button>
            <Button
              className="btn-primary-gradient rounded-xl"
              onClick={handleUpload}
              disabled={isUploading || !uploadFile}
            >
              {isUploading ? (
                <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Upload className="size-4 mr-2" />
              )}
              上传
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Parse Config Dialog */}
      <Dialog open={showParseConfig} onOpenChange={setShowParseConfig}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Zap className="size-5 text-primary" />
              解析配置
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium text-[#44403c] mb-1.5 block">解析策略</label>
              <select
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
                value={parseConfigStrategyId}
                onChange={(e) => setParseConfigStrategyId(e.target.value)}
              >
                <option value="">系统默认</option>
                {parseStrategies.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}{s.is_default ? "（默认）" : ""}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-[11px] text-[#a8a29e]">
                选择策略后可直接开始解析，或先预览分块效果
              </p>
            </div>

            <button
              type="button"
              onClick={() => setShowCustomParams((v) => !v)}
              className="flex items-center gap-1 text-xs text-primary hover:underline"
            >
              {showCustomParams ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
              自定义参数（覆盖策略）
            </button>

            {showCustomParams && (
              <div className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-[#a8a29e] mb-1 block">解析模式</label>
                    <select
                      className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all appearance-none"
                      value={pcParseMode}
                      onChange={(e) => setPcParseMode(e.target.value)}
                    >
                      <option value="">跟随策略</option>
                      <option value="pymupdf">PyMuPDF 图文提取</option>
                      <option value="paddleocr">PaddleOCR</option>
                      <option value="vlm">VLM 视觉理解</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#a8a29e] mb-1 block">切分方式</label>
                    <select
                      className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all appearance-none"
                      value={pcSplitMethod}
                      onChange={(e) => setPcSplitMethod(e.target.value)}
                    >
                      <option value="">跟随策略</option>
                      <option value="sentence">句子切分</option>
                      <option value="token">Token 切分</option>
                      <option value="structured">结构化切分</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#a8a29e] mb-1 block">Chunk Size</label>
                    <input
                      type="number"
                      min={100}
                      max={4000}
                      step={50}
                      placeholder="跟随策略"
                      value={pcChunkSize}
                      onChange={(e) => setPcChunkSize(e.target.value)}
                      className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-[#a8a29e] mb-1 block">Overlap</label>
                    <input
                      type="number"
                      min={0}
                      max={1000}
                      step={10}
                      placeholder="跟随策略"
                      value={pcChunkOverlap}
                      onChange={(e) => setPcChunkOverlap(e.target.value)}
                      className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all"
                    />
                  </div>
                  <div className="col-span-2">
                    <label className="text-[10px] text-[#a8a29e] mb-1 block">提取图片到 OSS</label>
                    <select
                      className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all appearance-none"
                      value={pcExtractImages}
                      onChange={(e) => setPcExtractImages(e.target.value)}
                    >
                      <option value="">跟随策略</option>
                      <option value="true">提取</option>
                      <option value="false">不提取</option>
                    </select>
                  </div>
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={handleParsePreview}
              className="rounded-xl border-[#e7e5e4]"
            >
              <Grid3X3 className="size-4 mr-1.5" />
              预览分块
            </Button>
            <Button
              className="btn-primary-gradient rounded-xl"
              onClick={handleParseConfirm}
              disabled={isParseStarting}
            >
              {isParseStarting ? (
                <Loader2 className="size-4 mr-1.5 animate-spin" />
              ) : (
                <Zap className="size-4 mr-1.5" />
              )}
              开始解析
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Chunk Preview Dialog */}
      <Dialog open={showChunkPreview} onOpenChange={setShowChunkPreview}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-3xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Grid3X3 className="size-5 text-primary" />
              分块预览
            </DialogTitle>
          </DialogHeader>
          {previewLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-6 animate-spin text-primary" />
            </div>
          ) : !previewData ? (
            <div className="text-center py-12 text-sm text-[#a8a29e]">暂无预览数据</div>
          ) : (
            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              <div className="flex items-center flex-wrap gap-x-4 gap-y-1 text-xs text-[#a8a29e] mb-2">
                <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 text-[10px] font-medium">
                  {modeUsedLabels[previewData.mode_used] || previewData.mode_used || "PyMuPDF"}
                </span>
                <span>共 {previewData.page_count} 页</span>
                <span>共 {previewData.chunks?.length || 0} 个分块</span>
                <span>共 {previewData.total_images} 张图片</span>
              </div>
              {previewData.chunks?.map((chunk: any, idx: number) => (
                <div key={chunk.chunk_id || idx} className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                  <div className="flex items-center flex-wrap gap-2 mb-1.5">
                    <span className="text-[10px] font-bold text-primary bg-primary/10 px-1.5 py-0.5 rounded">#{idx + 1}</span>
                    <span className="text-[10px] text-[#a8a29e]">第 {chunk.page} 页</span>
                    {chunk.chunk_type && chunk.chunk_type !== "text" && (
                      <span className="text-[10px] text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-100">
                        {chunk.chunk_type === "table" ? "表格" : chunk.chunk_type}
                      </span>
                    )}
                    {chunk.image_ids?.length > 0 && (
                      <span className="text-[10px] text-purple-600 bg-purple-50 px-1.5 py-0.5 rounded border border-purple-100">
                        {chunk.image_ids.length} 张图片
                      </span>
                    )}
                  </div>
                  {chunk.heading && (
                    <p className="text-[10px] text-[#78716c] mb-1 flex items-center gap-1">
                      <Layers className="size-3" />
                      {chunk.heading}
                    </p>
                  )}
                  <p className="text-xs text-[#44403c] leading-relaxed whitespace-pre-wrap line-clamp-6">{stripImgPlaceholders(chunk.content)}</p>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ========== 检索测试 Dialog ========== */}
      <Dialog open={showSearchTest} onOpenChange={setShowSearchTest}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-3xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <FlaskConical className="size-5 text-primary" />
              检索测试
            </DialogTitle>
          </DialogHeader>

          {/* 输入区 */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
              <input
                type="text"
                placeholder="输入测试查询，回车发起检索..."
                value={searchTestQuery}
                onChange={(e) => setSearchTestQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !searchTestLoading) handleSearchTest()
                }}
                className="w-full pl-9 pr-4 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-[#78716c] whitespace-nowrap">top_k</label>
              <input
                type="number"
                min={1}
                max={100}
                step={1}
                value={searchTestTopK}
                onChange={(e) => setSearchTestTopK(Number(e.target.value))}
                className="w-20 px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
              />
            </div>
            <Button
              onClick={handleSearchTest}
              disabled={searchTestLoading || !searchTestQuery.trim()}
              className="btn-primary-gradient rounded-xl px-4"
            >
              {searchTestLoading ? (
                <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Search className="size-4 mr-2" />
              )}
              检索
            </Button>
          </div>

          {/* 结果区 */}
          <div className="flex-1 overflow-y-auto space-y-3 pr-1 mt-2">
            {searchTestLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="size-6 animate-spin text-primary" />
              </div>
            ) : !searchTestResult ? (
              <div className="text-center py-12 text-sm text-[#a8a29e]">
                输入查询并点击「检索」，验证知识库召回效果
              </div>
            ) : (
              <>
                {searchTestResult.rewritten_query && (
                  <div className="p-3 rounded-xl bg-primary/5 border border-primary/10">
                    <p className="text-[10px] text-[#a8a29e] mb-0.5">改写后查询</p>
                    <p className="text-xs font-medium text-primary">{searchTestResult.rewritten_query}</p>
                  </div>
                )}
                {searchTestResult.results.length === 0 ? (
                  <div className="text-center py-12 text-sm text-[#a8a29e]">未召回到相关分片</div>
                ) : (
                  <>
                    <p className="text-xs text-[#a8a29e]">
                      共召回 {searchTestResult.results.length} 个分片
                    </p>
                    {searchTestResult.results.map((r, idx) => {
                      const expanded = expandedChunks.has(r.chunk_id)
                      return (
                        <div key={r.chunk_id || idx} className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                            <span className="text-[10px] font-bold text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                              #{idx + 1}
                            </span>
                            <span className="text-[10px] font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-100">
                              score: {r.score.toFixed(3)}
                            </span>
                            <span className="text-[10px] text-[#57534e] bg-[#f5f5f4] px-1.5 py-0.5 rounded border border-[#e7e5e4]">
                              {r.search_type}
                            </span>
                            {r.page_number != null && (
                              <span className="text-[10px] text-[#a8a29e]">第 {r.page_number} 页</span>
                            )}
                          </div>
                          <p
                            className={cn(
                              "text-xs text-[#44403c] leading-relaxed whitespace-pre-wrap",
                              !expanded && "line-clamp-3"
                            )}
                          >
                            {r.content}
                          </p>
                          <button
                            onClick={() => toggleChunkExpand(r.chunk_id)}
                            className="mt-1.5 flex items-center gap-0.5 text-[11px] text-primary hover:text-primary/80 transition-colors"
                          >
                            {expanded ? (
                              <>
                                收起 <ChevronUp className="size-3" />
                              </>
                            ) : (
                              <>
                                展开 <ChevronDown className="size-3" />
                              </>
                            )}
                          </button>
                        </div>
                      )
                    })}
                  </>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* ========== 详情抽屉 ========== */}
      {showDetailDrawer && (
        <div className="fixed inset-0 z-50 flex justify-end">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/30 backdrop-blur-[2px] transition-opacity"
            onClick={() => setShowDetailDrawer(false)}
          />
          {/* Drawer Panel */}
          <div className="relative w-full max-w-lg bg-white h-full shadow-2xl flex flex-col animate-[slideInRight_0.2s_ease-out]">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-[#e7e5e4]">
              <h3 className="text-base font-bold text-[#292524]">文档详情</h3>
              <button
                onClick={() => setShowDetailDrawer(false)}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#44403c] transition-all"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Tabs */}
            <div className="flex items-center gap-0 px-5 border-b border-[#e7e5e4] bg-[#fafaf9]">
              {([
                { key: "overview", label: "概览", icon: Info },
                { key: "chunks", label: "分块", icon: Layers },
                { key: "versions", label: "版本", icon: History },
              ] as const).map((t) => (
                <button
                  key={t.key}
                  onClick={() => setDrawerTab(t.key)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-all",
                    drawerTab === t.key
                      ? "border-primary text-primary"
                      : "border-transparent text-[#78716c] hover:text-[#44403c]"
                  )}
                >
                  <t.icon className="size-3.5" />
                  {t.label}
                </button>
              ))}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-5">
              {drawerLoading && !drawerDoc ? (
                <div className="flex items-center justify-center py-20">
                  <Loader2 className="size-6 animate-spin text-primary" />
                </div>
              ) : !drawerDoc ? (
                <div className="text-center py-20 text-sm text-[#a8a29e]">未找到文档</div>
              ) : drawerTab === "overview" ? (
                <div className="space-y-5">
                  {/* 基本信息 */}
                  <div className="flex items-start gap-3">
                    {(() => {
                      const dType = drawerDoc.type || getFileType(drawerDoc.original_name)
                      const DIcon = typeIcons[dType] || typeIcons.default
                      const dColors = typeColors[dType] || typeColors.default
                      return (
                        <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0", dColors.bg)}>
                          <DIcon className={cn("size-6", dColors.text)} />
                        </div>
                      )
                    })()}
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-[#292524] break-all">{drawerDoc.original_name}</p>
                      <p className="text-xs text-[#a8a29e] mt-0.5">{formatFileSize(drawerDoc.file_size)}</p>
                    </div>
                  </div>

                  {/* 状态与分类 */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                      <p className="text-[10px] text-[#a8a29e] mb-1">解析状态</p>
                      {(() => {
                        const dStatus = drawerDoc.parse_status as DocStatus
                        const sCfg = statusConfig[dStatus]
                        const SIcon = sCfg?.icon
                        return (
                          <span className={cn("px-2 py-0.5 rounded-md text-[10px] font-medium border flex items-center gap-1 w-fit", sCfg?.style)}>
                            {SIcon && <SIcon className="size-3" />}
                            {sCfg?.label || dStatus}
                          </span>
                        )
                      })()}
                    </div>
                    <div className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                      <p className="text-[10px] text-[#a8a29e] mb-1">所属分类</p>
                      <p className="text-xs font-medium text-[#44403c]">{categoryNameMap.get(drawerDoc.category_id || "") || "未分类"}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                      <p className="text-[10px] text-[#a8a29e] mb-1">更新时间</p>
                      <p className="text-xs font-medium text-[#44403c]">{formatDate(drawerDoc.updated_at)}</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                      <p className="text-[10px] text-[#a8a29e] mb-1">文档 ID</p>
                      <p className="text-xs font-medium text-[#44403c] truncate" title={drawerDoc.id}>{drawerDoc.id}</p>
                    </div>
                  </div>

                  {/* 解析策略 */}
                  <div className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                    <p className="text-[10px] text-[#a8a29e] mb-2">解析策略</p>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <p className="text-[10px] text-[#a8a29e]">解析模式</p>
                        <p className="text-xs font-medium text-[#44403c]">{drawerDoc.parse_mode || "默认"}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-[#a8a29e]">Chunk Size</p>
                        <p className="text-xs font-medium text-[#44403c]">{drawerDoc.chunk_size || "-"}</p>
                      </div>
                      <div>
                        <p className="text-[10px] text-[#a8a29e]">Overlap</p>
                        <p className="text-xs font-medium text-[#44403c]">{drawerDoc.chunk_overlap || "-"}</p>
                      </div>
                    </div>
                  </div>

                  {/* 快捷操作 */}
                  <div className="flex gap-2">
                    {drawerDoc.parse_status === "pending" && (
                      <Button
                        size="sm"
                        className="rounded-lg btn-primary-gradient flex-1"
                        onClick={() => { openParseConfig(drawerDoc.id); setShowDetailDrawer(false) }}
                      >
                        <Zap className="size-3.5 mr-1.5" />
                        解析配置
                      </Button>
                    )}
                    {drawerDoc.parse_status === "completed" && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="rounded-lg border-[#e7e5e4] flex-1"
                        onClick={() => { handlePreviewChunks(drawerDoc.id); setShowDetailDrawer(false) }}
                      >
                        <Grid3X3 className="size-3.5 mr-1.5" />
                        预览分块
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-lg border-red-200 text-red-600 hover:bg-red-50 flex-1"
                      onClick={() => { handleDelete(drawerDoc.id); setShowDetailDrawer(false) }}
                    >
                      <Trash2 className="size-3.5 mr-1.5" />
                      删除
                    </Button>
                  </div>
                </div>
              ) : drawerTab === "chunks" ? (
                <div className="space-y-3">
                  {drawerChunks.length === 0 ? (
                    <div className="text-center py-12 text-sm text-[#a8a29e]">暂无分块数据</div>
                  ) : (
                    drawerChunks.map((chunk: any, idx: number) => (
                      <div key={chunk.id || idx} className="p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                        <div className="flex items-center flex-wrap gap-2 mb-1.5">
                          <span className="text-[10px] font-bold text-primary bg-primary/10 px-1.5 py-0.5 rounded">#{idx + 1}</span>
                          <span className="text-[10px] text-[#a8a29e]">第 {chunk.page_number ?? chunk.page ?? "-"} 页</span>
                          {chunk.image_ids?.length > 0 && (
                            <span className="text-[10px] text-purple-600 bg-purple-50 px-1.5 py-0.5 rounded border border-purple-100">
                              {chunk.image_ids.length} 张图片
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-[#44403c] leading-relaxed whitespace-pre-wrap line-clamp-6">{stripImgPlaceholders(chunk.content)}</p>
                        {chunk.image_ids?.length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            {chunk.image_ids.map((imgId: string) => {
                              const url = drawerImageMap[imgId]
                              if (!url) return null
                              return (
                                <a key={imgId} href={url} target="_blank" rel="noreferrer">
                                  <img
                                    src={url}
                                    alt="分块图片"
                                    loading="lazy"
                                    className="h-16 w-auto rounded-lg border border-[#e7e5e4] object-cover hover:opacity-80 transition-opacity"
                                  />
                                </a>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {drawerVersions.length === 0 ? (
                    <div className="text-center py-12 text-sm text-[#a8a29e]">暂无版本记录</div>
                  ) : (
                    drawerVersions.map((v: any) => (
                      <div key={v.id} className="flex items-center justify-between p-3 rounded-xl bg-[#fafaf9] border border-[#e7e5e4]">
                        <div>
                          <p className="text-sm font-medium text-[#44403c]">版本 {v.version}</p>
                          <p className="text-[10px] text-[#a8a29e]">{formatFileSize(v.file_size)} · {formatDate(v.created_at)}</p>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs"
                          onClick={() => {
                            api.post(`/documents/${drawerDoc.id}/rollback`, { version_id: v.id })
                              .then(() => { toast.success("回滚成功"); loadDocuments() })
                              .catch(() => toast.error("回滚失败"))
                          }}
                        >
                          回滚
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========== 批量操作浮动栏 ========== */}
      {isBatchMode && selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 bg-[#292524] text-white px-4 py-2.5 rounded-2xl shadow-2xl animate-[bounceIn_0.2s_ease-out]">
          <div className="flex items-center gap-2 pr-3 border-r border-white/20">
            <input
              type="checkbox"
              checked={selectedIds.size === filteredDocs.length && filteredDocs.length > 0}
              onChange={(e) => e.target.checked ? selectAll() : clearSelection()}
              className="rounded border-white/30 text-primary focus:ring-primary size-4"
            />
            <span className="text-xs font-medium">已选 {selectedIds.size} 项</span>
          </div>
          <button
            onClick={handleBatchParse}
            className="flex items-center gap-1 text-xs text-white/90 hover:text-white px-2 py-1 rounded-lg hover:bg-white/10 transition-all"
            title="批量解析"
          >
            <Zap className="size-3.5" />
            解析
          </button>
          <button
            onClick={() => {
              const catId = prompt("请输入目标分类 ID（留空表示不分类）:")
              if (catId !== null) handleBatchMove(catId)
            }}
            className="flex items-center gap-1 text-xs text-white/90 hover:text-white px-2 py-1 rounded-lg hover:bg-white/10 transition-all"
            title="批量移动"
          >
            <FolderOpen className="size-3.5" />
            移动
          </button>
          <button
            onClick={handleBatchDelete}
            className="flex items-center gap-1 text-xs text-red-300 hover:text-red-200 px-2 py-1 rounded-lg hover:bg-red-500/20 transition-all"
            title="批量删除"
          >
            <Trash2 className="size-3.5" />
            删除
          </button>
          <button
            onClick={clearSelection}
            className="flex items-center gap-1 text-xs text-white/60 hover:text-white/90 pl-2 border-l border-white/20 transition-all"
          >
            <X className="size-3.5" />
            取消
          </button>
        </div>
      )}

      {/* ========== 拖拽上传遮罩 ========== */}
      {isDragging && (
        <div className="fixed inset-0 z-50 bg-primary/10 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-white rounded-2xl border-2 border-dashed border-primary/40 p-10 shadow-2xl flex flex-col items-center gap-3 animate-[pulse_1s_ease-in-out_infinite]">
            <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center">
              <Upload className="size-8 text-primary" />
            </div>
            <p className="text-lg font-semibold text-[#292524]">释放文件以上传</p>
            <p className="text-sm text-[#a8a29e]">支持 PDF、Word、Excel 等格式</p>
          </div>
        </div>
      )}
    </div>
  )
}
