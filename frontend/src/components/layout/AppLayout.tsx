import { Outlet, useLocation, useNavigate } from "react-router-dom"
import { useEffect } from "react"
import { cn } from "@/lib/utils"
import { FullscreenProvider, useFullscreen } from "./FullscreenContext"
import { SidebarProvider, useSidebar } from "./SidebarContext"
import AppNavbar from "./AppNavbar"

function LayoutInner() {
  const location = useLocation()
  const navigate = useNavigate()
  const { isChatFullscreen, exitChatFullscreen } = useFullscreen()
  const { setMobileOpen } = useSidebar()

  // Auto-exit fullscreen when leaving chat page
  useEffect(() => {
    if (isChatFullscreen && location.pathname !== "/chat") {
      exitChatFullscreen()
    }
  }, [location.pathname, isChatFullscreen, exitChatFullscreen])

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault()
        navigate("/knowledge-base", { state: { focusSearch: true } })
      }
      if (e.key === "Escape") {
        setMobileOpen(false)
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [navigate, setMobileOpen])

  const isChat = location.pathname === "/chat"

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar Navigation */}
      {!isChatFullscreen && <AppNavbar />}

      {/* Main Content */}
      <main
        className={cn(
          "flex-1 min-w-0 bg-background",
          isChat && !isChatFullscreen ? "overflow-hidden" : "overflow-y-auto"
        )}
      >
        <div
          className={cn(
            "h-full",
            isChat && !isChatFullscreen ? "" : "p-6 lg:p-8"
          )}
        >
          <Outlet />
        </div>
      </main>
    </div>
  )
}

export default function AppLayout() {
  return (
    <SidebarProvider>
      <FullscreenProvider>
        <LayoutInner />
      </FullscreenProvider>
    </SidebarProvider>
  )
}
