import { createBrowserRouter, Navigate } from "react-router-dom"
import AppLayout from "@/components/layout/AppLayout"
import ProtectedRoute from "@/components/layout/ProtectedRoute"
import Dashboard from "@/views/Dashboard"
import KnowledgeBase from "@/views/KnowledgeBase"
import CategoryManage from "@/views/CategoryManage"
import Chat from "@/views/Chat"
import Profile from "@/views/Profile"
import AuditLog from "@/views/AuditLog"
import UserManage from "@/views/UserManage"
import RoleManage from "@/views/RoleManage"
import PromptMarket from "@/views/PromptMarket"
import ParseStrategies from "@/views/ParseStrategies"
import ModelConfig from "@/views/ModelConfig"
import RetrievalConfig from "@/views/RetrievalConfig"
import MenuManage from "@/views/MenuManage"
import DataAnalysis from "@/views/DataAnalysis"
import Login from "@/views/Login"

/**
 * 受保护的路由包装器
 * 所有业务页面都需要登录后才能访问
 */
function ProtectedLayout() {
  return (
    <ProtectedRoute>
      <AppLayout />
    </ProtectedRoute>
  )
}

const router = createBrowserRouter([
  {
    path: "/login",
    element: (
      <ProtectedRoute requireAuth={false}>
        <Login />
      </ProtectedRoute>
    ),
  },
  {
    path: "/",
    element: <ProtectedLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "knowledge-base", element: <KnowledgeBase /> },
      { path: "category", element: <CategoryManage /> },
      { path: "chat", element: <Chat /> },
      { path: "llm-config", element: <Navigate to="/profile" replace /> },
      { path: "profile", element: <Profile /> },
      { path: "audit-log", element: <AuditLog /> },
      { path: "users", element: <UserManage /> },
      { path: "roles", element: <RoleManage /> },
      { path: "menu-manage", element: <MenuManage /> },
      { path: "prompt-market", element: <PromptMarket /> },
      { path: "parse-strategies", element: <ParseStrategies /> },
      { path: "model-config", element: <ModelConfig /> },
      { path: "config-center", element: <Navigate to="/model-config" replace /> },
      { path: "retrieval-config", element: <RetrievalConfig /> },
      { path: "data-analysis", element: <DataAnalysis /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
])

export default router
