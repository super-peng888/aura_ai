import { useEffect, useRef, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import PageHeader from "@/components/layout/PageHeader"
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Cloud,
  Database,
  Cpu,
  Globe,
  Terminal,
  Zap,
  Activity,
} from "lucide-react"
import * as echarts from "echarts"
import { api } from "@/api/client"

interface DashboardStats {
  total_documents: number
  total_users: number
  total_conversations: number
  completed_documents: number
  pending_documents: number
}

interface TrendData {
  period: string
  labels: string[]
  document_counts: number[]
  conversation_counts: number[]
  active_user_counts: number[]
}

interface InfraItem {
  name: string
  icon: React.ElementType
  status: "online" | "busy" | "offline"
  load: string | null
}

const topAgents = [
  { name: "Aura Customer Ops", score: 98.2, avatar: "https://api.dicebear.com/7.x/bottts/svg?seed=aura&backgroundColor=ffb59e", color: "#2563eb" },
  { name: "Echo Support Dev", score: 94.5, avatar: "https://api.dicebear.com/7.x/bottts/svg?seed=echo&backgroundColor=d6ed7a", color: "#3b82f6" },
]

const systemLogs = [
  { time: "09:24:12", level: "info", text: "Initializing system node cluster_alpha_v2..." },
  { time: "09:24:14", level: "success", text: "Handshake established with VectorDB: SUCCESS" },
  { time: "09:24:18", level: "info", text: 'Agent "Aura Ops" status: ONLINE' },
  { time: "09:25:01", level: "warn", text: "WARN: High latency detected on GPU_04-B (44ms)" },
  { time: "09:25:05", level: "info", text: "Re-routing non-critical inference tasks to Node_04-C..." },
  { time: "09:26:12", level: "success", text: "Global token consumption sync completed." },
  { time: "09:27:00", level: "info", text: "Listening for incoming requests...", active: true },
]

function getLogColor(level: string) {
  switch (level) {
    case "success": return "text-secondary"
    case "warn": return "text-destructive"
    default: return "text-primary"
  }
}

