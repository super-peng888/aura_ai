import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
import { useAuth } from "@/context/AuthContext"
import PageHeader from "@/components/layout/PageHeader"
import { Select } from "antd"
import {
  Plus,
  Trash2,
  Pencil,
  Star,
  CheckCircle,
  Bot,
  Zap,
  Server,
  Key,
  Check,
  Eye,
  EyeOff,
  Cpu,
  Database,
  ListOrdered,
  User as UserIcon,
} from "lucide-react"

// ============================================================================
// 类型（对应 GET /model-providers/ 的 {providers, assignments}）
// ============================================================================

type Capability = "text" | "multi_modal" | "embedding" | "rerank"
type Role = "embedding" | "rerank"

interface ProviderModelInfo {
  id: string
  provider_id: string
  model: string
  capability: Capability
  dimension: number | null
  max_tokens: number | null
  temperature: number | null
  top_p: number | null
  timeout: number | null
}

// 供应商 = base_url + api_key 只配一次；scope=system 系统供应商（仅 admin 可编辑），
// mine=我的私有供应商；key 留空回落环境变量（key_source 标注回落的变量名）
interface Provider {
  id: string
  name: string
  base_url: string
  scope: "system" | "mine"
  key_source: string
  key_configured: boolean
  models: ProviderModelInfo[]
}

const capabilityMeta: Record<Capability, { label: string; badge: string }> = {
  text: { label: "文本", badge: "bg-blue-50 text-blue-600 border-blue-100" },
  multi_modal: { label: "多模态", badge: "bg-purple-50 text-purple-600 border-purple-100" },
  embedding: { label: "向量", badge: "bg-emerald-50 text-emerald-600 border-emerald-100" },
  rerank: { label: "排序", badge: "bg-amber-50 text-amber-600 border-amber-100" },
}

const capabilityOptions: { value: Capability; label: string; desc: string }[] = [
  { value: "text", label: "文本", desc: "纯文本对话模型" },
  { value: "multi_modal", label: "多模态", desc: "支持图片输入，可对话也可作 VLM 解析" },
  { value: "embedding", label: "向量", desc: "文本/多模态向量化（需填维度）" },
  { value: "rerank", label: "排序", desc: "检索结果精排" },
]

// 系统角色指派（仅向量/排序）：未指派回落 .env 默认；
// 对话/VLM 解析非指派制，直接取系统供应商下对应能力的模型
const roleMeta: { role: Role; name: string; desc: string; caps: Capability[]; icon: React.ComponentType<{ className?: string }> }[] = [
  { role: "embedding", name: "向量模型", desc: "文档向量化", caps: ["embedding"], icon: Database },
  { role: "rerank", name: "排序模型", desc: "检索精排", caps: ["rerank"], icon: ListOrdered },
]

// 磨砂透明卡片基础样式
const frostedCard =
  "rounded-2xl border bg-white/60 backdrop-blur-xl shadow-[0_1px_3px_rgba(0,0,0,0.04)] p-5 transition-all hover-lift"

const inputClass =
  "py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm font-mono text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"

// 向量模型预置选项（qwen3-vl-embedding 走 dashscope 多模态路径，其余走 OpenAI /embeddings 文本路径）
const embeddingModelOptions = [
  { value: "text-embedding-v3", label: "text-embedding-v3（文本）" },
  { value: "qwen3.7-text-embedding", label: "qwen3.7-text-embedding（文本）" },
  { value: "qwen3-vl-embedding", label: "qwen3-vl-embedding（多模态）" },
]

