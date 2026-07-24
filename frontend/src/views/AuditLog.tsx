import { useState, useEffect, useCallback } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import PageHeader from "@/components/layout/PageHeader"
import { api } from "@/api/client"
import { toast } from "sonner"
import {
  Shield,
  Search,
  Loader2,
  FileText,
  Folder,
  MessageSquare,
  User,
  Calendar,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"

interface AuditLogItem {
  id: string
  user_id?: string
  action: string
  resource_type?: string
  resource_id?: string
  details: Record<string, unknown>
  ip_address?: string
  user_agent?: string
  created_at: string
}

const actionLabels: Record<string, string> = {
  "document:create": "创建文档",
  "document:delete": "删除文档",
  "category:create": "创建分类",
  "category:update": "更新分类",
  "category:delete": "删除分类",
  "chat:use": "使用对话",
}

const actionIcons: Record<string, React.ElementType> = {
  document: FileText,
  category: Folder,
  chat: MessageSquare,
}

function formatDateTime(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`
}

export default function AuditLog() {
  const [logs, setLogs] = useState<AuditLogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [searchAction, setSearchAction] = useState("")

  const loadLogs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get<{
        items: AuditLogItem[]
        total: number
      }>("/audit-logs", {
        params: {
          page,
          page_size: pageSize,
          ...(searchAction ? { action: searchAction } : {}),
        },
      })
      setLogs(res.items || [])
      setTotal(res.total || 0)
    } catch {
      toast.error("加载审计日志失败")
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, searchAction])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-6">
      <PageHeader />

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#292524] tracking-tight">审计日志</h2>
          <p className="text-sm text-[#a8a29e] mt-1">追踪系统中的关键操作记录</p>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
          <input
            type="text"
            placeholder="搜索操作类型..."
            value={searchAction}
            onChange={(e) => { setSearchAction(e.target.value); setPage(1) }}
            className="w-48 pl-9 pr-4 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
          />
        </div>
      </div>

      <Card className="glass-card rounded-[10px] border-[#e7e5e4]">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="size-6 animate-spin text-primary" />
            </div>
          ) : logs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
                <Shield className="size-8 text-[#a8a29e]" />
              </div>
              <h3 className="text-base font-semibold text-[#44403c] mb-1">暂无审计记录</h3>
              <p className="text-sm text-[#a8a29e]">系统操作将自动记录在此处</p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#e7e5e4]">
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">操作</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">用户</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">资源</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">IP</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#f5f5f4]">
                    {logs.map((log) => {
                      const resourceType = log.action?.split(":")[0] || ""
                      const Icon = actionIcons[resourceType] || Shield
                      return (
                        <tr key={log.id} className="hover:bg-primary/[0.02] transition-colors">
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-2.5">
                              <div className="w-8 h-8 rounded-lg bg-[#f5f5f4] flex items-center justify-center">
                                <Icon className="size-4 text-[#57534e]" />
                              </div>
                              <div>
                                <p className="text-sm font-medium text-[#44403c]">
                                  {actionLabels[log.action] || log.action}
                                </p>
                                {!!log.details?.method && (
                                  <p className="text-[10px] text-[#a8a29e]">
                                    {String(log.details.method)} {String(log.details.path || "")}
                                  </p>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-1.5">
                              <User className="size-3 text-[#a8a29e]" />
                              <span className="text-sm text-[#44403c]">{log.user_id ? log.user_id.slice(0, 8) + "..." : "系统"}</span>
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            <span className="text-sm text-[#44403c]">{log.resource_type || "—"}</span>
                            {log.resource_id && (
                              <span className="text-[10px] text-[#a8a29e] ml-1">{log.resource_id.slice(0, 8)}...</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-sm text-[#44403c]">{log.ip_address || "—"}</td>
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-1.5 text-sm text-[#44403c]">
                              <Calendar className="size-3 text-[#a8a29e]" />
                              {formatDateTime(log.created_at)}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between px-4 py-3 border-t border-[#e7e5e4]">
                <span className="text-xs text-[#a8a29e]">
                  共 {total} 条，第 {page} / {totalPages} 页
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 px-2"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 px-2"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
