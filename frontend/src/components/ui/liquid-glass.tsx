import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const liquidGlassVariants = cva(
  "relative overflow-hidden border backdrop-blur-xl transition-all duration-300 will-change-transform",
  {
    variants: {
      variant: {
        default:
          "bg-white/70 dark:bg-slate-950/60 border-white/50 dark:border-white/10 rounded-2xl shadow-lg",
        card:
          "bg-white/65 dark:bg-slate-950/55 border-white/40 dark:border-white/10 rounded-[1.25rem] shadow-xl",
        panel:
          "bg-white/60 dark:bg-slate-950/50 border-white/30 dark:border-white/10 rounded-3xl shadow-2xl",
        float:
          "bg-white/75 dark:bg-slate-950/65 border-white/50 dark:border-white/10 rounded-2xl shadow-2xl ring-1 ring-black/5 dark:ring-white/10",
      },
      intensity: {
        subtle: "backdrop-blur-md saturate-150",
        medium: "backdrop-blur-xl saturate-[180%]",
        strong: "backdrop-blur-2xl saturate-[200%]",
      },
    },
    defaultVariants: {
      variant: "default",
      intensity: "medium",
    },
  }
)

interface LiquidGlassProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof liquidGlassVariants> {
  /** Render slow morphing iridescent blobs behind content. */
  animated?: boolean
  /** Number of blob layers when animated (1–3). */
  blobs?: 1 | 2 | 3
}

const LiquidGlass = React.forwardRef<HTMLDivElement, LiquidGlassProps>(
  (
    {
      className,
      variant,
      intensity,
      animated = false,
      blobs = 3,
      children,
      ...props
    },
    ref
  ) => {
    return (
      <div
        ref={ref}
        className={cn(liquidGlassVariants({ variant, intensity }), className)}
        {...props}
      >
        {animated && (
          <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
            {blobs >= 1 && (
              <div
                className="liquid-glass-blob liquid-glass-blob-1"
                aria-hidden="true"
              />
            )}
            {blobs >= 2 && (
              <div
                className="liquid-glass-blob liquid-glass-blob-2"
                aria-hidden="true"
              />
            )}
            {blobs >= 3 && (
              <div
                className="liquid-glass-blob liquid-glass-blob-3"
                aria-hidden="true"
              />
            )}
          </div>
        )}
        <div className="relative z-10">{children}</div>
      </div>
    )
  }
)
LiquidGlass.displayName = "LiquidGlass"

export { LiquidGlass, liquidGlassVariants }
export type { LiquidGlassProps }
