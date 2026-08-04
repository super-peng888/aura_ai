import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"
import { api, fetchStream } from "@/api/client"
import { toast } from "sonner"
import {
  XProvider,
  Bubble,
  Sender,
  Conversations,
  ThoughtChain,
  Welcome,
  Prompts,
  Attachments,
} from "@ant-design/x"
import { XMarkdown } from "@ant-design/x-markdown"
import "@ant-design/x-markdown/themes/light.css"
import { Avatar, Button, Input, Modal } from "antd"
import type { UploadFile } from "antd"
import zhCN from "antd/locale/zh_CN"
import {
  MoreHorizontal,
  FileText,
  Bot,
  User,
  Table,
  BookOpen,
  X,
  Paperclip,
  PanelLeftClose,
  PanelRightClose,
  PanelRightOpen,
  ChevronRight,
  Share2,
  Download,
} from "lucide-react"
import PageHeader from "@/components/layout/PageHeader"
import EChartsCard from "@/components/ai-elements/echarts-card"

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

interface ThoughtStep {
  kind?: string
  step: string
  title: string
  content?: string
  status: "pending" | "success"
}

interface ChatAttachment {
  filename: string
  url: string
  mediaType: string
  type: "file"
}

interface ChatImage {
  image_id: string
  url: string
  thumbnail_url?: string | null
  caption?: string | null
  page_number?: number | null
}

interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  thoughts?: ThoughtStep[]
  attachments?: ChatAttachment[]
  images?: ChatImage[]
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
// 消息内容渲染（assistant：X Markdown + Data Agent 结构化输出）
// ============================================================================

function AssistantContent({ message, streaming }: { message: ChatMessage; streaming: boolean }) {
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      <XMarkdown
        content={message.content}
        streaming={{ hasNextChunk: streaming }}
        openLinksInNewTab
        className="x-markdown-light"
      />

      {/* 命中文档中的原图（检索回捞的 [IMG:...] 引用） */}
      {message.images && message.images.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-[#44403c] mb-2">文档原图（{message.images.length}）</p>
          <div className="grid grid-cols-2 gap-2">
            {message.images.map((img) => (
              <a
                key={img.image_id}
                href={img.url}
                target="_blank"
                rel="noreferrer"
                className="block border border-[#e7e5e4] rounded-xl overflow-hidden bg-white hover:shadow-md transition-shadow"
              >
                <img
                  src={img.url}
                  alt={img.caption || img.image_id}
                  loading="lazy"
                  className="w-full max-h-64 object-contain bg-[#fafaf9]"
                />
                <p className="text-[10px] text-[#a8a29e] px-2 py-1 truncate">
                  {img.caption || (img.page_number ? `第 ${img.page_number} 页` : img.image_id)}
                </p>
              </a>
            ))}
          </div>
        </div>
      )}

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
  )
}

/** 思维链（真实 agent 步骤，实时推送不落库）置于当轮 assistant 气泡上方 */
function MessageThoughts({ thoughts }: { thoughts: ThoughtStep[] }) {
  const items = thoughts.map((t, i) => ({
    key: `${i}`,
    title: t.title,
    description: t.content,
    status: (t.status === "pending" ? "loading" : "success") as "loading" | "success",
  }))
  return (
    <div className="mb-1.5">
      <ThoughtChain items={items} />
    </div>
  )
}

/** 用户消息头部：附件卡片列表 */
function MessageAttachments({ attachments }: { attachments: ChatAttachment[] }) {
  return (
    <div className="flex flex-wrap gap-2 mb-1 justify-end">
      {attachments.map((att, idx) => (
        <div key={idx} className="flex items-center gap-2 glass-card rounded-lg px-3 py-2 text-xs">
          <FileText className="size-3.5 text-primary" />
          <span className="font-medium">{att.filename || "附件"}</span>
          <span className="text-muted-foreground">{att.mediaType}</span>
        </div>
      ))}
    </div>
  )
}

// Bubble.List 角色配置（模块级常量，避免重渲染重置动画）
const bubbleRoles = {
  assistant: {
    placement: "start" as const,
    avatar: <Avatar style={{ backgroundColor: "#f5f5f4", color: "#292524" }} icon={<Bot className="size-4" />} />,
    variant: "outlined" as const,
  },
  user: {
    placement: "end" as const,
    avatar: <Avatar style={{ backgroundColor: "#292524", color: "#fff" }} icon={<User className="size-4" />} />,
  },
}

