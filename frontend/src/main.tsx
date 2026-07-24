import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider } from "react-router-dom"
import { Toaster } from "sonner"
import { AuthProvider } from "@/context/AuthContext"
import router from "./router"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AuthProvider>
      <RouterProvider router={router} />
      <Toaster position="top-right" richColors />
    </AuthProvider>
  </StrictMode>
)
