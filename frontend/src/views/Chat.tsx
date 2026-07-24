import { useCallback, useEffect, useRef, useState } from "react"
import { useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Streamdown } from "streamdown"
import { cjk } from "@streamdown/cjk"
import { code } from "@streamdown/code"
import { math } from "@streamdown/math"
import { mermaid } from "@streamdown/mermaid"
import type { FileUIPart } from "ai"
import { api, fetchStream } from "@/api/client"
import { toast } from "sonner"
import {
  SpeechInput,
} from "@/components/ai-elements/speech-input"
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputSubmit,
  PromptInputTools,
  PromptInputButton,
  PromptInputHeader,
  PromptInputBody,
  PromptInputFooter,
  usePromptInputAttachments,
  type PromptInputMessage,
  PromptInputProvider,
} from "@/components/ai-elements/prompt-input"
import {
  Attachments,
  Attachment,
  AttachmentPreview,
  AttachmentRemove,
} from "@/components/ai-elements/attachments"
import {
  Plus,
  MoreHorizontal,
  FileText,
  ChevronDown,
  Bot,
  User,
  Table,
  BookOpen,
  ArrowUp,
  Copy,
  ThumbsUp,
  ThumbsDown,
  Paperclip,
  X,
  PanelLeftClose,
  PanelRightClose,
  PanelRightOpen,
  ChevronRight,
  Wand2,
  Check,
  Share2,
  Download,
  Pencil,
  Trash2,
} from "lucide-react"
import PageHeader from "@/components/layout/PageHeader"
import EChartsCard from "@/components/ai-elements/echarts-card"
import sendIcon from "@/assets/send.svg"
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom"

// ============================================================================
// Types
// ============================================================================

interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

interface ChartConfig {
  title: string
  type: string
  option: Record<string, unknown>
}

interface TableConfig {
  title: string
  headers: string[]
  rows: (string | number)[][]
}

interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  attachments?: FileUIPart[]
  sql?: string
  queryResult?: { columns?: string[]; rows?: unknown[][]; row_count?: number; error?: string }
  queryError?: string
  charts?: ChartConfig[]
  tables?: TableConfig[]
}

interface Citation {
  id: string
  title: string
  source: string
  url: string
}

// ============================================================================
// Mock Data
// ============================================================================

// 从 API 加载会话列表

const streamdownPlugins = { cjk, code, math, mermaid }

// ============================================================================
// SSE 解析工具
// ============================================================================

async function readSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: string, data: unknown) => void
) {
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split("\n")
    buffer = lines.pop() || ""

    let currentEvent = ""
    let currentData = ""

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim()
      } else if (line.startsWith("data:")) {
        currentData = line.slice(5).trim()
      } else if (line.trim() === "" && currentEvent) {
        try {
          const parsed = JSON.parse(currentData)
          onEvent(currentEvent, parsed)
        } catch {
          onEvent(currentEvent, currentData)
        }
        currentEvent = ""
        currentData = ""
      }
    }

    if (currentEvent || currentData) {
      buffer = `event: ${currentEvent}\ndata: ${currentData}\n` + buffer
    }
  }
}

// ============================================================================
// Sub-components
// ============================================================================