function PasswordInput({ placeholder, value, onChange, disabled }: { placeholder: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={cn("w-full pr-10", inputClass)}
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-[#a8a29e] hover:text-[#57534e] transition-colors"
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}

// ============================================================================
// Main Page
// ============================================================================

export default function ModelConfig() {
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const [providers, setProviders] = useState<Provider[]>([])
  const [assignments, setAssignments] = useState<Record<Role, string | null>>({
    embedding: null,
    rerank: null,
  })
  // 当前使用：模型 id 或 "system"（跟随系统默认对话模型）
  const [currentModel, setCurrentModel] = useState<string>("system")
  const [isLoading, setIsLoading] = useState(true)
  const [isSavingCurrent, setIsSavingCurrent] = useState(false)
  const [savingRole, setSavingRole] = useState<Role | null>(null)

  // 供应商弹窗（新建时 scope 由入口决定；编辑时沿用原 scope）
  const [showProviderDialog, setShowProviderDialog] = useState(false)
  const [providerScope, setProviderScope] = useState<"system" | "mine">("mine")
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null)
  const [providerForm, setProviderForm] = useState({ name: "", base_url: "" })
  const [providerKey, setProviderKey] = useState("")
  const [clearProviderKey, setClearProviderKey] = useState(false)
  const [isSavingProvider, setIsSavingProvider] = useState(false)

  // 模型弹窗（挂在某供应商下；私有供应商模型可配对话参数）
  const [showModelDialog, setShowModelDialog] = useState(false)
  const [modelProvider, setModelProvider] = useState<Provider | null>(null)
  const [editingModel, setEditingModel] = useState<ProviderModelInfo | null>(null)
  const [modelForm, setModelForm] = useState({
    model: "",
    capability: "text" as Capability,
    dimension: 1024,
    max_tokens: 4096,
    temperature: 0.7,
    top_p: 0.9,
    timeout: 60,
  })
  const [isSavingModel, setIsSavingModel] = useState(false)

  const load = async () => {
    try {
      const [overviewRes, defaultRes] = await Promise.allSettled([
        api.get<{ providers: Provider[]; assignments: Record<Role, string | null> }>("/model-providers/"),
        api.get<{ provider: string }>("/users/me/default-model"),
      ])
      if (overviewRes.status === "fulfilled" && overviewRes.value) {
        setProviders(overviewRes.value.providers || [])
        setAssignments((prev) => ({ ...prev, ...(overviewRes.value.assignments || {}) }))
      }
      if (defaultRes.status === "fulfilled" && defaultRes.value) {
        setCurrentModel(defaultRes.value.provider || "system")
      }
    } catch {
      // error toast by api client
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const systemProviders = providers.filter((p) => p.scope === "system")
  const myProviders = providers.filter((p) => p.scope === "mine")

  // 所有模型的索引（找指派/当前使用对应的模型与供应商）
  const findModel = (modelId: string | null): { provider: Provider; model: ProviderModelInfo } | null => {
    if (!modelId) return null
    for (const p of providers) {
      const m = p.models.find((x) => x.id === modelId)
      if (m) return { provider: p, model: m }
    }
    return null
  }

  // 对话候选（text / multi_modal，系统 + 私有），用于「当前使用」单选
  const chatCandidates = providers.flatMap((p) =>
    p.models
      .filter((m) => m.capability === "text" || m.capability === "multi_modal")
      .map((m) => ({ provider: p, model: m }))
  )

  // 系统默认对话模型 = 系统供应商下最早的 text 模型，无则回落 multi_modal 模型（后端 chat 回落同逻辑）
  const systemDefaultChat = (() => {
    for (const cap of ["text", "multi_modal"]) {
      for (const p of systemProviders) {
        const m = p.models.find((x) => x.capability === cap)
        if (m) return { provider: p, model: m }
      }
    }
    return null
  })()

  // --------------------------------------------------------------------------
  // 系统角色指派（admin）
  // --------------------------------------------------------------------------

  const handleAssign = async (role: Role, value: string) => {
    setSavingRole(role)
    try {
      const payload: Record<string, unknown> = value
        ? { [role]: value, clear: [] }
        : { clear: [role] }
      const res = await api.put<{ assignments: Record<Role, string | null> }>(
        "/model-providers/assignments",
        payload
      )
      if (res?.assignments) {
        setAssignments((prev) => ({ ...prev, ...res.assignments }))
      }
      toast.success("角色指派已更新")
    } catch {
      // error toast by api client
    } finally {
      setSavingRole(null)
    }
  }

  // --------------------------------------------------------------------------
  // 供应商 CRUD
  // --------------------------------------------------------------------------

  const openCreateProvider = (scope: "system" | "mine") => {
    setEditingProvider(null)
    setProviderScope(scope)
    setProviderForm({
      name: "",
      base_url: scope === "mine" ? "https://api.openai.com/v1" : "https://dashscope.aliyuncs.com/compatible-mode/v1",
    })
    setProviderKey("")
    setClearProviderKey(false)
    setShowProviderDialog(true)
  }

  const openEditProvider = (p: Provider) => {
    setEditingProvider(p)
    setProviderScope(p.scope)
    setProviderForm({ name: p.name, base_url: p.base_url })
    setProviderKey("")
    setClearProviderKey(false)
    setShowProviderDialog(true)
  }

  const handleSaveProvider = async () => {
    if (!providerForm.name.trim() || !providerForm.base_url.trim()) {
      toast.error("请填写供应商名称与 API 端点")
      return
    }
    setIsSavingProvider(true)
    try {
      if (editingProvider) {
        await api.put(`/model-providers/${editingProvider.id}`, {
          name: providerForm.name.trim(),
          base_url: providerForm.base_url.trim(),
          api_key: providerKey.trim() || undefined,
          clear_api_key: clearProviderKey,
        })
        toast.success("供应商已更新")
      } else {
        await api.post("/model-providers/", {
          scope: providerScope,
          name: providerForm.name.trim(),
          base_url: providerForm.base_url.trim(),
          api_key: providerKey.trim() || undefined,
        })
        toast.success("供应商已添加，可继续在其下添加模型")
      }
      setShowProviderDialog(false)
      load()
    } catch {
      // error toast by api client
    } finally {
      setIsSavingProvider(false)
    }
  }

  const handleDeleteProvider = async (p: Provider) => {
    if (
      !confirm(
        `确定删除供应商「${p.name}」吗？其下 ${p.models.length} 个模型将一并删除，` +
          `占用的系统角色指派与用户「当前使用」绑定将回落系统默认。`
      )
    )
      return
    try {
      await api.delete(`/model-providers/${p.id}`)
      toast.success("供应商已删除")
      load()
    } catch {
      // error toast by api client
    }
  }

  // --------------------------------------------------------------------------
  // 模型 CRUD
  // --------------------------------------------------------------------------

  const openCreateModel = (p: Provider) => {
    setModelProvider(p)
    setEditingModel(null)
    setModelForm({
      model: "",
      capability: "text",
      dimension: 1024,
      max_tokens: 4096,
      temperature: 0.7,
      top_p: 0.9,
      timeout: 60,
    })
    setShowModelDialog(true)
  }

  const openEditModel = (p: Provider, m: ProviderModelInfo) => {
    setModelProvider(p)
    setEditingModel(m)
    setModelForm({
      model: m.model,
      capability: m.capability,
      dimension: m.dimension ?? 1024,
      max_tokens: m.max_tokens ?? 4096,
      temperature: m.temperature ?? 0.7,
      top_p: m.top_p ?? 0.9,
      timeout: m.timeout ?? 60,
    })
    setShowModelDialog(true)
  }

  const handleSaveModel = async () => {
    if (!modelProvider) return
    if (!modelForm.model.trim()) {
      toast.error("请填写模型名称")
      return
    }
    setIsSavingModel(true)
    try {
      const isMine = modelProvider.scope === "mine"
      const isChatLike = modelForm.capability === "text" || modelForm.capability === "multi_modal"
      const payload = {
        model: modelForm.model.trim(),
        capability: modelForm.capability,
        dimension: modelForm.capability === "embedding" ? modelForm.dimension : undefined,
        // 对话参数仅私有对话模型携带（系统模型统一走默认参数）
        max_tokens: isMine && isChatLike ? modelForm.max_tokens : undefined,
        temperature: isMine && isChatLike ? modelForm.temperature : undefined,
        top_p: isMine && isChatLike ? modelForm.top_p : undefined,
        timeout: isMine && isChatLike ? modelForm.timeout : undefined,
      }
      if (editingModel) {
        await api.put(`/model-providers/models/${editingModel.id}`, payload)
        toast.success("模型已更新")
      } else {
        await api.post(`/model-providers/${modelProvider.id}/models`, payload)
        toast.success("模型已添加")
      }
      setShowModelDialog(false)
      load()
    } catch {
      // 重复模型等错误 toast 由 api client 处理
    } finally {
      setIsSavingModel(false)
    }
  }

  const handleDeleteModel = async (m: ProviderModelInfo) => {
    if (
      !confirm(
        `确定删除模型「${m.model}」吗？指派了它的系统角色与正在使用它的用户将回落系统默认。`
      )
    )
      return
    try {
      await api.delete(`/model-providers/models/${m.id}`)
      if (currentModel === m.id) setCurrentModel("system")
      toast.success("模型已删除")
      load()
    } catch {
      // error toast by api client
    }
  }

  // --------------------------------------------------------------------------
  // 当前使用（对话模型）
  // --------------------------------------------------------------------------

  const handleSetCurrent = async (value: string) => {
    setIsSavingCurrent(true)
    try {
      await api.put("/users/me/default-model", { provider: value })
      setCurrentModel(value)
      toast.success(value === "system" ? "已切换为跟随系统默认" : "已切换当前使用模型")
    } catch {
      // error toast by api client
    } finally {
      setIsSavingCurrent(false)
    }
  }

  // --------------------------------------------------------------------------
  // 渲染
  // --------------------------------------------------------------------------

  const renderModelRow = (p: Provider, m: ProviderModelInfo, canEdit: boolean) => {
    const meta = capabilityMeta[m.capability]
    return (
      <div
        key={m.id}
        className="flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-white/50 border border-black/5"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-mono font-medium text-[#44403c] truncate">{m.model}</span>
          <span className={cn("px-1.5 py-0.5 rounded border text-[10px] shrink-0", meta.badge)}>
            {meta.label}
          </span>
          {m.dimension != null && (
            <span className="px-1.5 py-0.5 rounded bg-black/5 border border-black/5 text-[10px] text-[#78716c] shrink-0">
              维度 {m.dimension}
            </span>
          )}
        </div>
        {canEdit && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => openEditModel(p, m)}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-[#78716c] hover:bg-black/5 transition-all"
              title="编辑模型"
            >
              <Pencil className="size-3.5" />
            </button>
            <button
              onClick={() => handleDeleteModel(m)}
              className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
              title="删除模型"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        )}
      </div>
    )
  }

  const renderProviderCard = (p: Provider, canEdit: boolean) => (
    <div key={p.id} className={cn(frostedCard, "border-white/60")}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 shrink-0 rounded-xl bg-blue-100 flex items-center justify-center">
            <Server className="size-5 text-blue-600" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[#292524] truncate">{p.name}</h3>
            <p className="text-[10px] text-[#a8a29e] font-mono truncate max-w-[240px]">{p.base_url}</p>
          </div>
        </div>
        {canEdit && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => openEditProvider(p)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-[#78716c] hover:bg-black/5 transition-all"
              title="编辑供应商"
            >
              <Pencil className="size-3.5" />
            </button>
            <button
              onClick={() => handleDeleteProvider(p)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
              title="删除供应商"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        )}
      </div>

      <div className="flex items-center flex-wrap gap-1.5 mb-3 text-[10px] text-[#78716c]">
        <span
          className={cn(
            "px-1.5 py-0.5 rounded border flex items-center gap-1",
            p.key_configured
              ? "bg-emerald-50 text-emerald-600 border-emerald-100"
              : "bg-red-50 text-red-500 border-red-100"
          )}
        >
          <Key className="size-3" />
          {p.key_configured ? `${p.key_source} 已配置` : `${p.key_source} 未配置`}
        </span>
        <span className="px-1.5 py-0.5 rounded bg-black/5 border border-black/5">
          {p.models.length} 个模型
        </span>
      </div>

      <div className="space-y-1.5">
        {p.models.map((m) => renderModelRow(p, m, canEdit))}
        {p.models.length === 0 && (
          <p className="text-[11px] text-[#a8a29e] px-1">暂无模型</p>
        )}
        {canEdit && (
          <button
            onClick={() => openCreateModel(p)}
            className="w-full h-8 rounded-xl text-xs font-medium text-[#78716c] border border-dashed border-[#d6d3d1] hover:border-primary/40 hover:text-primary transition-all flex items-center justify-center gap-1"
          >
            <Plus className="size-3.5" />
            添加模型
          </button>
        )}
      </div>
    </div>
  )

  const isChatLikeForm = modelForm.capability === "text" || modelForm.capability === "multi_modal"

  return (
    <div className="space-y-6 pb-10">
      <PageHeader />

      {isLoading ? (
        <div className="py-10 flex items-center justify-center">
          <div className="size-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : (
        <>
          {/* ===================== 系统角色指派 ===================== */}
          <section className="space-y-3">
            <div className="flex items-center gap-2 px-1">
              <Cpu className="size-4 text-blue-600" />
              <h3 className="text-sm font-semibold text-[#292524]">系统角色指派</h3>
              <span className="text-xs text-[#a8a29e] hidden sm:inline">
                向量 / 排序两个系统角色指到具体模型；未指派回落 .env 默认，仅管理员可修改
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {roleMeta.map(({ role, name, desc, caps, icon: Icon }) => {
                const assigned = findModel(assignments[role])
                // 只能指派系统供应商下能力匹配的模型
                const options = systemProviders.flatMap((p) =>
                  p.models
                    .filter((m) => caps.includes(m.capability))
                    .map((m) => ({ id: m.id, label: `${p.name} / ${m.model}` }))
                )
                return (
                  <div key={role} className={cn(frostedCard, "border-white/60")}>
                    <div className="flex items-center gap-2.5 mb-3">
                      <div className="w-9 h-9 shrink-0 rounded-xl bg-blue-100 flex items-center justify-center">
                        <Icon className="size-4.5 text-blue-600" />
                      </div>
                      <div className="min-w-0">
                        <h4 className="text-sm font-semibold text-[#292524]">{name}</h4>
                        <p className="text-[10px] text-[#a8a29e]">{desc}</p>
                      </div>
                    </div>
                    {isAdmin ? (
                      <Select
                        className="w-full"
                        value={assignments[role] ?? ""}
                        disabled={savingRole === role}
                        loading={savingRole === role}
                        onChange={(v) => handleAssign(role, v)}
                        options={[
                          { value: "", label: "跟随 .env 默认" },
                          ...options.map((o) => ({ value: o.id, label: o.label })),
                          ...(assignments[role] && !options.some((o) => o.id === assignments[role])
                            ? [{ value: assignments[role]!, label: "已失效的指派（将回落 .env）" }]
                            : []),
                        ]}
                      />
                    ) : (
                      <p className="text-xs font-mono text-[#57534e] px-1 truncate">
                        {assigned ? `${assigned.provider.name} / ${assigned.model.model}` : "跟随 .env 默认"}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          {/* ===================== 系统供应商 ===================== */}
          <section className="space-y-3">
            <div className="flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <Bot className="size-4 text-purple-600" />
                <h3 className="text-sm font-semibold text-[#292524]">系统供应商</h3>
                <span className="text-xs text-[#a8a29e] hidden sm:inline">
                  base_url 与 Key 只配一次，模型挂在供应商下；仅管理员可增删改
                </span>
              </div>
              {isAdmin && (
                <Button
                  onClick={() => openCreateProvider("system")}
                  variant="outline"
                  className="rounded-xl px-4 flex items-center gap-2 text-xs border-[#e7e5e4] text-[#57534e] hover:bg-[#f5f5f4]"
                >
                  <Plus className="size-3.5" />
                  添加系统供应商
                </Button>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {systemProviders.map((p) => renderProviderCard(p, isAdmin))}
            </div>
            {systemProviders.length === 0 && (
              <p className="text-xs text-[#a8a29e] px-1">暂无系统供应商</p>
            )}
          </section>

          {/* ===================== 我的供应商 ===================== */}
          <section className="space-y-3">
            <div className="flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <UserIcon className="size-4 text-emerald-600" />
                <h3 className="text-sm font-semibold text-[#292524]">我的供应商</h3>
                <span className="text-xs text-[#a8a29e] hidden sm:inline">
                  你的私有模型接入，仅自己可见；文本/多模态模型可设为当前使用
                </span>
              </div>
              <Button
                onClick={() => openCreateProvider("mine")}
                className="btn-primary-gradient rounded-xl px-4 flex items-center gap-2 text-xs"
              >
                <Plus className="size-3.5" />
                添加我的供应商
              </Button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {myProviders.map((p) => renderProviderCard(p, true))}
            </div>
            {myProviders.length === 0 && (
              <p className="text-xs text-[#a8a29e] px-1">暂无私有供应商，可添加自己的模型接入</p>
            )}
          </section>

          {/* ===================== 当前使用（对话模型） ===================== */}
          <section className="space-y-3">
            <div className="flex items-center gap-2 px-1">
              <Zap className="size-4 text-amber-500" />
              <h3 className="text-sm font-semibold text-[#292524]">当前使用</h3>
              <span className="text-xs text-[#a8a29e] hidden sm:inline">
                选择你对话时使用的模型（文本/多模态），或跟随系统默认
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {/* 跟随系统默认 */}
              <div
                className={cn(
                  frostedCard,
                  currentModel === "system" ? "border-primary/60 ring-2 ring-primary/10" : "border-white/60"
                )}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 shrink-0 rounded-xl bg-primary/10 flex items-center justify-center">
                      <Star className="size-5 text-primary" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-[#292524]">跟随系统默认</h3>
                      <p className="text-[10px] text-[#a8a29e] truncate max-w-[200px]">
                        {systemDefaultChat
                          ? `当前为 ${systemDefaultChat.model.model}`
                          : "当前回落 .env 默认对话模型"}
                      </p>
                    </div>
                  </div>
                  {currentModel === "system" && (
                    <span className="px-2 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-medium border border-primary/20 flex items-center gap-1 shrink-0">
                      <Star className="size-3" />
                      当前使用
                    </span>
                  )}
                </div>
                {currentModel !== "system" && (
                  <button
                    onClick={() => handleSetCurrent("system")}
                    disabled={isSavingCurrent}
                    className="w-full h-8 mt-2 rounded-lg text-xs font-medium text-primary border border-primary/20 hover:bg-primary/5 transition-all flex items-center justify-center gap-1"
                  >
                    <CheckCircle className="size-3.5" />
                    设为当前使用
                  </button>
                )}
              </div>

              {/* 所有可见的 chat / multi_modal 模型 */}
              {chatCandidates.map(({ provider: p, model: m }) => {
                const isCurrent = currentModel === m.id
                const meta = capabilityMeta[m.capability]
                return (
                  <div
                    key={m.id}
                    className={cn(frostedCard, isCurrent ? "border-primary/60 ring-2 ring-primary/10" : "border-white/60")}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 shrink-0 rounded-xl bg-blue-100 flex items-center justify-center">
                          <Zap className="size-5 text-blue-600" />
                        </div>
                        <div className="min-w-0">
                          <h3 className="text-sm font-semibold text-[#292524] truncate">{m.model}</h3>
                          <p className="text-[10px] text-[#a8a29e] font-mono truncate max-w-[200px]">{p.name}</p>
                        </div>
                      </div>
                      {isCurrent && (
                        <span className="px-2 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-medium border border-primary/20 flex items-center gap-1 shrink-0">
                          <Star className="size-3" />
                          当前使用
                        </span>
                      )}
                    </div>
                    <div className="flex items-center flex-wrap gap-1.5 text-[10px] text-[#78716c]">
                      <span className={cn("px-1.5 py-0.5 rounded border", meta.badge)}>{meta.label}</span>
                      <span
                        className={cn(
                          "px-1.5 py-0.5 rounded border",
                          p.scope === "mine"
                            ? "bg-emerald-50 text-emerald-600 border-emerald-100"
                            : "bg-black/5 border-black/5"
                        )}
                      >
                        {p.scope === "mine" ? "我的" : "系统"}
                      </span>
                    </div>
                    {!isCurrent && (
                      <button
                        onClick={() => handleSetCurrent(m.id)}
                        disabled={isSavingCurrent}
                        className="w-full h-8 mt-3 rounded-lg text-xs font-medium text-primary border border-primary/20 hover:bg-primary/5 transition-all flex items-center justify-center gap-1"
                      >
                        <CheckCircle className="size-3.5" />
                        设为当前使用
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        </>
      )}

      {/* ===================== 供应商弹窗 ===================== */}
      <Dialog open={showProviderDialog} onOpenChange={setShowProviderDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Server className="size-5 text-blue-600" />
              {editingProvider
                ? `编辑供应商「${editingProvider.name}」`
                : providerScope === "system"
                  ? "添加系统供应商"
                  : "添加我的供应商"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-[#78716c]">供应商名称</Label>
              <Input
                value={providerForm.name}
                onChange={(e) => setProviderForm((prev) => ({ ...prev, name: e.target.value }))}
                placeholder="例如：阿里云百炼、DeepSeek、OpenAI"
                className={inputClass}
              />
            </div>

            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5 text-xs font-medium text-[#78716c]">
                <Server className="size-3.5 text-[#a8a29e]" />
                Base URL
              </Label>
              <Input
                value={providerForm.base_url}
                onChange={(e) => setProviderForm((prev) => ({ ...prev, base_url: e.target.value }))}
                placeholder="https://api.example.com/v1"
                className={inputClass}
              />
            </div>

            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5 text-xs font-medium text-[#78716c]">
                <Key className="size-3.5 text-[#a8a29e]" />
                API Key
              </Label>
              <PasswordInput
                placeholder={editingProvider ? "留空保持当前配置" : "留空回落环境变量"}
                value={providerKey}
                onChange={setProviderKey}
                disabled={clearProviderKey}
              />
              {editingProvider ? (
                <label className="flex items-center gap-2 cursor-pointer select-none pt-1">
                  <input
                    type="checkbox"
                    checked={clearProviderKey}
                    onChange={(e) => setClearProviderKey(e.target.checked)}
                    className="size-4 rounded border-[#e7e5e4] accent-[var(--primary)]"
                  />
                  <span className="text-[11px] text-[#78716c]">清除自定义 Key，回落环境变量</span>
                </label>
              ) : (
                <p className="text-[11px] text-[#a8a29e]">
                  Key 将被加密存储，供应商下所有模型共用；留空回落环境变量
                  （DeepSeek 端点 → DEEPSEEK_API_KEY，其余 → DASHSCOPE_API_KEY）
                </p>
              )}
            </div>
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setShowProviderDialog(false)}
              className="rounded-xl border-[#e7e5e4] text-[#57534e] hover:bg-[#f5f5f4]"
            >
              取消
            </Button>
            <Button
              onClick={handleSaveProvider}
              disabled={isSavingProvider}
              className="btn-primary-gradient rounded-xl"
            >
              {isSavingProvider ? (
                <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Check className="size-4 mr-2" />
              )}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ===================== 模型弹窗 ===================== */}
      <Dialog open={showModelDialog} onOpenChange={setShowModelDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Cpu className="size-5 text-blue-600" />
              {editingModel ? "编辑模型" : `添加模型到「${modelProvider?.name ?? ""}」`}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-[#78716c]">能力</Label>
              <div className="grid grid-cols-2 gap-2">
                {capabilityOptions.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setModelForm((prev) => ({ ...prev, capability: opt.value }))}
                    className={cn(
                      "flex flex-col items-start p-2.5 rounded-xl border text-left transition-all",
                      modelForm.capability === opt.value
                        ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                        : "border-[#e7e5e4] hover:border-primary/30"
                    )}
                  >
                    <span
                      className={cn(
                        "text-xs font-medium",
                        modelForm.capability === opt.value ? "text-primary" : "text-[#44403c]"
                      )}
                    >
                      {opt.label}
                    </span>
                    <span className="text-[10px] text-[#a8a29e] mt-0.5">{opt.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-[#78716c]">模型名称</Label>
              {modelForm.capability === "embedding" ? (
                <Select
                  className="w-full"
                  placeholder="选择向量模型"
                  value={modelForm.model || undefined}
                  onChange={(v) => setModelForm((prev) => ({ ...prev, model: v }))}
                  options={[
                    ...embeddingModelOptions.map((opt) => ({ value: opt.value, label: opt.label })),
                    ...(modelForm.model && !embeddingModelOptions.some((opt) => opt.value === modelForm.model)
                      ? [{ value: modelForm.model, label: modelForm.model }]
                      : []),
                  ]}
                />
              ) : (
                <Input
                  value={modelForm.model}
                  onChange={(e) => setModelForm((prev) => ({ ...prev, model: e.target.value }))}
                  placeholder={
                    modelForm.capability === "rerank"
                      ? "例如：qwen3-rerank"
                      : "例如：qwen3.7-plus、deepseek-v4-flash、gpt-4o"
                  }
                  className={inputClass}
                />
              )}
            </div>

            {modelForm.capability === "embedding" && (
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-[#78716c]">向量维度</Label>
                <Input
                  type="number"
                  min="128"
                  max="4096"
                  value={modelForm.dimension}
                  onChange={(e) =>
                    setModelForm((prev) => ({ ...prev, dimension: parseInt(e.target.value) || prev.dimension }))
                  }
                  className={inputClass}
                />
                <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5">
                  ⚠️ 更换向量模型或维度后，需重建向量库并重新索引已有文档，否则检索会失败
                </p>
              </div>
            )}

            {/* 对话参数：仅私有供应商的对话/多模态模型 */}
            {modelProvider?.scope === "mine" && isChatLikeForm && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-[#78716c]">Temperature</Label>
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={modelForm.temperature}
                    onChange={(e) => setModelForm((prev) => ({ ...prev, temperature: parseFloat(e.target.value) }))}
                    className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-[#78716c]">Max Tokens</Label>
                  <Input
                    type="number"
                    min="1"
                    max="128000"
                    value={modelForm.max_tokens}
                    onChange={(e) => setModelForm((prev) => ({ ...prev, max_tokens: parseInt(e.target.value) }))}
                    className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-[#78716c]">Top P</Label>
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    value={modelForm.top_p}
                    onChange={(e) => setModelForm((prev) => ({ ...prev, top_p: parseFloat(e.target.value) }))}
                    className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-[#78716c]">Timeout (s)</Label>
                  <Input
                    type="number"
                    min="1"
                    max="300"
                    value={modelForm.timeout}
                    onChange={(e) => setModelForm((prev) => ({ ...prev, timeout: parseInt(e.target.value) }))}
                    className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                  />
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setShowModelDialog(false)}
              className="rounded-xl border-[#e7e5e4] text-[#57534e] hover:bg-[#f5f5f4]"
            >
              取消
            </Button>
            <Button
              onClick={handleSaveModel}
              disabled={isSavingModel}
              className="btn-primary-gradient rounded-xl"
            >
              {isSavingModel ? (
                <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Check className="size-4 mr-2" />
              )}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