// ============================================================================
// 模块级缓存：路由切换 unmount 后保留会话/消息状态，回到页面直接恢复
// ============================================================================

const chatCache: {
  conversations: Conversation[]
  activeConversationId: string | null
  messages: ChatMessage[]
  citations: Citation[]
} = { conversations: [], activeConversationId: null, messages: [], citations: [] }

// 已拉取过消息的会话 id：同一会话切回时直接用缓存，不重拉（保留思维链等不落库字段）
let cachedLoadedConvId: string | null = null

// ============================================================================
// Main Chat Page
// ============================================================================

export default function Chat() {
  const location = useLocation()
  const [conversations, setConversations] = useState<Conversation[]>(chatCache.conversations)
  const [activeConversationId, setActiveConversationId] = useState<string | null>(chatCache.activeConversationId)
  const [messages, setMessages] = useState<ChatMessage[]>(chatCache.messages)
  const [status, setStatus] = useState<"ready" | "submitted" | "streaming">("ready")
  const [citations, setCitations] = useState<Citation[]>(chatCache.citations)
  const [structuredOutput, setStructuredOutput] = useState<Array<{ key: string; value: string; confidence: number }>>([])

  // 面板展开/收起状态
  const [convPanelOpen, setConvPanelOpen] = useState(true)
  const [rightPanelOpen, setRightPanelOpen] = useState(true)
  const [templates, setTemplates] = useState<{ id: string; name: string; content: string; category?: string }[]>([])

  // 输入区状态（Sender + Attachments）
  const [inputValue, setInputValue] = useState("")
  const [attachments, setAttachments] = useState<UploadFile[]>([])
  const [attachHeaderOpen, setAttachHeaderOpen] = useState(false)

  // 会话重命名弹窗
  const [renameConv, setRenameConv] = useState<{ id: string; title: string } | null>(null)

  const abortRef = useRef<boolean>(false)
  const conversationsRef = useRef(conversations)
  useEffect(() => {
    conversationsRef.current = conversations
  }, [conversations])

  // 同步状态到模块级缓存（切路由后恢复）
  useEffect(() => {
    chatCache.conversations = conversations
    chatCache.activeConversationId = activeConversationId
    chatCache.messages = messages
    chatCache.citations = citations
  }, [conversations, activeConversationId, messages, citations])

  // 从 Prompt 市场传入的模板内容
  useEffect(() => {
    const tpl = location.state?.templateContent as string | undefined
    if (tpl) {
      requestAnimationFrame(() => setInputValue(tpl))
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
          // 仅当无已激活会话时才自动选中第一个（保留切路由前的选择）
          if (res && res.length > 0) {
            setActiveConversationId((prev) => prev ?? res[0].id)
          }
        })
      })
      .catch(() => toast.error("加载会话失败"))
  }, [])

  // 加载当前会话消息（同一会话已缓存则跳过，避免切路由回来清空思维链/图表等不落库字段）
  useEffect(() => {
    if (!activeConversationId) {
      requestAnimationFrame(() => setMessages([]))
      return
    }
    if (activeConversationId === cachedLoadedConvId) return
    api.get<{ id: string; role: string; content: string; created_at: string; images?: ChatImage[] }[]>(`/conversations/${activeConversationId}/messages`)
      .then((res) => {
        cachedLoadedConvId = activeConversationId
        requestAnimationFrame(() => {
          setMessages(
            (res || []).map((m) => ({
              id: m.id,
              role: m.role as "user" | "assistant",
              content: m.content,
              images: m.images && m.images.length > 0 ? m.images : undefined,
            }))
          )
        })
      })
      .catch(() => toast.error("加载消息失败"))
  }, [activeConversationId])

  const handleUpdateTitle = useCallback(async (convId: string, title: string) => {
    try {
      await api.put(`/conversations/${convId}`, { title })
      setConversations((prev) =>
        prev.map((c) => (c.id === convId ? { ...c, title } : c))
      )
      toast.success("对话名已更新")
    } catch {
      toast.error("更新对话名失败")
    }
  }, [])

  const handleDeleteConversation = useCallback(async (convId: string) => {
    if (!confirm("确定要删除该对话吗？")) return
    try {
      await api.delete(`/conversations/${convId}`)
      if (convId === cachedLoadedConvId) cachedLoadedConvId = null
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
    async (text: string) => {
      if (!text.trim() && attachments.length === 0) return
      if (status !== "ready") return

      // 确保存在会话：无激活会话时先创建，否则后端不会持久化消息（conversation_id 为空不落库）
      let convId = activeConversationId
      if (!convId) {
        try {
          const res = await api.post<{ id: string; title: string }>("/conversations", { title: "新对话" })
          convId = res.id
          const now = new Date().toISOString()
          setConversations((prev) => [{ id: res.id, title: res.title, created_at: now, updated_at: now }, ...prev])
          // 新会话无历史消息，标记为已加载，避免消息 effect 重拉清空流式中的消息
          cachedLoadedConvId = res.id
          setActiveConversationId(res.id)
        } catch {
          toast.error("创建对话失败")
          return
        }
      }

      // 上传附件到 OSS
      const uploadedAttachments: ChatAttachment[] = []
      for (const f of attachments) {
        const file = f.originFileObj as File | undefined
        if (!file) continue
        try {
          const formData = new FormData()
          formData.append("file", file, f.name || "file")
          const res = await api.post<{ oss_url: string; original_name: string }>("/uploads/document", formData)
          uploadedAttachments.push({
            filename: res.original_name || f.name || "file",
            url: res.oss_url,
            mediaType: file.type || "application/octet-stream",
            type: "file" as const,
          })
        } catch {
          toast.error(`上传附件 ${f.name} 失败`)
        }
      }

      const newMessage: ChatMessage = {
        id: `m${Date.now()}`,
        role: "user",
        content: text,
        attachments: uploadedAttachments.length > 0 ? uploadedAttachments : undefined,
      }

      setMessages((prev) => [...prev, newMessage])
      setStatus("submitted")
      setCitations([])
      setStructuredOutput([])
      setInputValue("")
      setAttachments([])
      setAttachHeaderOpen(false)
      abortRef.current = false

      const assistantId = `a${Date.now()}`
      setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }])

      try {
        const reader = await fetchStream("/chat/stream", {
          conversation_id: convId,
          messages: [{ role: "user", content: text }],
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

        const patchLastAssistant = (patch: Partial<ChatMessage> | ((last: ChatMessage) => Partial<ChatMessage>)) => {
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            if (last && last.role === "assistant") {
              const p = typeof patch === "function" ? patch(last) : patch
              return [...prev.slice(0, -1), { ...last, ...p }]
            }
            return prev
          })
        }

        await readSSEStream(reader, (event, data) => {
          if (abortRef.current) return

          if (event === "text") {
            patchLastAssistant((last) => ({ content: last.content + (typeof data === "string" ? data : "") }))
          } else if (event === "thought") {
            // 思维链步骤：tool_result 到达时把之前 pending 的检索步骤置为完成
            const t = data as ThoughtStep
            if (!t || typeof t !== "object" || !t.title) return
            patchLastAssistant((last) => {
              const prevThoughts = last.thoughts || []
              const settled = t.step === "tool_result"
                ? prevThoughts.map((s) => (s.status === "pending" ? { ...s, status: "success" as const } : s))
                : prevThoughts
              return { thoughts: [...settled, t] }
            })
          } else if (event === "analysis") {
            // Data Agent 分析文字（覆盖式，不是追加）
            patchLastAssistant({ content: typeof data === "string" ? data : String(data) })
          } else if (event === "sql") {
            currentSql = typeof data === "string" ? data : ""
            patchLastAssistant({ sql: currentSql })
          } else if (event === "query_result") {
            currentQueryResult = data as ChatMessage["queryResult"]
            patchLastAssistant({ queryResult: currentQueryResult })
          } else if (event === "error") {
            currentQueryError = typeof data === "string" ? data : String(data)
            patchLastAssistant({ queryError: currentQueryError })
          } else if (event === "chart") {
            if (data) {
              currentCharts.push(data as ChartConfig)
              patchLastAssistant({ charts: [...currentCharts] })
            }
          } else if (event === "table") {
            if (data) {
              currentTables.push(data as TableConfig)
              patchLastAssistant({ tables: [...currentTables] })
            }
          } else if (event === "images") {
            // 检索命中的文档原图（后端在首个文本增量前推送）
            if (Array.isArray(data) && data.length > 0) {
              patchLastAssistant({ images: data as ChatImage[] })
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
        // 收尾：残留 pending 的思维链步骤统一置为完成
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last && last.role === "assistant" && last.thoughts?.some((t) => t.status === "pending")) {
            return [...prev.slice(0, -1), {
              ...last,
              thoughts: last.thoughts.map((t) => (t.status === "pending" ? { ...t, status: "success" as const } : t)),
            }]
          }
          return prev
        })
        // 自动生成对话标题：如果当前标题是"新对话"，取用户消息前20字作为标题
        if (convId && text.trim()) {
          const activeConv = conversationsRef.current.find((c) => c.id === convId)
          if (activeConv && activeConv.title === "新对话") {
            const newTitle = text.trim().slice(0, 20) + (text.trim().length > 20 ? "..." : "")
            handleUpdateTitle(convId, newTitle)
          }
        }
      }
    },
    [status, activeConversationId, attachments, handleUpdateTitle]
  )

  const handleNewChat = useCallback(async () => {
    try {
      const res = await api.post<{ id: string; title: string }>("/conversations", { title: "新对话" })
      const newConv = { id: res.id, title: res.title, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
      setConversations((prev) => [newConv, ...prev])
      // 新会话无历史消息，标记已加载，省去一次空拉取
      cachedLoadedConvId = res.id
      setActiveConversationId(res.id)
      setMessages([])
      setCitations([])
      setStructuredOutput([])
      setStatus("ready")
    } catch {
      toast.error("创建对话失败")
    }
  }, [])

  const activeConv = conversations.find((c) => c.id === activeConversationId)

  // 会话列表（今天/更早分组）
  const conversationItems = useMemo(() => {
    const today = new Date().toDateString()
    return conversations.map((c) => ({
      key: c.id,
      label: c.title,
      group: new Date(c.created_at).toDateString() === today ? "今天" : "更早",
    }))
  }, [conversations])

  // 消息 → Bubble.List items
  const bubbleItems = useMemo(() => {
    return messages.map((m, idx) => {
      const isLast = idx === messages.length - 1
      const streamingThis = isLast && m.role === "assistant" && status === "streaming"
      if (m.role === "assistant") {
        return {
          key: m.id,
          role: "assistant",
          content: m.content,
          loading: isLast && status === "submitted" && !m.content && !(m.thoughts?.length),
          header: m.thoughts && m.thoughts.length > 0 ? <MessageThoughts thoughts={m.thoughts} /> : undefined,
          contentRender: () => <AssistantContent message={m} streaming={streamingThis} />,
        }
      }
      return {
        key: m.id,
        role: "user",
        content: m.content,
        header: m.attachments && m.attachments.length > 0 ? <MessageAttachments attachments={m.attachments} /> : undefined,
      }
    })
  }, [messages, status])

  return (
    <XProvider locale={zhCN} theme={{ token: { colorPrimary: "#292524", borderRadius: 12 } }}>
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
            convPanelOpen ? "w-[240px] opacity-100" : "w-0 opacity-0 overflow-hidden"
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

          <div className="flex-1 overflow-y-auto px-2 pb-4">
            <Conversations
              items={conversationItems}
              activeKey={activeConversationId ?? undefined}
              onActiveChange={(key) => setActiveConversationId(key)}
              groupable
              creation={{ label: "新建对话", onClick: handleNewChat }}
              menu={(conversation) => ({
                items: [
                  { key: "rename", label: "重命名" },
                  { key: "delete", label: "删除", danger: true },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent?.stopPropagation?.()
                  const conv = conversations.find((c) => c.id === conversation.key)
                  if (!conv) return
                  if (key === "rename") setRenameConv({ id: conv.id, title: conv.title })
                  if (key === "delete") handleDeleteConversation(conv.id)
                },
              })}
              style={{ width: "100%" }}
            />
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
          <div className="flex-1 overflow-hidden pb-32 px-5 pt-4">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center gap-6 max-w-2xl mx-auto">
                <Welcome
                  variant="borderless"
                  icon={<Avatar size={48} style={{ backgroundColor: "#292524", color: "#fff" }} icon={<Bot className="size-6" />} />}
                  title="你好，我是 Aura AI"
                  description="输入问题或上传文档，我将基于企业知识库为你解答"
                />
                {templates.length > 0 && (
                  <Prompts
                    title="试试这些模板"
                    wrap
                    items={templates.slice(0, 6).map((tpl) => ({
                      key: tpl.id,
                      label: tpl.name,
                      description: tpl.content.length > 40 ? tpl.content.slice(0, 40) + "..." : tpl.content,
                    }))}
                    onItemClick={(info) => {
                      const tpl = templates.find((t) => t.id === info.data.key)
                      if (tpl) handleSubmit(tpl.content)
                    }}
                  />
                )}
              </div>
            ) : (
              <Bubble.List items={bubbleItems} role={bubbleRoles} autoScroll style={{ height: "100%" }} />
            )}
          </div>

          {/* Input Area */}
          <div className="absolute bottom-0 left-0 right-0 px-4 pb-4 pt-2 bg-gradient-to-t from-[#fafaf9] via-[#fafaf9] to-transparent">
            <div className="max-w-3xl mx-auto">
              <Sender
                value={inputValue}
                onChange={setInputValue}
                loading={status !== "ready"}
                onSubmit={(msg) => handleSubmit(msg)}
                onCancel={() => {
                  abortRef.current = true
                  setStatus("ready")
                }}
                allowSpeech
                placeholder={status === "streaming" ? "AI 正在回复中..." : "输入消息... (Shift + Enter 换行)"}
                autoSize={{ minRows: 1, maxRows: 6 }}
                header={
                  <Sender.Header title="附件" open={attachHeaderOpen} onOpenChange={setAttachHeaderOpen}>
                    <Attachments
                      beforeUpload={() => false}
                      items={attachments}
                      onChange={({ fileList }) => setAttachments(fileList)}
                      placeholder={{
                        icon: <Paperclip className="size-5 mx-auto" />,
                        title: "拖拽文件到这里",
                        description: "或点击选择文件上传",
                      }}
                    />
                  </Sender.Header>
                }
                prefix={
                  <Button
                    type="text"
                    icon={<Paperclip className="size-4" />}
                    onClick={() => setAttachHeaderOpen(!attachHeaderOpen)}
                    title="添加附件"
                  />
                }
              />
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
                <span className="ml-auto text-[10px] text-[#a8a29e]">{structuredOutput.length} 项</span>
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
                <p className="text-[11px] text-[#a8a29e]">暂无结构化数据</p>
              )}
            </div>

            {/* Citations */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <BookOpen className="size-3.5 text-accent-500" />
                <span className="text-xs font-semibold text-[#292524]">引用来源</span>
                <span className="ml-auto text-[10px] text-[#a8a29e]">{citations.length} 处</span>
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
                <p className="text-[11px] text-[#a8a29e]">提问后这里会展示知识库引用来源</p>
              )}
            </div>
          </div>
        </aside>
      </div>

      {/* 重命名对话弹窗 */}
      <Modal
        title="重命名对话"
        open={!!renameConv}
        onCancel={() => setRenameConv(null)}
        onOk={() => {
          if (renameConv && renameConv.title.trim()) {
            handleUpdateTitle(renameConv.id, renameConv.title.trim())
          }
          setRenameConv(null)
        }}
        okText="保存"
        cancelText="取消"
      >
        <Input
          value={renameConv?.title || ""}
          onChange={(e) => setRenameConv((prev) => (prev ? { ...prev, title: e.target.value } : prev))}
          onPressEnter={() => {
            if (renameConv && renameConv.title.trim()) {
              handleUpdateTitle(renameConv.id, renameConv.title.trim())
            }
            setRenameConv(null)
          }}
          placeholder="输入新的对话名称"
        />
      </Modal>
    </div>
    </XProvider>
  )
}
