import { useEffect, useRef } from "react"
import * as echarts from "echarts"
import type { EChartsOption } from "echarts"

interface EChartsCardProps {
  id: string
  option: EChartsOption
  title?: string
  height?: number
  className?: string
}

export default function EChartsCard({ id, option, title, height = 320, className = "" }: EChartsCardProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!chartRef.current) return
    if (!option || typeof option !== "object") return

    // 如果已存在实例，先销毁
    if (instanceRef.current) {
      instanceRef.current.dispose()
    }

    try {
      const inst = echarts.init(chartRef.current, undefined, { renderer: "canvas" })
      instanceRef.current = inst
      inst.setOption(option)

      const handleResize = () => inst.resize()
      window.addEventListener("resize", handleResize)

      return () => {
        window.removeEventListener("resize", handleResize)
        inst.dispose()
        instanceRef.current = null
      }
    } catch {
      return
    }
  }, [option, id])

  return (
    <div className={`bg-white rounded-2xl border border-[#e7e5e4] p-4 shadow-[0_1px_3px_rgba(0,0,0,0.04)] ${className}`}>
      {title && <p className="text-sm font-semibold text-[#292524] mb-3">{title}</p>}
      <div ref={chartRef} style={{ width: "100%", height }} />
    </div>
  )
}