function StatCard({ title, value, icon: Icon, trend, trendType }: {
  title: string; value: string; icon: React.ElementType; trend?: string; trendType?: "up" | "down" | "neutral"
}) {
  const TrendIcon = trendType === "up" ? TrendingUp : trendType === "down" ? TrendingDown : Minus
  const trendColor = trendType === "up" ? "text-secondary" : trendType === "down" ? "text-destructive" : "text-muted-foreground"

  return (
    <Card className="glass-card rounded-[10px] border-[#e7e5e4] relative overflow-hidden hover:scale-[1.01] transition-transform duration-300">
      <div className="absolute top-0 right-0 w-24 h-24 rounded-full bg-primary/5 blur-2xl" />
      <CardContent className="p-6">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm text-muted-foreground font-medium">{title}</span>
          <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-primary/10">
            <Icon className="size-[18px] text-primary" />
          </div>
        </div>
        <div className="flex items-end gap-2">
          <span className="text-[28px] font-bold text-foreground tracking-tight">{value}</span>
          {trend && (
            <span className={`flex items-center gap-0.5 text-xs font-bold mb-1.5 ${trendColor}`}>
              <TrendIcon className="size-3" />
              {trend}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [trends, setTrends] = useState<TrendData | null>(null)
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstanceRef = useRef<echarts.ECharts | null>(null)
  const [throughputPeriod, setThroughputPeriod] = useState<"daily" | "weekly">("daily")
  const [infraItems, setInfraItems] = useState<InfraItem[]>([
    { name: "Main Cluster Alpha", icon: Cloud, status: "online", load: null },
    { name: "Vector Database", icon: Database, status: "online", load: null },
    { name: "GPU Node 04-B", icon: Cpu, status: "busy", load: "88%" },
    { name: "API Gateway", icon: Globe, status: "online", load: null },
  ])
  const [isHealthChecking, setIsHealthChecking] = useState(false)

  // 加载统计数据
  useEffect(() => {
    api.get<DashboardStats>("/dashboard/stats")
      .then(setStats)
      .catch(() => {})
  }, [])

  // 加载趋势数据
  useEffect(() => {
    api.get<TrendData>(`/dashboard/trends?period=${throughputPeriod}`)
      .then(setTrends)
      .catch(() => {})
  }, [throughputPeriod])

  // 健康检查
  const checkHealth = async () => {
    setIsHealthChecking(true)
    try {
      const res = await fetch("/health")
      const isOk = res.ok
      setInfraItems((prev) =>
        prev.map((item) => ({
          ...item,
          status: isOk ? (item.name === "GPU Node 04-B" ? "busy" : "online") : "offline",
        }))
      )
      if (!isOk) {
        toast.warning("部分服务状态异常")
      }
    } catch {
      setInfraItems((prev) => prev.map((item) => ({ ...item, status: "offline" })))
      toast.error("无法连接到后端服务")
    } finally {
      setIsHealthChecking(false)
    }
  }

  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 30000)
    return () => clearInterval(timer)
  }, [])

  // 渲染趋势图表
  useEffect(() => {
    if (!chartRef.current || !trends) return

    // 销毁旧实例
    if (chartInstanceRef.current) {
      chartInstanceRef.current.dispose()
    }

    const chart = echarts.init(chartRef.current)
    chartInstanceRef.current = chart

    const colors = {
      doc: ["rgba(37,99,235,0.7)", "rgba(37,99,235,0.15)"],
      conv: ["rgba(16,185,129,0.7)", "rgba(16,185,129,0.15)"],
      user: ["rgba(245,158,11,0.7)", "rgba(245,158,11,0.15)"],
    }

    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: {
        data: ["文档上传", "会话数", "活跃用户"],
        bottom: 0,
        textStyle: { color: "#89726b", fontSize: 11 },
      },
      grid: { left: 10, right: 10, bottom: 40, top: 20, containLabel: true },
      xAxis: {
        type: "category",
        data: trends.labels,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "#89726b", fontSize: 11, fontFamily: "Plus Jakarta Sans" },
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          name: "文档上传",
          type: "bar",
          data: trends.document_counts,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: colors.doc[0] },
              { offset: 1, color: colors.doc[1] },
            ]),
            borderRadius: [6, 6, 0, 0],
          },
          barWidth: "20%",
        },
        {
          name: "会话数",
          type: "bar",
          data: trends.conversation_counts,
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: colors.conv[0] },
              { offset: 1, color: colors.conv[1] },
            ]),
            borderRadius: [6, 6, 0, 0],
          },
          barWidth: "20%",
        },
        {
          name: "活跃用户",
          type: "line",
          data: trends.active_user_counts,
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { color: "#f59e0b", width: 2 },
          itemStyle: { color: "#f59e0b" },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(245,158,11,0.2)" },
              { offset: 1, color: "rgba(245,158,11,0)" },
            ]),
          },
        },
      ],
    })

    const handleResize = () => chart.resize()
    window.addEventListener("resize", handleResize)
    return () => {
      window.removeEventListener("resize", handleResize)
      chart.dispose()
      chartInstanceRef.current = null
    }
  }, [trends])

  return (
    <div className="space-y-6">
      <PageHeader />
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-headline-md font-bold text-foreground tracking-tight">System Overview</h2>
          <p className="text-body-md text-muted-foreground mt-1.5">Real-time infrastructure health and performance metrics.</p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="rounded-xl text-xs border-[#e7e5e4]"
          onClick={checkHealth}
          disabled={isHealthChecking}
        >
          {isHealthChecking ? (
            <span className="inline-block size-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-1.5" />
          ) : (
            <Zap className="size-3 mr-1.5" />
          )}
          刷新状态
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {stats ? (
          <>
            <StatCard title="总文档数" value={stats.total_documents.toLocaleString()} icon={Database} trendType="neutral" />
            <StatCard title="总用户数" value={stats.total_users.toLocaleString()} icon={Activity} trendType="neutral" />
            <StatCard title="总会话数" value={stats.total_conversations.toLocaleString()} icon={Zap} trendType="neutral" />
            <StatCard title="已完成文档" value={stats.completed_documents.toLocaleString()} icon={Cloud} trendType="neutral" />
          </>
        ) : (
          <>
            {Array.from({ length: 4 }).map((_, i) => (
              <Card key={i} className="glass-card rounded-[10px] border-[#e7e5e4] animate-pulse">
                <div className="p-6 space-y-3">
                  <div className="h-4 bg-[#f5f5f4] rounded w-1/2" />
                  <div className="h-8 bg-[#f5f5f4] rounded w-1/3" />
                </div>
              </Card>
            ))}
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2 glass-card rounded-[10px] border-[#e7e5e4] p-6">
          <div className="flex justify-between items-center mb-6">
            <h4 className="text-lg font-semibold text-foreground">Activity Trends</h4>
            <div className="flex bg-white/20 p-1 rounded-full border border-[#e7e5e4] backdrop-blur-md">
              <button
                onClick={() => setThroughputPeriod("daily")}
                className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all duration-300 ${
                  throughputPeriod === "daily" ? "bg-white/40 text-foreground shadow-sm" : "text-muted-foreground/60 hover:text-foreground"
                }`}
              >
                Daily
              </button>
              <button
                onClick={() => setThroughputPeriod("weekly")}
                className={`px-4 py-1.5 rounded-full text-xs font-bold transition-all duration-300 ${
                  throughputPeriod === "weekly" ? "bg-white/40 text-foreground shadow-sm" : "text-muted-foreground/60 hover:text-foreground"
                }`}
              >
                Weekly
              </button>
            </div>
          </div>
          <div ref={chartRef} className="h-64 w-full" />
        </Card>

        <Card className="glass-card rounded-[10px] border-[#e7e5e4] p-6">
          <h4 className="text-lg font-semibold text-foreground mb-4">Infrastructure</h4>
          <div className="space-y-2">
            {infraItems.map((item) => (
              <div
                key={item.name}
                className="flex items-center justify-between p-3 rounded-2xl hover:bg-[#f5f5f4] transition-all duration-200 cursor-pointer border border-transparent hover:border-[#e7e5e4]"
              >
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${item.status === "busy" ? "bg-primary/10" : item.status === "offline" ? "bg-destructive/10" : "bg-secondary/10"}`}>
                    <item.icon
                      className="size-[18px]"
                      style={{
                        color: item.status === "busy" ? "#2563eb" : item.status === "offline" ? "#ba1a1a" : "#57534e",
                      }}
                    />
                  </div>
                  <span className="text-sm font-medium text-foreground">{item.name}</span>
                </div>
                {item.load ? (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-bold uppercase tracking-wider text-primary">Load {item.load}</span>
                    <span className="w-2 h-2 rounded-full animate-pulse bg-primary shadow-[0_0_8px_rgba(37,99,235,0.5)]" />
                  </div>
                ) : (
                  <span
                    className={`w-2 h-2 rounded-full shadow-[0_0_8px_rgba(39,201,63,0.6)] ${
                      item.status === "offline" ? "bg-destructive shadow-[0_0_8px_rgba(186,26,26,0.6)]" : "bg-success"
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
          <Button
            className="w-full mt-4 btn-primary-gradient rounded-full font-bold text-sm scale-95 active:scale-90 flex items-center justify-center gap-2 h-10"
            onClick={checkHealth}
            disabled={isHealthChecking}
          >
            <Zap className="size-4" /> System Diagnostics
          </Button>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="glass-card rounded-[10px] border-[#e7e5e4] p-6 overflow-hidden relative">
          <h4 className="text-lg font-semibold text-foreground mb-4">Top Performing Agents</h4>
          <div className="space-y-3">
            {topAgents.map((agent) => (
              <div
                key={agent.name}
                className="flex items-center gap-4 p-4 rounded-2xl bg-[#f5f5f4] border border-[#e7e5e4] hover:bg-[#f5f5f4] hover:border-[#e7e5e4] transition-all duration-200 cursor-pointer"
              >
                <img src={agent.avatar} alt={agent.name} className="w-12 h-12 rounded-xl object-cover ring-2 ring-white/50" />
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between items-center">
                    <h5 className="text-sm font-semibold text-foreground truncate">{agent.name}</h5>
                    <span className="text-secondary font-bold text-xs flex items-center gap-1">
                      {agent.score}% <span className="text-muted-foreground font-normal opacity-60">SR</span>
                    </span>
                  </div>
                  <div className="w-full h-2 bg-surface-container-low rounded-full mt-2 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-1000 ease-out"
                      style={{ width: `${agent.score}%`, background: `linear-gradient(to right, #2563eb, ${agent.color})` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <div className="glass-card-strong rounded-[10px] shadow-warm relative overflow-hidden h-[300px] flex flex-col">
          <div className="flex items-center justify-between shrink-0 px-5 pt-5 pb-3 border-b border-outline-variant">
            <div className="flex items-center gap-2.5">
              <div className="flex gap-1.5">
                <div className="w-3 h-3 rounded-full bg-destructive/50" />
                <div className="w-3 h-3 rounded-full bg-secondary/50" />
                <div className="w-3 h-3 rounded-full bg-primary/50" />
              </div>
              <span className="font-mono text-xs text-muted-foreground ml-2 tracking-wider">system_logs.sh</span>
            </div>
            <Terminal className="text-muted-foreground text-sm hover:text-primary transition-colors cursor-pointer size-4" />
          </div>
          <div className="font-mono text-xs space-y-2 px-5 py-3 h-[210px] overflow-y-auto flex-1 bg-black/[0.02] rounded-b-[10px]">
            {systemLogs.map((log, idx) => (
              <p key={idx} className="text-muted-foreground/70 leading-relaxed">
                <span className="inline-block w-20 shrink-0 text-muted-foreground/40">[{log.time}]</span>
                <span className={getLogColor(log.level) + " font-semibold"}>{log.level.toUpperCase().padEnd(7)}</span>
                <span>{log.text}</span>
                {log.active && <span className="inline-block w-0.5 h-4 align-middle ml-0.5 cursor-blink bg-primary-container" />}
              </p>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
