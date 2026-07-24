import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { api } from "@/api/client"
import { toast } from "sonner"
import PageHeader from "@/components/layout/PageHeader"
import {
  Sparkles,
  Copy,
  MessageSquare,
  Search,
  BookOpen,
  Code,
  FileText,
  TrendingUp,
  Lightbulb,
  Wand2,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useNavigate } from "react-router-dom"

interface PromptTemplate {
  id: string
  name: string
  content: string
  category?: string
  is_system?: boolean
  created_at?: string
}

const categoryIcons: Record<string, React.ElementType> = {
  文档分析: FileText,
  市场分析: TrendingUp,
  开发: Code,
  学习: BookOpen,
  通用: Sparkles,
}

const categoryColors: Record<string, { bg: string; text: string; border: string }> = {
  文档分析: { bg: "bg-blue-50", text: "text-blue-600", border: "border-blue-100" },
  市场分析: { bg: "bg-emerald-50", text: "text-emerald-600", border: "border-emerald-100" },
  开发: { bg: "bg-purple-50", text: "text-purple-600", border: "border-purple-100" },
  学习: { bg: "bg-amber-50", text: "text-amber-600", border: "border-amber-100" },
  通用: { bg: "bg-[#f5f5f4]", text: "text-[#57534e]", border: "border-[#e7e5e4]" },
}

function getCategoryIcon(category?: string) {
  if (!category) return Sparkles
  return categoryIcons[category] || Sparkles
}

function getCategoryColor(category?: string) {
  if (!category) return categoryColors.通用
  return categoryColors[category] || categoryColors.通用
}

export default function PromptMarket() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    setIsLoading(true)
    api.get<PromptTemplate[]>("/prompt-templates")
      .then((res) => {
        setTemplates(res || [])
      })
      .catch(() => toast.error("加载模板失败"))
      .finally(() => setIsLoading(false))
  }, [])

  const categories = Array.from(new Set(templates.map((t) => t.category || "通用")))

  const filtered = templates.filter((t) => {
    const matchSearch =
      !searchQuery ||
      t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (t.content || "").toLowerCase().includes(searchQuery.toLowerCase())
    const matchCategory = !selectedCategory || (t.category || "通用") === selectedCategory
    return matchSearch && matchCategory
  })

  const handleCopy = (content: string) => {
    navigator.clipboard.writeText(content)
    toast.success("已复制到剪贴板")
  }

  const handleUse = (template: PromptTemplate) => {
    // 携带模板内容跳转到对话页面
    navigate("/chat", { state: { templateContent: template.content, templateName: template.name } })
  }

  return (
    <div className="space-y-6">
      <PageHeader />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#292524] tracking-tight">Prompt 市场</h2>
          <p className="text-sm text-[#a8a29e] mt-1">浏览和使用预设提示词模板，提升对话效率</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
            <input
              type="text"
              placeholder="搜索模板..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-56 pl-9 pr-4 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
            />
          </div>
        </div>
      </div>

      {/* Category Filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setSelectedCategory(null)}
          className={cn(
            "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
            selectedCategory === null
              ? "bg-[#292524] text-white"
              : "bg-white border border-[#e7e5e4] text-[#78716c] hover:border-primary/40 hover:text-primary"
          )}
        >
          全部
        </button>
        {categories.map((cat) => {
          const colors = getCategoryColor(cat)
          return (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all border",
                selectedCategory === cat
                  ? "bg-[#292524] text-white border-[#292524]"
                  : `bg-white ${colors.text} ${colors.border} hover:border-primary/40`
              )}
            >
              {cat}
            </button>
          )
        })}
      </div>

      {/* Templates Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-white rounded-2xl border border-[#e7e5e4] p-5 animate-pulse">
              <div className="w-10 h-10 rounded-xl bg-[#f5f5f4] mb-4" />
              <div className="h-4 bg-[#f5f5f4] rounded w-3/4 mb-2" />
              <div className="h-3 bg-[#f5f5f4] rounded w-full mb-1" />
              <div className="h-3 bg-[#f5f5f4] rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
            <Wand2 className="size-8 text-[#a8a29e]" />
          </div>
          <h3 className="text-base font-semibold text-[#44403c] mb-1">
            {searchQuery || selectedCategory ? "未找到匹配的模板" : "暂无模板"}
          </h3>
          <p className="text-sm text-[#a8a29e] max-w-sm">
            {searchQuery || selectedCategory
              ? "尝试更换搜索关键词或分类筛选"
              : "Prompt 市场还没有模板，系统模板将在解析任务完成后自动添加"}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((template) => {
            const CatIcon = getCategoryIcon(template.category)
            const colors = getCategoryColor(template.category)
            return (
              <div
                key={template.id}
                className="group bg-white rounded-2xl border border-[#e7e5e4] p-5 hover:border-primary/20 hover-lift transition-all flex flex-col"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", colors.bg)}>
                    <CatIcon className={cn("size-5", colors.text)} />
                  </div>
                  {template.is_system && (
                    <span className="px-2 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-medium">
                      系统
                    </span>
                  )}
                </div>

                <h3 className="text-sm font-semibold text-[#292524] mb-2">{template.name}</h3>
                <p className="text-xs text-[#a8a29e] mb-4 line-clamp-3 flex-1">{template.content}</p>

                <div className="flex items-center justify-between pt-3 border-t border-[#f5f5f4]">
                  <span className={cn("px-2 py-0.5 rounded-md text-[10px] font-medium border", colors.bg, colors.text, colors.border)}>
                    {template.category || "通用"}
                  </span>
                  <div className="flex items-center gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 w-7 p-0 rounded-lg"
                      onClick={() => handleCopy(template.content)}
                      title="复制"
                    >
                      <Copy className="size-3.5 text-[#a8a29e]" />
                    </Button>
                    <Button
                      size="sm"
                      className="h-7 rounded-lg text-xs btn-primary-gradient px-3"
                      onClick={() => handleUse(template)}
                    >
                      <MessageSquare className="size-3 mr-1" />
                      使用
                    </Button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