function ScrollToBottomButton() {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext()
  if (isAtBottom) return null
  return (
    <button
      onClick={() => scrollToBottom()}
      className="absolute bottom-4 left-1/2 -translate-x-1/2 glass-card-strong rounded-full p-2 hover:bg-[#f5f5f4] transition-colors z-10"
    >
      <ArrowUp className="size-4 rotate-180 text-muted-foreground" />
    </button>
  )
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert">
      <Streamdown plugins={streamdownPlugins}>{content}</Streamdown>
    </div>
  )
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user"

  return (
    <div className={cn("group flex w-full gap-3", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={cn(
          "shrink-0 size-7 rounded-full flex items-center justify-center mt-0.5",
          isUser ? "bg-secondary text-secondary-foreground" : "bg-primary/10 text-primary"
        )}
      >
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </div>

      <div className={cn("flex flex-col gap-1.5 max-w-[85%]", isUser ? "items-end" : "items-start")}>
        {message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-1">
            {message.attachments.map((att, idx) => (
              <div key={idx} className="flex items-center gap-2 glass-card rounded-lg px-3 py-2 text-xs">
                <FileText className="size-3.5 text-primary" />
                <span className="font-medium">{att.filename || "附件"}</span>
                <span className="text-muted-foreground">{att.mediaType}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs font-semibold text-[#44403c]">{isUser ? "王鹏" : "Aura AI"}</span>
          <span className="text-[10px] text-[#a8a29e]">14:33</span>
          {!isUser && (
            <span className="px-1.5 py-0.5 rounded-md bg-accent-50 text-accent-600 text-[9px] font-medium border border-accent-100">
              <Check className="size-2.5 inline mr-0.5" />已引用文档
            </span>
          )}
        </div>

        <div
          className={cn(
            "px-4 py-3 text-sm leading-relaxed",
            isUser
              ? "bg-secondary text-secondary-foreground rounded-2xl rounded-tr-sm"
              : "glass-card rounded-2xl rounded-tl-sm"
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="space-y-3">
              <MarkdownContent content={message.content} />

              {/* Data Agent: SQL */}
              {message.sql && (
                <div className="bg-[#1e1e1e] rounded-xl p-3 overflow-x-auto mt-2">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-semibold text-[#a8a29e] uppercase tracking-wider">Generated SQL</span>
                    <span className="text-[10px] text-emerald-400 font-medium">只读查询 · 安全执行</span>
                  </div>
                  <pre className="text-xs text-emerald-300 font-mono leading-relaxed">{message.sql}</pre>
                </div>
              )}

              {/* Data Agent: Query Error */}
              {message.queryError && (
                <div className="bg-red-50 border border-red-100 rounded-xl p-3 mt-2">
                  <p className="text-xs font-semibold text-red-600 mb-1">查询执行失败</p>
                  <p className="text-xs text-red-500">{message.queryError}</p>
                </div>
              )}

              {/* Data Agent: Query Result */}
              {message.queryResult && message.queryResult.columns && message.queryResult.rows && (
                <div className="mt-2 overflow-x-auto">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-[#44403c]">查询结果</span>
                    <span className="text-[10px] text-[#a8a29e]">共 {message.queryResult.row_count ?? message.queryResult.rows.length} 行</span>
                  </div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#e7e5e4]">
                        {message.queryResult.columns.map((h, hi) => (
                          <th key={hi} className="text-left py-1.5 px-2 text-[#a8a29e] font-semibold uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {message.queryResult.rows.map((row, ri) => (
                        <tr key={ri} className="border-b border-[#f5f5f4] last:border-0">
                          {Array.isArray(row) && row.map((cell, ci) => (
                            <td key={ci} className="py-1.5 px-2 text-[#44403c] font-mono">{String(cell)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Data Agent: Charts */}
              {message.charts?.map((chart, cidx) => (
                chart.option && typeof chart.option === "object" && (
                  <div key={cidx} className="mt-2">
                    <EChartsCard id={`chart_chat_${message.id}_${cidx}`} title={chart.title} option={chart.option} height={280} />
                  </div>
                )
              ))}

              {/* Data Agent: Tables */}
              {message.tables?.map((table, tidx) => (
                <div key={tidx} className="mt-2 overflow-x-auto">
                  <p className="text-xs font-semibold text-[#44403c] mb-2">{table.title}</p>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[#e7e5e4]">
                        {table.headers?.map((h, hi) => (
                          <th key={hi} className="text-left py-1.5 px-2 text-[#a8a29e] font-semibold uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows?.map((row, ri) => (
                        <tr key={ri} className="border-b border-[#f5f5f4] last:border-0">
                          {Array.isArray(row) && row.map((cell, ci) => (
                            <td key={ci} className="py-1.5 px-2 text-[#44403c]">{String(cell)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>

        {!isUser && (
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all" title="复制"><Copy className="size-3" /></button>
            <button className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all" title="点赞"><ThumbsUp className="size-3" /></button>
            <button className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all" title="重试"><ThumbsDown className="size-3" /></button>
          </div>
        )}
      </div>
    </div>
  )
}

const PromptInputAttachmentsDisplay = () => {
  const attachments = usePromptInputAttachments()
  const handleRemove = useCallback(
    (id: string) => {
      attachments.remove(id)
    },
    [attachments]
  )
  if (attachments.files.length === 0) return null
  return (
    <Attachments variant="inline">
      {attachments.files.map((attachment) => (
        <Attachment key={attachment.id} data={attachment} onRemove={() => handleRemove(attachment.id)}>
          <AttachmentPreview />
          <AttachmentRemove />
        </Attachment>
      ))}
    </Attachments>
  )
}

function AttachmentButton() {
  const attachments = usePromptInputAttachments()
  return (
    <PromptInputButton
      type="button"
      variant="ghost"
      size="icon-sm"
      className="flex items-center justify-center size-8 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
      title="添加附件"
      onClick={() => attachments.openFileDialog()}
    >
      <Paperclip className="size-4" />
    </PromptInputButton>
  )
}

// ============================================================================
// Main Chat Page
// ============================================================================

export default function Chat() {
  const location = useLocation()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [status, setStatus] = useState<"ready" | "submitted" | "streaming">("ready")
  const [citations, setCitations] = useState<Citation[]>([])
  const [structuredOutput, setStructuredOutput] = useState<Array<{ key: string; value: string; confidence: number }>>([])

  // 面板展开/收起状态
  const [convPanelOpen, setConvPanelOpen] = useState(true)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [templates, setTemplates] = useState<{ id: string; name: string; content: string; category?: string }[]>([])
  const [showTemplateDropdown, setShowTemplateDropdown] = useState(false)
  const [initialInput, setInitialInput] = useState("")

  // 对话编辑状态
  const [editingConvId, setEditingConvId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState("")

  const templateDropdownRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<boolean>(false)
  const conversationsRef = useRef(conversations)
  useEffect(() => {
    conversationsRef.current = conversations
  }, [conversations])

  // 从 Prompt 市场传入的模板内容
  useEffect(() => {
    const tpl = location.state?.templateContent as string | undefined
    if (tpl) {
      requestAnimationFrame(() => setInitialInput(tpl))
      window.history.replaceState({}, document.title)
    }
  }, [location.state])

  // 加载模板列表
  useEffect(() => {
    api.get<{ id: string; name: string; content: string; category?: string }[]>("/prompt-templates")
      .then((res) => setTemplates(res || []))
      .catch(() => {})
  }, [])

  // 加载会话列表
  useEffect(() => {
    api.get<Conversation[]>("/conversations")
      .then((res) => {
        requestAnimationFrame(() => {
          setConversations(res || [])
          if (res && res.length > 0) {
            setActiveConversationId(res[0].id)
          }
        })
      })
      .catch(() => toast.error("加载会话失败"))
  }, [])

  // 加载当前会话消息
  useEffect(() => {
    if (!activeConversationId) {
      requestAnimationFrame(() => setMessages([]))
      return
    }
    api.get<{ id: string; role: string; content: string; created_at: string }[]>(`/conversations/${activeConversationId}/messages`)
      .then((res) => {
        requestAnimationFrame(() => {
          setMessages(
            (res || []).map((m) => ({
              id: m.id,
              role: m.role as "user" | "assistant",
              content: m.content,
            }))
          )
        })
      })
      .catch(() => toast.error("加载消息失败"))
  }, [activeConversationId])

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (templateDropdownRef.current && !templateDropdownRef.current.contains(event.target as Node)) {
        setShowTemplateDropdown(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  const handleUpdateTitle = useCallback(async (convId: string, title: string) => {
    try {
      await api.put(`/conversations/${convId}`, { title })
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, title } : c))
      )
      setEditingConvId(null)
      toast.success("对话名已更新")
    } catch {
      toast.error("更新对话名失败")
    }
  }, [])

  const handleDeleteConversation = useCallback(async (convId: string) => {
    if (!confirm("确定要删除该对话吗？")) return
    try {
      await api.delete(`/conversations/${convId}`)
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== convId)
        if (convId === activeConversationId) {
          if (next.length > 0) {
            setActiveConversationId(next[0].id)
          } else {
            setActiveConversationId(null)
            setMessages([])
          }
        }
        return next
      })
      toast.success("对话已删除")
    } catch {
      toast.error("删除对话失败")
    }
  }, [activeConversationId])

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (!message.text.trim() && message.files.length === 0) return
      if (status !== "ready") return

      // 上传附件到 OSS
      const uploadedAttachments: { filename: string; url: string; mediaType: string; type: "file" }[] = []
      if (message.files.length > 0) {
        for (const file of message.files) {
          try {
            const blob = await fetch(file.url).then((r) => r.blob())
            const formData = new FormData()
            formData.append("file", blob, file.filename || "file")
            const res = await api.post<{ oss_url: string; original_name: string }>("/uploads/document", formData)
            uploadedAttachments.push({
              filename: res.original_name || file.filename || "file",
              url: res.oss_url,
              mediaType: file.mediaType || blob.type || "application/octet-stream",
              type: "file" as const,
            })
          } catch {
            toast.error(`上传附件 ${file.filename} 失败`)
          }
        }
      }

      const newMessage: ChatMessage = {
        id: `m${Date.now()}`,
        role: "user",
        content: message.text,
        attachments: uploadedAttachments.length > 0 ? uploadedAttachments : undefined,
      }

      setMessages((prev) => [...prev, newMessage])
      setStatus("submitted")
      setCitations([])
      setStructuredOutput([])
      abortRef.current = false

      const assistantId = `a${Date.now()}`
      setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }])

      try {
        const reader = await fetchStream("/chat/stream", {
          conversation_id: activeConversationId,
          messages: [{ role: "user", content: message.text }],
          temperature: 0.7,
          stream: true,
          attachments: uploadedAttachments,
        })

        setStatus("streaming")

        // 用于累积 Data Agent 输出的临时状态
        let currentSql = ""
        let currentQueryResult: ChatMessage["queryResult"] = undefined
        let currentQueryError = ""
        const currentCharts: ChartConfig[] = []
        const currentTables: TableConfig[] = []

        await readSSEStream(reader, (event, data) => {
          if (abortRef.current) return

          if (event === "text") {
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === "assistant") {
                return [...prev.slice(0, -1), { ...last, content: last.content + (typeof data === "string" ? data : "") }]
              }
              return prev
            })
          } else if (event === "analysis") {
            // Data Agent 分析文字（覆盖式，不是追加）
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === "assistant") {
                return [...prev.slice(0, -1), { ...last, content: typeof data === "string" ? data : String(data) }]
              }
              return prev
            })
          } else if (event === "sql") {
            currentSql = typeof data === "string" ? data : ""
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === "assistant") {
                return [...prev.slice(0, -1), { ...last, sql: currentSql }]
              }
              return prev
            })
          } else if (event === "query_result") {
            currentQueryResult = data as ChatMessage["queryResult"]
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === "assistant") {
                return [...prev.slice(0, -1), { ...last, queryResult: currentQueryResult }]
              }
              return prev
            })
          } else if (event === "error") {
            currentQueryError = typeof data === "string" ? data : String(data)
            setMessages((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.role === "assistant") {
                return [...prev.slice(0, -1), { ...last, queryError: currentQueryError }]
              }
              return prev
            })
          } else if (event === "chart") {
            if (data) {
              currentCharts.push(data as ChartConfig)
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (last && last.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, charts: [...currentCharts] }]
                }
                return prev
              })
            }
          } else if (event === "table") {
            if (data) {
              currentTables.push(data as TableConfig)
              setMessages((prev) => {
                const last = prev[prev.length - 1]
                if (last && last.role === "assistant") {
                  return [...prev.slice(0, -1), { ...last, tables: [...currentTables] }]
                }
                return prev
              })
            }
          } else if (event === "citations") {
            if (Array.isArray(data)) {
              setCitations(
                data.map((c: { chunk_id?: string; title?: string; source?: string; url?: string }, i: number) => ({
                  id: c.chunk_id || `c${i}`,
                  title: c.title || `引用 ${i + 1}`,
                  source: c.source || "知识库",
                  url: c.url || "#",
                }))
              )
            }
          } else if (event === "content_blocks") {
            if (Array.isArray(data)) {
              const rows = data
                .filter((b: { type?: string; content?: string }) => b.type === "text" && b.content)
                .map((b: { content?: string }, i: number) => ({
                  key: `Block ${i + 1}`,
                  value: String(b.content).slice(0, 100),
                  confidence: 0.95,
                }))
              if (rows.length > 0) setStructuredOutput(rows)
            }
          }
        })
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "对话请求失败"
        toast.error(errorMessage)
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last && last.role === "assistant" && !last.content) {
            return [...prev.slice(0, -1), { ...last, content: "❌ 请求失败，请稍后重试。" }]
          }
          return prev
        })
      } finally {
        setStatus("ready")
        // 自动生成对话标题：如果当前标题是"新对话"，取用户消息前20字作为标题
        if (activeConversationId && message.text.trim()) {
          const activeConv = conversationsRef.current.find((c) => c.id === activeConversationId)
          if (activeConv && activeConv.title === "新对话") {
            const newTitle = message.text.trim().slice(0, 20) + (message.text.trim().length > 20 ? "..." : "")
            handleUpdateTitle(activeConversationId, newTitle)
          }
        }
      }
    },
    [status, activeConversationId, handleUpdateTitle]
  )

  const handleNewChat = useCallback(async () => {
    try {
      const res = await api.post<{ id: string; title: string }>("/conversations", { title: "新对话" })
      const newConv = { id: res.id, title: res.title, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
      setConversations((prev) => [newConv, ...prev])
      setActiveConversationId(res.id)
      setMessages([])
      setCitations([])
      setStructuredOutput([])
      setStatus("ready")
    } catch {
      toast.error("创建对话失败")
    }
  }, [])

  const todayConversations = conversations.filter(
    (c) => new Date(c.created_at).toDateString() === new Date().toDateString()
  )
  const earlierConversations = conversations.filter(
    (c) => new Date(c.created_at).toDateString() !== new Date().toDateString()
  )

  const activeConv = conversations.find((c) => c.id === activeConversationId)

  return (
    <div className="flex flex-col h-full">
      {/* Breadcrumb */}
      <div className="px-6 lg:px-8 pt-4 pb-2 flex-shrink-0">
        <PageHeader />
      </div>
      {/* Main Chat Layout */}
      <div className="flex flex-1 min-w-0 overflow-hidden relative">
        {/* ==================== Conversation List Panel ==================== */}
      <aside
        className={cn(
          "shrink-0 bg-white border-r border-[#e7e5e4] flex flex-col overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
          convPanelOpen ? "w-[220px] opacity-100" : "w-0 opacity-0 overflow-hidden"
        )}
      >
        <div className="px-4 py-3.5 border-b border-[#f5f5f4] flex items-center justify-between">
          <span className="text-[11px] font-semibold text-[#a8a29e] uppercase tracking-wider">历史对话</span>
          <button
            onClick={() => setConvPanelOpen(false)}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all"
            title="收起"
          >
            <PanelLeftClose className="size-3.5" />
          </button>
        </div>

        <div className="px-3 py-3">
          <button
            onClick={handleNewChat}
            className="w-full py-2.5 rounded-xl bg-[#292524] text-white text-xs font-medium hover:bg-[#1c1917] transition-colors flex items-center justify-center gap-2 shadow-soft"
          >
            <Plus className="size-3.5" />
            新建对话
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-0.5">
          {todayConversations.length > 0 && (
            <div>
              <p className="px-2 text-[10px] font-semibold text-[#a8a29e] uppercase tracking-wider mb-2 mt-2">今天</p>
              {todayConversations.map((conv) => (
                <div
                  key={conv.id}
                  className={cn(
                    "group flex items-center gap-1 px-3 py-2 rounded-xl text-xs transition-all",
                    activeConversationId === conv.id
                      ? "bg-accent-50 text-accent-700 font-medium border border-accent-100"
                      : "text-[#57534e] hover:bg-[#f5f5f4] hover:text-[#292524]"
                  )}
                >
                  {editingConvId === conv.id ? (
                    <input
                      autoFocus
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onBlur={() => {
                        if (editingConvId !== conv.id) return
                        if (editingTitle.trim() && editingTitle !== conv.title) {
                          handleUpdateTitle(conv.id, editingTitle.trim())
                        } else {
                          setEditingConvId(null)
                        }
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault()
                          e.stopPropagation()
                          if (editingTitle.trim() && editingTitle !== conv.title) {
                            handleUpdateTitle(conv.id, editingTitle.trim())
                          } else {
                            setEditingConvId(null)
                          }
                        }
                        if (e.key === "Escape") {
                          setEditingConvId(null)
                        }
                      }}
                      className="flex-1 min-w-0 bg-transparent outline-none text-xs"
                    />
                  ) : (
                    <button
                      onClick={() => setActiveConversationId(conv.id)}
                      className="flex-1 min-w-0 text-left truncate"
                    >
                      {conv.title}
                    </button>
                  )}
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setEditingConvId(conv.id)
                        setEditingTitle(conv.title)
                      }}
                      className="w-6 h-6 rounded flex items-center justify-center text-[#a8a29e] hover:text-accent-600 hover:bg-accent-50 transition-all"
                      title="编辑"
                    >
                      <Pencil className="size-3" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteConversation(conv.id)
                      }}
                      className="w-6 h-6 rounded flex items-center justify-center text-[#a8a29e] hover:text-red-500 hover:bg-red-50 transition-all"
                      title="删除"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {earlierConversations.length > 0 && (
            <div>
              <p className="px-2 text-[10px] font-semibold text-[#a8a29e] uppercase tracking-wider mb-2 mt-4">更早</p>
              {earlierConversations.map((conv) => (
                <div
                  key={conv.id}
                  className={cn(
                    "group flex items-center gap-1 px-3 py-2 rounded-xl text-xs transition-all",
                    activeConversationId === conv.id
                      ? "bg-accent-50 text-accent-700 font-medium border border-accent-100"
                      : "text-[#57534e] hover:bg-[#f5f5f4] hover:text-[#292524]"
                  )}
                >
                  {editingConvId === conv.id ? (
                    <input
                      autoFocus
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onBlur={() => {
                        if (editingConvId !== conv.id) return
                        if (editingTitle.trim() && editingTitle !== conv.title) {
                          handleUpdateTitle(conv.id, editingTitle.trim())
                        } else {
                          setEditingConvId(null)
                        }
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault()
                          e.stopPropagation()
                          if (editingTitle.trim() && editingTitle !== conv.title) {
                            handleUpdateTitle(conv.id, editingTitle.trim())
                          } else {
                            setEditingConvId(null)
                          }
                        }
                        if (e.key === "Escape") {
                          setEditingConvId(null)
                        }
                      }}
                      className="flex-1 min-w-0 bg-transparent outline-none text-xs"
                    />
                  ) : (
                    <button
                      onClick={() => setActiveConversationId(conv.id)}
                      className="flex-1 min-w-0 text-left truncate"
                    >
                      {conv.title}
                    </button>
                  )}
                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setEditingConvId(conv.id)
                        setEditingTitle(conv.title)
                      }}
                      className="w-6 h-6 rounded flex items-center justify-center text-[#a8a29e] hover:text-accent-600 hover:bg-accent-50 transition-all"
                      title="编辑"
                    >
                      <Pencil className="size-3" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDeleteConversation(conv.id)
                      }}
                      className="w-6 h-6 rounded flex items-center justify-center text-[#a8a29e] hover:text-red-500 hover:bg-red-50 transition-all"
                      title="删除"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>

      {/* 会话列表收起后的悬浮展开按钮 */}
      {!convPanelOpen && (
        <button
          onClick={() => setConvPanelOpen(true)}
          className="absolute left-[72px] top-1/2 -translate-y-1/2 z-30 w-5 h-10 bg-white border border-[#e7e5e4] rounded-r-lg shadow-soft flex items-center justify-center text-[#a8a29e] hover:text-accent-600 transition-all"
          title="展开会话列表"
        >
          <ChevronRight className="size-3" />
        </button>
      )}

      {/* ==================== Center Chat Area ==================== */}
      <main className="flex-1 flex flex-col min-w-0 relative bg-[#fafaf9]">
        {/* Top Bar */}
        <div className="h-14 px-5 flex items-center justify-between bg-white/80 backdrop-blur-md border-b border-[#e7e5e4]/60 sticky top-0 z-10">
          <div className="flex items-center gap-3">
            {!convPanelOpen && (
              <button
                onClick={() => setConvPanelOpen(true)}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all"
                title="展开会话列表"
              >
                <PanelLeftClose className="size-3.5 rotate-180" />
              </button>
            )}
            <h2 className="text-sm font-semibold text-[#292524] truncate max-w-[300px]">
              {activeConv?.title || "新对话"}
            </h2>
            <button className="text-[#d6d3d1] hover:text-[#a8a29e] transition-colors">
              <MoreHorizontal className="size-4" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            {/* Share & Export */}
            <button
              onClick={() => {
                const md = messages.map((m) => `**${m.role === "user" ? "用户" : "Aura AI"}**\n\n${m.content}`).join("\n\n---\n\n")
                const blob = new Blob([md], { type: "text/markdown" })
                const url = URL.createObjectURL(blob)
                const a = document.createElement("a")
                a.href = url
                a.download = `对话-${activeConv?.title || "导出"}.md`
                a.click()
                URL.revokeObjectURL(url)
              }}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all"
              title="导出 Markdown"
            >
              <Download className="size-3.5" />
            </button>
            <button
              onClick={() => {
                toast.info("分享功能需要后端支持，请先创建真实对话")
              }}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all"
              title="分享链接"
            >
              <Share2 className="size-3.5" />
            </button>

            {/* Right Panel Toggle */}
            <button
              onClick={() => setRightPanelOpen(!rightPanelOpen)}
              className={cn(
                "w-8 h-8 rounded-lg flex items-center justify-center transition-all",
                rightPanelOpen
                  ? "bg-accent-50 text-accent-600 border border-accent-100"
                  : "text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e]"
              )}
              title="引用面板"
            >
              {rightPanelOpen ? <PanelRightClose className="size-3.5" /> : <PanelRightOpen className="size-3.5" />}
            </button>
          </div>
        </div>

        {/* Messages */}
        <StickToBottom className="flex-1 overflow-hidden pb-28" initial="smooth" resize="smooth">
          <StickToBottom.Content className="flex flex-col gap-6 p-5">
            {messages.length === 0 && (
              <div className="flex-1 flex flex-col items-center justify-center text-[#a8a29e]/60 min-h-[200px]">
                <Bot className="size-10 mb-3 opacity-40" />
                <p className="text-sm">开始一个新的对话吧</p>
                <p className="text-xs mt-1">输入问题或上传文档，Aura AI 将基于知识库为你解答</p>
              </div>
            )}
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </StickToBottom.Content>
          <ScrollToBottomButton />
        </StickToBottom>

        {/* Input Area */}
        <div className="absolute bottom-0 left-0 right-0 px-4 pb-4 pt-2 bg-gradient-to-t from-[#fafaf9] via-[#fafaf9] to-transparent">
          <div className="max-w-3xl mx-auto">
            {/* Quick Actions */}
            <div className="flex gap-2 mb-2 px-1 relative">
              {templates.slice(0, 3).map((tpl) => (
                <button
                  key={tpl.id}
                  onClick={() => {
                    handleSubmit({ text: tpl.content, files: [] } as PromptInputMessage)
                  }}
                  className="px-2.5 py-1 rounded-lg bg-white border border-[#e7e5e4] text-[11px] text-[#78716c] hover:border-accent-300 hover:text-accent-600 transition-all shadow-soft truncate max-w-[120px]"
                  title={tpl.name}
                >
                  <Wand2 className="size-3 inline mr-1" />{tpl.name}
                </button>
              ))}
              {templates.length > 3 && (
                <div className="relative" ref={templateDropdownRef}>
                  <button
                    onClick={() => setShowTemplateDropdown(!showTemplateDropdown)}
                    className="px-2.5 py-1 rounded-lg bg-white border border-[#e7e5e4] text-[11px] text-[#78716c] hover:border-accent-300 hover:text-accent-600 transition-all shadow-soft"
                  >
                    <ChevronDown className="size-3 inline" />更多
                  </button>
                  {showTemplateDropdown && (
                    <div className="absolute bottom-full left-0 mb-2 w-56 bg-white border border-[#e7e5e4] rounded-xl shadow-elevated z-50 overflow-hidden">
                      <div className="p-2 space-y-1 max-h-[240px] overflow-y-auto">
                        {templates.slice(3).map((tpl) => (
                          <button
                            key={tpl.id}
                            onClick={() => {
                              handleSubmit({ text: tpl.content, files: [] } as PromptInputMessage)
                              setShowTemplateDropdown(false)
                            }}
                            className="w-full text-left px-3 py-2 rounded-lg text-sm text-[#44403c] hover:bg-[#f5f5f4] transition-colors"
                          >
                            {tpl.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <PromptInputProvider initialInput={initialInput}>
            <PromptInput globalDrop multiple onSubmit={handleSubmit} className="glass-card-strong rounded-2xl">
              <PromptInputHeader className="px-3 pt-2.5">
                <PromptInputAttachmentsDisplay />
              </PromptInputHeader>
              <PromptInputBody>
                <PromptInputTextarea
                  placeholder={status === "streaming" ? "AI 正在回复中..." : "输入消息... (Shift + Enter 换行)"}
                  className="w-full bg-transparent px-3 py-2 text-sm resize-none outline-none placeholder:text-muted-foreground/50 max-h-[160px] min-h-[44px]"
                  disabled={status === "streaming"}
                />
              </PromptInputBody>
              <PromptInputFooter className="px-2 pb-2">
                <PromptInputTools>
                  <AttachmentButton />
                  <SpeechInput
                    className="shrink-0 flex items-center justify-center size-8 rounded-lg bg-primary text-white hover:bg-primary/90 hover:text-white transition-colors"
                    title="语音输入"
                  />
                </PromptInputTools>
                <PromptInputSubmit
                  status={status}
                  className="flex items-center justify-center size-8 rounded-lg bg-primary text-white hover:bg-primary/90 shadow-sm transition-all"
                >
                  <img src={sendIcon} className="size-4" alt="发送" />
                </PromptInputSubmit>
              </PromptInputFooter>
            </PromptInput>
            </PromptInputProvider>
            <p className="text-center text-[10px] text-[#a8a29e] mt-1.5">AI 生成内容仅供参考，请核实重要信息</p>
          </div>
        </div>
      </main>

      {/* ==================== Right Info Panel ==================== */}
      <aside
        className={cn(
          "shrink-0 bg-white border-l border-[#e7e5e4] flex flex-col overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
          rightPanelOpen ? "w-[280px] opacity-100" : "w-0 opacity-0 overflow-hidden"
        )}
      >
        <div className="px-4 py-3 border-b border-[#f5f5f4] flex items-center justify-between">
          <span className="text-xs font-semibold text-[#292524]">引用与结构化数据</span>
          <button
            onClick={() => setRightPanelOpen(false)}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-[#f5f5f4] hover:text-[#57534e] transition-all"
          >
            <X className="size-3.5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* Structured Output */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Table className="size-3.5 text-accent-500" />
              <span className="text-xs font-semibold text-[#292524]">关键指标</span>
              <span className="ml-auto text-[10px] text-[#a8a29e]">{structuredOutput.length || 3} 项</span>
            </div>
            {structuredOutput.length > 0 ? (
              <div className="space-y-2">
                {structuredOutput.map((row) => (
                  <div key={row.key} className="p-3 rounded-xl bg-[#f5f5f4] border border-[#e7e5e4]">
                    <p className="text-[10px] text-[#a8a29e] mb-0.5">{row.key}</p>
                    <p className="text-sm font-mono text-accent-600">{row.value}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="p-3 rounded-xl bg-[#f5f5f4] border border-[#e7e5e4]">
                  <p className="text-[10px] text-[#a8a29e] mb-0.5">营收增长</p>
                  <p className="text-sm font-bold text-emerald-600">+23.5%</p>
                  <p className="text-[10px] text-[#a8a29e]">4.8 亿元</p>
                </div>
                <div className="p-3 rounded-xl bg-[#f5f5f4] border border-[#e7e5e4]">
                  <p className="text-[10px] text-[#a8a29e] mb-0.5">净利润</p>
                  <p className="text-sm font-bold text-blue-600">9,200 万</p>
                  <p className="text-[10px] text-[#a8a29e]">利润率 19.2%</p>
                </div>
                <div className="p-3 rounded-xl bg-[#f5f5f4] border border-[#e7e5e4]">
                  <p className="text-[10px] text-[#a8a29e] mb-0.5">研发投入</p>
                  <p className="text-sm font-bold text-amber-600">15.8%</p>
                  <p className="text-[10px] text-[#a8a29e]">同比增长 4.2%</p>
                </div>
              </div>
            )}
          </div>

          {/* Citations */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <BookOpen className="size-3.5 text-accent-500" />
              <span className="text-xs font-semibold text-[#292524]">引用来源</span>
              <span className="ml-auto text-[10px] text-[#a8a29e]">{citations.length || 3} 处</span>
            </div>
            {citations.length > 0 ? (
              <div className="space-y-2">
                {citations.map((cite, index) => (
                  <a
                    key={cite.id}
                    href={cite.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-start gap-2.5 p-2.5 rounded-xl bg-[#f5f5f4] border border-[#e7e5e4] hover:border-accent-300 hover:shadow-sm transition-all group"
                  >
                    <div className="w-5 h-5 rounded-md bg-accent-50 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <span className="text-[9px] font-bold text-accent-600">{index + 1}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-[#44403c] truncate group-hover:text-accent-600 transition-colors">{cite.title}</p>
                      <p className="text-[10px] text-[#a8a29e] flex items-center gap-1 mt-0.5">
                        <BookOpen className="size-2.5" />
                        {cite.source}
                      </p>
                    </div>
                  </a>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <a
                    key={i}
                    href="#"
                    className="flex items-start gap-2.5 p-2.5 rounded-xl bg-[#f5f5f4] border border-[#e7e5e4] hover:border-accent-300 hover:shadow-sm transition-all group"
                  >
                    <div className="w-5 h-5 rounded-md bg-accent-50 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <span className="text-[9px] font-bold text-accent-600">{i}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-[#44403c] truncate group-hover:text-accent-600 transition-colors">2024年Q3财务报告.pdf</p>
                      <p className="text-[10px] text-[#a8a29e] mt-0.5">第 {i * 2 + 1} 页</p>
                    </div>
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      </aside>
      </div>
    </div>
  )
}
