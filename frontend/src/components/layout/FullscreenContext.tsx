import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react"

interface FullscreenContextType {
  isChatFullscreen: boolean
  enterChatFullscreen: () => void
  exitChatFullscreen: () => void
  toggleChatFullscreen: () => void
}

const FullscreenContext = createContext<FullscreenContextType | null>(null)

export function FullscreenProvider({ children }: { children: ReactNode }) {
  const [isChatFullscreen, setIsChatFullscreen] = useState(false)

  const enterChatFullscreen = useCallback(
    () => setIsChatFullscreen(true),
    []
  )
  const exitChatFullscreen = useCallback(
    () => setIsChatFullscreen(false),
    []
  )
  const toggleChatFullscreen = useCallback(
    () => setIsChatFullscreen((prev) => !prev),
    []
  )

  return (
    <FullscreenContext.Provider
      value={{
        isChatFullscreen,
        enterChatFullscreen,
        exitChatFullscreen,
        toggleChatFullscreen,
      }}
    >
      {children}
    </FullscreenContext.Provider>
  )
}

export function useFullscreen() {
  const ctx = useContext(FullscreenContext)
  if (!ctx) {
    throw new Error(
      "useFullscreen must be used within FullscreenProvider"
    )
  }
  return ctx
}
