import { useState, useEffect, useCallback } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import PageHeader from "@/components/layout/PageHeader"
import { api } from "@/api/client"
import { toast } from "sonner"
import {
  Users,
  Shield,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Search,
  Edit3,
  User,
} from "lucide-react"

interface UserItem {
  id: string
  username: string
  email?: string
  phone?: string
  avatar_url?: string
  role: string
  created_at: string
}

export default function UserManage() {
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [searchQuery, setSearchQuery] = useState("")

  const [showDialog, setShowDialog] = useState(false)
  const [editUser, setEditUser] = useState<UserItem | null>(null)
  const [editRole, setEditRole] = useState("user")
  const [dialogLoading, setDialogLoading] = useState(false)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get<{ items: UserItem[]; total: number }>("/users", {
        params: { page, page_size: pageSize },
      })
      setUsers(res.items || [])
      setTotal(res.total || 0)
    } catch {
      toast.error("加载用户列表失败")
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  const openEditDialog = (u: UserItem) => {
    setEditUser(u)
    setEditRole(u.role)
    setShowDialog(true)
  }

  const handleSaveRole = async () => {
    if (!editUser) return
    setDialogLoading(true)
    try {
      await api.put(`/users/${editUser.id}/role`, { role: editRole })
      toast.success("角色更新成功")
      setShowDialog(false)
      loadUsers()
    } catch {
      toast.error("角色更新失败")
    } finally {
      setDialogLoading(false)
    }
  }

  const filteredUsers = users.filter((u) =>
    !searchQuery ||
    u.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (u.email && u.email.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-6">
      <PageHeader />

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-[#292524] tracking-tight">用户管理</h2>
          <p className="text-sm text-[#a8a29e] mt-1">管理系统用户、分配角色</p>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
          <input
            type="text"
            placeholder="搜索用户..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
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
          ) : filteredUsers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="w-16 h-16 rounded-2xl bg-[#f5f5f4] flex items-center justify-center mb-4">
                <Users className="size-8 text-[#a8a29e]" />
              </div>
              <h3 className="text-base font-semibold text-[#44403c] mb-1">暂无用户</h3>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#e7e5e4]">
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">用户</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">邮箱</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">角色</th>
                      <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">注册时间</th>
                      <th className="text-right py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#f5f5f4]">
                    {filteredUsers.map((u) => (
                      <tr key={u.id} className="hover:bg-primary/[0.02] transition-colors">
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-[#f5f5f4] flex items-center justify-center text-[#57534e] text-xs font-bold">
                              {u.username?.slice(0, 2).toUpperCase()}
                            </div>
                            <span className="text-sm font-medium text-[#44403c]">{u.username}</span>
                          </div>
                        </td>
                        <td className="py-3 px-4 text-sm text-[#44403c]">{u.email || "—"}</td>
                        <td className="py-3 px-4">
                          <span className={cn(
                            "px-2 py-0.5 rounded-md text-[10px] font-medium border",
                            u.role === "admin"
                              ? "bg-red-50 text-red-600 border-red-100"
                              : "bg-[#f5f5f4] text-[#57534e] border-[#e7e5e4]"
                          )}>
                            {u.role === "admin" ? "管理员" : "普通用户"}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-sm text-[#a8a29e]">{formatDate(u.created_at)}</td>
                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={() => openEditDialog(u)}
                            className="p-1.5 rounded-lg hover:bg-[#f5f5f4] transition-colors"
                          >
                            <Edit3 className="size-4 text-[#a8a29e]" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

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

      {/* Edit Role Dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="glass-card-strong rounded-[10px] border-[#e7e5e4]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Shield className="size-5 text-primary" />
              修改角色
            </DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-[#f5f5f4] flex items-center justify-center text-[#57534e] font-bold">
                {editUser?.username?.slice(0, 2).toUpperCase()}
              </div>
              <div>
                <p className="text-sm font-medium text-[#44403c]">{editUser?.username}</p>
                <p className="text-xs text-[#a8a29e]">{editUser?.email}</p>
              </div>
            </div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">角色</label>
            <select
              className="w-full px-3 py-2 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all appearance-none"
              value={editRole}
              onChange={(e) => setEditRole(e.target.value)}
            >
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <DialogFooter className="border-t border-[#e7e5e4] pt-4">
            <Button variant="ghost" onClick={() => setShowDialog(false)}>取消</Button>
            <Button className="btn-primary-gradient rounded-full" onClick={handleSaveRole} disabled={dialogLoading}>
              {dialogLoading ? <Loader2 className="size-4 animate-spin" /> : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ")
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}
