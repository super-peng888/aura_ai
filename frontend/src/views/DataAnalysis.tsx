import { useEffect, useRef, useState, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { api, fetchStream, parseSSEStream } from "@/api/client"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import PageHeader from "@/components/layout/PageHeader"
import EChartsCard from "@/components/ai-elements/echarts-card"
import {
  Send,
  BarChart3,
  Download,
  Loader2,
  User,
  Sparkles,
  Trash2,
  Database,
  History,
  Save,
  ChevronRight,
  X,
} from "lucide-react"

interface DataSourceItem {
  id: string
  name: string
  type: string
}

interface QueryLogItem {
  id: string
  natural_language_query: string | null
  generated_sql: string | null
  status: string
  created_at: string
}

interface ChartConfig {
  title: string
  type: string
  option: any
}

interface TableConfig {
  title: string
  headers: string[]
  rows: (string | number)[][]
}

interface BIMessage {
  role: "user" | "assistant"
  content: string
  sql?: string
  queryResult?: { columns: string[]; rows: string[][]; row_count: number }
  queryError?: string
  charts?: ChartConfig[]
  tables?: TableConfig[]
}

export default function DataAnalysis() {
  const [messages, setMessages] = useState<BIMessage[]>([
    {
      role: "assistant",
      content: "你好！我是你的数据分析助手。你可以直接描述你想要的分析，例如：\n\n• 帮我分析一下最近7天各时段的会话量变化\n• 展示一下文档解析状态的分布饼图\n• 对比一下不同分类下的文档数量\n\n我会为你生成美观的图表和专业的分析结论。",
    },
  ])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // 数据源
  const [dataSources, setDataSources] = useState<DataSourceItem[]>([])
  const [selectedDataSource, setSelectedDataSource] = useState<string>("")

  // 查询历史
  const [queryLogs, setQueryLogs] = useState<QueryLogItem[]>([])
  const [showHistory, setShowHistory] = useState(false)

  // 滚动
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // 加载数据源和查询历史
  useEffect(() => {
    api.get<DataSourceItem[]>("/bi/data-sources")
      .then((res) => {
        setDataSources(res || [])
      })
      .catch(() => {})

    loadQueryLogs()
  }, [])

  const loadQueryLogs = useCallback(() => {
    api.get<QueryLogItem[]>("/bi/query-logs?limit=20")
      .then((res) => setQueryLogs(res || []))
      .catch(() => {})
  }, [])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return
    const userMsg: BIMessage = { role: "user", content: input.trim() }
    setMessages((prev) => [...prev, userMsg])
    setInput("")
    setIsLoading(true)

    // 准备 assistant 占位消息（流式更新）
    const assistantMsg: BIMessage = {
      role: "assistant",
      content: "",
      sql: "",
      charts: [],
      tables: [],
    }
    setMessages((prev) => [...prev, assistantMsg])

    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }))
      const reader = await fetchStream("/bi/chat/stream", {
        messages: [...history, { role: "user", content: userMsg.content }],
        data_source_id: selectedDataSource || undefined,
        temperature: 0.3,
        stream: true,
      })

      // 使用临时变量累积当前 assistant 消息的状态
      let currentSql = ""
      let currentAnalysis = ""
      let currentQueryResult: BIMessage["queryResult"] = undefined
      let currentQueryError = ""
      let currentCharts: ChartConfig[] = []
      let currentTables: TableConfig[] = []

      for await (const event of parseSSEStream(reader)) {
        const { event: eventType, data } = event

        switch (eventType) {
          case "sql":
            currentSql = data || ""
            break
          case "query_result":
            currentQueryResult = data
            break
          case "error":
            currentQueryError = data
            break
          case "analysis":
            currentAnalysis = data || ""
            break
          case "chart":
            if (data) currentCharts.push(data)
            break
          case "table":
            if (data) currentTables.push(data)
            break
          case "done":
            break
        }

        // 实时更新消息
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last.role === "assistant") {
            last.sql = currentSql
            last.queryResult = currentQueryResult
            last.queryError = currentQueryError
            last.content = currentAnalysis
            last.charts = [...currentCharts]
            last.tables = [...currentTables]
          }
          return next
        })
      }

      // 刷新查询历史
      loadQueryLogs()
    } catch (err: any) {
      toast.error(err.message || "分析失败，请重试")
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last.role === "assistant") {
          last.content = "分析失败，请重试。"
        }
        return next
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleExport = async () => {
    try {
      const allCharts: ChartConfig[] = []
      const allTables: TableConfig[] = []
      messages.forEach((m) => {
        if (m.charts) allCharts.push(...m.charts)
        if (m.tables) allTables.push(...m.tables)
      })

      const res = await api.post<any>("/bi/export", {
        title: "数据分析报告",
        messages: messages.map((m) => ({ role: m.role, content: m.content })),
        charts: allCharts,
        tables: allTables,
      })

      const html = res.html
      const blob = new Blob([html], { type: "text/html" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `数据分析报告_${new Date().toISOString().slice(0, 10)}.html`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      toast.success("报告已下载")
    } catch {
      toast.error("导出失败")
    }
  }

  const handleSaveReport = async () => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant")
    if (!lastAssistant || !lastAssistant.charts?.length) {
      toast.error("当前没有可保存的图表")
      return
    }
    try {
      await api.post("/bi/reports", {
        title: `数据分析报告 ${new Date().toLocaleString("zh-CN")}`,
        description: lastAssistant.content?.slice(0, 200),
        chart_configs: lastAssistant.charts,
      })
      toast.success("报表已保存")
    } catch {
      toast.error("保存失败")
    }
  }

  const handleClear = () => {
    if (!confirm("确定要清空所有对话吗？")) return
    setMessages([
      {
        role: "assistant",
        content: "你好！我是你的数据分析助手。你可以直接描述你想要的分析，例如：\n\n• 帮我分析一下最近7天各时段的会话量变化\n• 展示一下文档解析状态的分布饼图\n• 对比一下不同分类下的文档数量\n\n我会为你生成美观的图表和专业的分析结论。",
      },
    ])
  }

  const handleLoadHistory = (log: QueryLogItem) => {
    if (!log.generated_sql) return
    const assistantMsg: BIMessage = {
      role: "assistant",
      content: log.natural_language_query || "历史查询",
      sql: log.generated_sql,
    }
    setMessages((prev) => [
      ...prev,
      { role: "user", content: log.natural_language_query || "历史查询" },
      assistantMsg,
    ])
    setShowHistory(false)
  }

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] -m-6 lg:-m-8 p-6 lg:p-8">
      <PageHeader />

      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <BarChart3 className="size-5 text-primary" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#292524]">数据分析</h2>
            <p className="text-xs text-[#a8a29e]">对话式 BI 报表生成</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* 数据源选择 */}
          <select
            value={selectedDataSource}
            onChange={(e) => setSelectedDataSource(e.target.value)}
            className="h-9 px-3 text-xs rounded-xl border border-[#e7e5e4] bg-white text-[#44403c] outline-none focus:ring-2 focus:ring-primary/20"
          >
            <option value="">默认数据源</option>
            {dataSources.map((ds) => (
              <option key={ds.id} value={ds.id}>
                {ds.name} ({ds.type})
              </option>
            ))}
          </select>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowHistory(true)}
            className="rounded-xl border-[#e7e5e4] text-[#78716c]"
          >
            <History className="size-3.5 mr-1.5" />
            历史
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleClear}
            className="rounded-xl border-[#e7e5e4] text-[#78716c]"
          >
            <Trash2 className="size-3.5 mr-1.5" />
            清空
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleSaveReport}
            className="rounded-xl border-[#e7e5e4] text-[#78716c]"
          >
            <Save className="size-3.5 mr-1.5" />
            保存报表
          </Button>

          <Button
            size="sm"
            onClick={handleExport}
            className="btn-primary-gradient rounded-xl"
            disabled={messages.length <= 1}
          >
            <Download className="size-3.5 mr-1.5" />
            导出报告
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex flex-1 min-h-0 gap-4">
        {/* Messages */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 overflow-y-auto space-y-4 min-h-0 pr-1">
            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={cn(
                  "flex gap-3",
                  msg.role === "user" ? "flex-row-reverse" : "flex-row"
                )}
              >
                <div
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-1",
                    msg.role === "user" ? "bg-[#292524]" : "bg-primary/10"
                  )}
                >
                  {msg.role === "user" ? (
                    <User className="size-4 text-white" />
                  ) : (
                    <Sparkles className="size-4 text-primary" />
                  )}
                </div>

                <div className={cn("max-w-[80%] space-y-3", msg.role === "user" ? "items-end" : "items-start")}>
                  {/* Text */}
                  {msg.content && (
                    <div
                      className={cn(
                        "px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap",
                        msg.role === "user"
                          ? "bg-[#292524] text-white rounded-tr-sm"
                          : "bg-white border border-[#e7e5e4] text-[#44403c] rounded-tl-sm"
                      )}
                    >
                      {msg.content}
                    </div>
                  )}

                  {/* SQL */}
                  {msg.sql && (
                    <div className="bg-[#1e1e1e] rounded-2xl p-4 overflow-x-auto">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-semibold text-[#a8a29e] uppercase tracking-wider">Generated SQL</span>
                        <span className="text-[10px] text-emerald-400 font-medium">只读查询 · 安全执行</span>
                      </div>
                      <pre className="text-xs text-emerald-300 font-mono leading-relaxed">{msg.sql}</pre>
                    </div>
                  )}

                  {/* Query Error */}
                  {msg.queryError && (
                    <div className="bg-red-50 border border-red-100 rounded-2xl p-4">
                      <p className="text-xs font-semibold text-red-600 mb-1">查询执行失败</p>
                      <p className="text-xs text-red-500">{msg.queryError}</p>
                    </div>
                  )}

                  {/* Query Result */}
                  {msg.queryResult && (
                    <div className="bg-white rounded-2xl border border-[#e7e5e4] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-x-auto">
                      <div className="flex items-center justify-between mb-3">
                        <p className="text-sm font-semibold text-[#292524]">查询结果</p>
                        <span className="text-[10px] text-[#a8a29e]">共 {msg.queryResult.row_count} 行</span>
                      </div>
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-[#e7e5e4]">
                            {msg.queryResult.columns.map((h, hi) => (
                              <th key={hi} className="text-left py-2 px-3 text-[#a8a29e] font-semibold uppercase tracking-wider">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {msg.queryResult.rows.map((row, ri) => (
                            <tr key={ri} className="border-b border-[#f5f5f4] last:border-0 hover:bg-[#fafaf9]">
                              {row.map((cell, ci) => (
                                <td key={ci} className="py-2 px-3 text-[#44403c] font-mono">{cell}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Charts */}
                  {msg.charts?.map((chart, cidx) => (
                    <EChartsCard
                      key={cidx}
                      id={`chart_${idx}_${cidx}`}
                      title={chart.title}
                      option={chart.option}
                      height={320}
                    />
                  ))}

                  {/* Tables */}
                  {msg.tables?.map((table, tidx) => (
                    <div
                      key={tidx}
                      className="bg-white rounded-2xl border border-[#e7e5e4] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-x-auto"
                    >
                      <p className="text-sm font-semibold text-[#292524] mb-3">{table.title}</p>
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-[#e7e5e4]">
                            {table.headers.map((h, hi) => (
                              <th key={hi} className="text-left py-2 px-3 text-[#a8a29e] font-semibold uppercase tracking-wider">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {table.rows.map((row, ri) => (
                            <tr key={ri} className="border-b border-[#f5f5f4] last:border-0 hover:bg-[#fafaf9]">
                              {row.map((cell, ci) => (
                                <td key={ci} className="py-2 px-3 text-[#44403c]">{cell}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="size-4 text-primary" />
                </div>
                <div className="bg-white border border-[#e7e5e4] rounded-2xl rounded-tl-sm px-4 py-3 flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin text-primary" />
                  <span className="text-sm text-[#78716c]">正在生成分析...</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="shrink-0 mt-4">
            <div className="flex items-end gap-2 bg-white rounded-2xl border border-[#e7e5e4] p-2 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                placeholder="描述你想要的分析，例如：展示最近7天各时段的会话量变化..."
                className="flex-1 min-h-[44px] max-h-[120px] px-3 py-2.5 text-sm text-[#44403c] placeholder:text-[#a8a29e] bg-transparent outline-none resize-none"
                rows={1}
              />
              <Button
                onClick={handleSend}
                disabled={!input.trim() || isLoading}
                className="btn-primary-gradient rounded-xl h-10 w-10 p-0 flex items-center justify-center shrink-0"
              >
                <Send className="size-4" />
              </Button>
            </div>
            <p className="text-[10px] text-[#a8a29e] mt-1.5 text-center">
              按 Enter 发送，Shift + Enter 换行
            </p>
          </div>
        </div>
      </div>

      {/* Query History Slide-over */}
      {showHistory && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/20" onClick={() => setShowHistory(false)} />
          <div className="relative w-80 bg-white h-full shadow-xl border-l border-[#e7e5e4] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-[#e7e5e4]">
              <div className="flex items-center gap-2">
                <History className="size-4 text-primary" />
                <h3 className="text-sm font-semibold text-[#292524]">查询历史</h3>
              </div>
              <button onClick={() => setShowHistory(false)} className="p-1 rounded-lg hover:bg-[#f5f5f4]">
                <X className="size-4 text-[#a8a29e]" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {queryLogs.length === 0 && (
                <p className="text-xs text-[#a8a29e] text-center py-8">暂无查询记录</p>
              )}
              {queryLogs.map((log) => (
                <button
                  key={log.id}
                  onClick={() => handleLoadHistory(log)}
                  className="w-full text-left p-3 rounded-xl border border-[#e7e5e4] hover:border-primary/30 hover:bg-primary/5 transition-all group"
                >
                  <p className="text-xs text-[#44403c] line-clamp-2 mb-1.5">
                    {log.natural_language_query || "直接 SQL 查询"}
                  </p>
                  {log.generated_sql && (
                    <code className="text-[10px] text-[#a8a29e] font-mono line-clamp-1 block">
                      {log.generated_sql}
                    </code>
                  )}
                  <div className="flex items-center justify-between mt-2">
                    <span className={cn(
                      "text-[10px] px-1.5 py-0.5 rounded-full",
                      log.status === "success" ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600"
                    )}>
                      {log.status === "success" ? "成功" : "失败"}
                    </span>
                    <ChevronRight className="size-3 text-[#d6d3d1] group-hover:text-primary transition-colors" />
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
