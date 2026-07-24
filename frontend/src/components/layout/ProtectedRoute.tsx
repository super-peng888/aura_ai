/**
 * 路由守卫组件
 *
 * 已登录用户才能访问子路由；未登录重定向到 /login。
 * 已登录用户访问 /login 时重定向到 /。
 */

import { Navigate, useLocation } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { Spinner } from "@/components/ui/spinner"

interface ProtectedRouteProps {
  children: React.ReactNode
  requireAuth?: boolean
}

export default function ProtectedRoute({
  children,
  requireAuth = true,
}: ProtectedRouteProps) {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spinner className="size-8 text-primary" />
      </div>
    )
  }

  // 需要登录但未登录
  if (requireAuth && !isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  // 已登录但访问登录页
  if (!requireAuth && isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}
