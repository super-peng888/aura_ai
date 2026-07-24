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
  Star,
  FileText,
  BrainCircuit,
  ScanText,
  Layers,
  CheckCircle,
  Loader2,
} from "lucide-react"

interface ParseStrategy {
  id: string
  name: string
  parse_mode: string
  chunk_size: number
  chunk_overlap: number
  dimension: number
  split_method: string
  extract_images: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

// 解析模式收敛为三种：pymupdf / paddleocr / vlm
// （txt/md/json/csv 等纯文本文件由后端按扩展名自动走纯文本解析，无需选择）
const modeOptions = [
  { value: "pymupdf", label: "PyMuPDF 图文提取", icon: FileText, desc: "PDF 文本 + 图片提取，支持图文并茂引用" },
  { value: "paddleocr", label: "PaddleOCR", icon: ScanText, desc: "扫描件 / 图片型文档文字 OCR 识别" },
  { value: "vlm", label: "VLM 视觉理解", icon: BrainCircuit, desc: "图表 / 架构图 / 手写文档，使用 qwen3-vl-flash" },
]

// 历史模式值仅做展示兼容（存量策略可能仍是旧值，后端会自动归一）
const legacyModeLabels: Record<string, string> = {
  pymupdf_rich: "PyMuPDF 富文本（旧）",
  ocr: "OCR（旧）",
}

const splitOptions = [
  { value: "sentence", label: "句子切分" },
  { value: "token", label: "Token 切分" },
  { value: "structured", label: "结构化切分" },
]

// ============================================================================
// Main Page
// ============================================================================

export default function ParseStrategies() {
  const [strategies, setStrategies] = useState<ParseStrategy[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showDialog, setShowDialog] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  const [form, setForm] = useState({
    name: "",
    parse_mode: "pymupdf",
    chunk_size: 800,
    chunk_overlap: 100,
    dimension: 1536,
    split_method: "sentence",
    extract_images: false,
  })

  const loadStrategies = async () => {
    setIsLoading(true)
    try {
      const res = await api.get<ParseStrategy[]>("/parse-strategies")
      setStrategies(res || [])
    } catch {
      toast.error("加载策略失败")
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadStrategies()
  }, [])

  const openCreate = () => {
    setEditingId(null)
    setForm({
      name: "",
      parse_mode: "pymupdf",
      chunk_size: 800,
      chunk_overlap: 100,
      dimension: 1536,
      split_method: "sentence",
      extract_images: false,
    })
    setShowDialog(true)
  }

  const openEdit = (s: ParseStrategy) => {
    setEditingId(s.id)
    setForm({
      name: s.name,
      parse_mode: s.parse_mode,
      chunk_size: s.chunk_size,
      chunk_overlap: s.chunk_overlap,
      dimension: s.dimension,
      split_method: s.split_method,
      extract_images: s.extract_images,
    })
    setShowDialog(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      toast.error("请输入策略名称")
      return
    }
    try {
      if (editingId) {
        await api.put(`/parse-strategies/${editingId}`, form)
        toast.success("策略已更新")
      } else {
        await api.post("/parse-strategies", form)
        toast.success("策略已创建")
      }
      setShowDialog(false)
      loadStrategies()
    } catch {
      toast.error("保存失败")
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除该策略吗？")) return
    try {
      await api.delete(`/parse-strategies/${id}`)
      toast.success("策略已删除")
      loadStrategies()
    } catch {
      toast.error("删除失败")
    }
  }

  const handleSetDefault = async (id: string) => {
    try {
      await api.post(`/parse-strategies/${id}/set-default`)
      toast.success("默认策略已设置")
      loadStrategies()
    } catch {
      toast.error("设置失败")
    }
  }

  const modeLabel = (mode: string) =>
    modeOptions.find((m) => m.value === mode)?.label || legacyModeLabels[mode] || mode
  const splitLabel = (method: string) => splitOptions.find((s) => s.value === method)?.label || method

  return (
    <div className="space-y-6">
      <PageHeader />

      {/* ===================== 解析策略 Section ===================== */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#292524] tracking-tight">解析策略</h2>
          <p className="text-sm text-[#a8a29e] mt-1">管理文档解析和分片策略，默认策略将自动应用于新文档</p>
        </div>
        <Button
          onClick={openCreate}
          className="btn-primary-gradient rounded-xl px-4 flex items-center gap-2"
        >
          <Plus className="size-4" />
          新建策略
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-6 animate-spin text-primary" />
        </div>
      ) : strategies.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
            <Layers className="size-8 text-[#a8a29e]" />
          </div>
          <h3 className="text-base font-semibold text-[#44403c] mb-1">暂无策略</h3>
          <p className="text-sm text-[#a8a29e] mb-5">创建第一个解析策略，自动应用于文档解析</p>
          <Button onClick={openCreate} className="btn-primary-gradient rounded-xl px-5">
            <Plus className="size-4 mr-2" />
            新建策略
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {strategies.map((s) => {
            const ModeIcon = modeOptions.find((m) => m.value === s.parse_mode)?.icon || FileText
            return (
              <div
                key={s.id}
                className={cn(
                  "bg-white rounded-2xl border p-5 transition-all hover-lift",
                  s.is_default
                    ? "border-primary ring-2 ring-primary/10"
                    : "border-[#e7e5e4]"
                )}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                      <ModeIcon className="size-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-[#292524]">{s.name}</h3>
                      <p className="text-[10px] text-[#a8a29e]">{modeLabel(s.parse_mode)}</p>
                    </div>
                  </div>
                  {s.is_default && (
                    <span className="px-2 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-medium border border-primary/20 flex items-center gap-1">
                      <Star className="size-3" />
                      默认
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-3 gap-2 mb-4">
                  <div className="p-2 rounded-lg bg-[#fafaf9] border border-[#e7e5e4] text-center">
                    <p className="text-[10px] text-[#a8a29e]">Chunk</p>
                    <p className="text-xs font-semibold text-[#44403c]">{s.chunk_size}</p>
                  </div>
                  <div className="p-2 rounded-lg bg-[#fafaf9] border border-[#e7e5e4] text-center">
                    <p className="text-[10px] text-[#a8a29e]">Overlap</p>
                    <p className="text-xs font-semibold text-[#44403c]">{s.chunk_overlap}</p>
                  </div>
                  <div className="p-2 rounded-lg bg-[#fafaf9] border border-[#e7e5e4] text-center">
                    <p className="text-[10px] text-[#a8a29e]">维度</p>
                    <p className="text-xs font-semibold text-[#44403c]">{s.dimension}</p>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 mb-4 text-[10px] text-[#78716c]">
                  <span className="px-1.5 py-0.5 rounded bg-[#f5f5f4] border border-[#e7e5e4]">
                    {splitLabel(s.split_method)}
                  </span>
                  {s.extract_images && (
                    <span className="px-1.5 py-0.5 rounded bg-purple-50 text-purple-600 border border-purple-100">
                      提取图片
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {!s.is_default && (
                    <button
                      onClick={() => handleSetDefault(s.id)}
                      className="flex-1 h-8 rounded-lg text-xs font-medium text-primary border border-primary/20 hover:bg-primary/5 transition-all flex items-center justify-center gap-1"
                    >
                      <CheckCircle className="size-3.5" />
                      设为默认
                    </button>
                  )}
                  <button
                    onClick={() => openEdit(s)}
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-[#78716c] hover:bg-[#f5f5f4] transition-all"
                    title="编辑"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(s.id)}
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
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

      {/* Create / Edit Dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Layers className="size-5 text-primary" />
              {editingId ? "编辑策略" : "新建策略"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium text-[#44403c] mb-1.5 block">策略名称</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="例如：默认策略"
                className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
              />
            </div>

            <div>
              <label className="text-sm font-medium text-[#44403c] mb-1.5 block">解析模式</label>
              <div className="grid grid-cols-1 gap-2">
                {modeOptions.map((mode) => (
                  <button
                    key={mode.value}
                    onClick={() => setForm((f) => ({ ...f, parse_mode: mode.value }))}
                    className={cn(
                      "flex items-start gap-2 p-2.5 rounded-xl border text-left transition-all",
                      form.parse_mode === mode.value
                        ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                        : "border-[#e7e5e4] hover:border-primary/30"
                    )}
                  >
                    <mode.icon className={cn("size-4 mt-0.5 flex-shrink-0", form.parse_mode === mode.value ? "text-primary" : "text-[#a8a29e]")} />
                    <div>
                      <p className={cn("text-xs font-medium", form.parse_mode === mode.value ? "text-primary" : "text-[#44403c]")}>{mode.label}</p>
                      <p className="text-[10px] text-[#a8a29e] mt-0.5">{mode.desc}</p>
                    </div>
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-[#a8a29e]">
                txt / md / json / csv 等纯文本文件将自动按纯文本解析，无需选择模式
              </p>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-[10px] text-[#a8a29e] mb-1 block">Chunk Size</label>
                <input
                  type="number"
                  min={100}
                  max={4000}
                  step={50}
                  value={form.chunk_size}
                  onChange={(e) => setForm((f) => ({ ...f, chunk_size: Number(e.target.value) }))}
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
                  value={form.chunk_overlap}
                  onChange={(e) => setForm((f) => ({ ...f, chunk_overlap: Number(e.target.value) }))}
                  className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#a8a29e] mb-1 block">向量维度</label>
                <input
                  type="number"
                  min={128}
                  max={4096}
                  step={128}
                  value={form.dimension}
                  onChange={(e) => setForm((f) => ({ ...f, dimension: Number(e.target.value) }))}
                  className="w-full px-2 py-1.5 rounded-lg bg-white border border-[#e7e5e4] text-xs text-[#44403c] outline-none focus:border-primary transition-all"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-[#44403c] mb-1.5 block">切分方式</label>
                <select
                  className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
                  value={form.split_method}
                  onChange={(e) => setForm((f) => ({ ...f, split_method: e.target.value }))}
                >
                  {splitOptions.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm text-[#44403c] cursor-pointer pb-2">
                  <input
                    type="checkbox"
                    checked={form.extract_images}
                    onChange={(e) => setForm((f) => ({ ...f, extract_images: e.target.checked }))}
                    className="rounded border-[#d6d3d1] text-primary focus:ring-primary size-4"
                  />
                  提取图片到 OSS
                </label>
              </div>
            </div>
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
              {editingId ? "保存修改" : "创建策略"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
