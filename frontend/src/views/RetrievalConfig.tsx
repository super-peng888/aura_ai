import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { api } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import PageHeader from "@/components/layout/PageHeader"
import {
  AlertCircle,
  Globe,
  Loader2,
  MapPin,
  Route,
  Save,
  Search,
} from "lucide-react"

// ============================================================================
// Types (与后端 /retrieval-config/ 契约一致)
// ============================================================================

type GraphSearchMode = "auto" | "local" | "global"

interface RetrievalConfig {
  similarity_threshold: number
  enable_query_rewrite: boolean
  enable_keyword_search: boolean
  enable_vector_search: boolean
  enable_rerank: boolean
  enable_graph_rag: boolean
  graph_search_mode: GraphSearchMode
}

const graphSearchModeOptions: {
  value: GraphSearchMode
  label: string
  desc: string
  icon: React.ComponentType<{ className?: string }>
}[] = [
  { value: "auto", label: "自动路由", desc: "根据问题自动选择 Local 或 Global", icon: Route },
  { value: "local", label: "Local 实体关联", desc: "适合具体实体/关系的问题", icon: MapPin },
  { value: "global", label: "Global 社区摘要", desc: "适合全局综述类问题", icon: Globe },
]

// ============================================================================
// Sub-components
// ============================================================================

function FormGroup({
  label,
  children,
  icon: Icon,
  hint,
  error,
}: {
  label: string
  children: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  hint?: string
  error?: string
}) {
  return (
    <div className="space-y-1.5">
      <Label className="flex items-center gap-1.5 text-xs font-medium text-[#78716c]">
        {Icon && <Icon className="size-3.5 text-[#a8a29e]" />}
        {label}
      </Label>
      <div className="relative">{children}</div>
      {hint && !error && <p className="text-[11px] text-[#a8a29e]">{hint}</p>}
      {error && (
        <p className="text-xs text-destructive flex items-center gap-1">
          <AlertCircle className="size-3" />
          {error}
        </p>
      )}
    </div>
  )
}

const inputClass =
  "py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"

// ============================================================================
// Main Page
// ============================================================================

export default function RetrievalConfig() {
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  // 仅含检索策略字段；reranker / embedding / VLM 模型为服务端系统级配置，不在页面可配
  const [config, setConfig] = useState<RetrievalConfig | null>(null)

  const loadConfig = async () => {
    setIsLoading(true)
    try {
      const res = await api.get<RetrievalConfig>("/retrieval-config/")
      if (res) {
        // 后端并行开发中，新字段可能暂未下发，给默认值兜底
        setConfig({
          ...res,
          enable_graph_rag: res.enable_graph_rag ?? false,
          graph_search_mode: res.graph_search_mode ?? "auto",
        })
      }
    } catch {
      // 错误已在 api client 中 toast
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const update = <K extends keyof RetrievalConfig>(key: K, value: RetrievalConfig[K]) => {
    setConfig((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const handleSave = async () => {
    if (!config) return
    setIsSaving(true)
    try {
      // 只提交检索策略字段；模型相关字段由服务端系统级配置维护
      await api.put("/retrieval-config/", config)
      toast.success("检索配置已保存")
      await loadConfig()
    } catch {
      // 错误已在 api client 中 toast
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading && !config) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <PageHeader />
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-6 animate-spin text-primary" />
        </div>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <PageHeader />
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
            <Search className="size-8 text-[#a8a29e]" />
          </div>
          <h3 className="text-base font-semibold text-[#44403c] mb-1">配置加载失败</h3>
          <p className="text-sm text-[#a8a29e] mb-5">请检查网络后重试</p>
          <Button onClick={loadConfig} className="btn-primary-gradient rounded-xl px-5">
            重新加载
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <PageHeader />

      {/* ===================== 检索策略 ===================== */}
      <section className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
        <div className="px-6 py-4 border-b border-[#f5f5f4] flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
            <Search className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#292524]">检索策略</h3>
            <p className="text-xs text-[#a8a29e]">知识检索的召回方式与参数</p>
          </div>
        </div>
        <div className="p-6 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-4">
            {(
              [
                { key: "enable_vector_search", label: "向量检索", desc: "基于向量相似度召回文档分片" },
                { key: "enable_keyword_search", label: "关键词检索", desc: "基于关键词匹配召回文档分片" },
                { key: "enable_query_rewrite", label: "查询改写", desc: "改写用户查询以提升召回效果" },
                { key: "enable_rerank", label: "Rerank 重排序", desc: "对召回结果重新排序提升精度（排序模型由系统管理员在服务端配置）" },
                {
                  key: "enable_graph_rag",
                  label: "GraphRAG 知识图谱",
                  desc: "构建实体关系图谱增强检索（关键字分布在多个文档的多跳问题）；开启后新索引文档将进行实体抽取，索引成本上升",
                },
              ] as const
            ).map((item) => (
              <div
                key={item.key}
                className="flex items-center justify-between p-3 rounded-xl border border-[#e7e5e4] bg-[#fafaf9]"
              >
                <div>
                  <p className="text-sm font-medium text-[#44403c]">{item.label}</p>
                  <p className="text-[11px] text-[#a8a29e] mt-0.5">{item.desc}</p>
                </div>
                <Switch
                  checked={config[item.key]}
                  onCheckedChange={(checked) => update(item.key, checked)}
                />
              </div>
            ))}
          </div>

          {/* 图谱检索方式（未开启 GraphRAG 时置灰） */}
          <div className={cn("transition-opacity", !config.enable_graph_rag && "opacity-60")}>
            <Label className="text-xs font-medium text-[#78716c] mb-1.5 block">
              图谱检索方式
              {!config.enable_graph_rag && (
                <span className="ml-2 font-normal text-[#a8a29e]">需先开启 GraphRAG 知识图谱</span>
              )}
            </Label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {graphSearchModeOptions.map((opt) => (
                <button
                  key={opt.value}
                  disabled={!config.enable_graph_rag}
                  onClick={() => update("graph_search_mode", opt.value)}
                  className={cn(
                    "flex items-start gap-2 p-3 rounded-xl border text-left transition-all disabled:cursor-not-allowed",
                    config.graph_search_mode === opt.value
                      ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                      : "border-[#e7e5e4] hover:border-primary/30"
                  )}
                >
                  <opt.icon
                    className={cn(
                      "size-4 mt-0.5 flex-shrink-0",
                      config.graph_search_mode === opt.value ? "text-primary" : "text-[#a8a29e]"
                    )}
                  />
                  <div>
                    <p
                      className={cn(
                        "text-xs font-medium",
                        config.graph_search_mode === opt.value ? "text-primary" : "text-[#44403c]"
                      )}
                    >
                      {opt.label}
                    </p>
                    <p className="text-[10px] text-[#a8a29e] mt-0.5">{opt.desc}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* 数值参数 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-5 gap-y-4">
            <FormGroup label="相似度阈值" hint="0-1 小数，0 表示不过滤">
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={config.similarity_threshold}
                onChange={(e) => update("similarity_threshold", Number(e.target.value))}
                className={inputClass}
              />
            </FormGroup>
          </div>
        </div>
      </section>

      {/* 保存 */}
      <div className="flex justify-end mb-8">
        <Button
          onClick={handleSave}
          disabled={isSaving || isLoading}
          className="btn-primary-gradient rounded-xl px-6"
        >
          {isSaving ? (
            <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
          ) : (
            <Save className="size-4 mr-2" />
          )}
          保存配置
        </Button>
      </div>
    </div>
  )
}
