import { useState, useEffect, useCallback } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import PageHeader from "@/components/layout/PageHeader"
import { api } from "@/api/client"
import { toast } from "sonner"
import {
  Shield,
  Loader2,
  Check,
  X,
} from "lucide-react"

interface RoleItem {
  id: string
  name: string
  description?: string
  created_at: string
}

interface PermissionItem {
  id: string
  code: string
  name: string
  description?: string
}

export default function RoleManage() {
  const [roles, setRoles] = useState<RoleItem[]>([])
  const [permissions, setPermissions] = useState<PermissionItem[]>([])
  const [rolePermissions, setRolePermissions] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(true)
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [rolesRes, permsRes] = await Promise.all([
        api.get<RoleItem[]>("/roles"),
        api.get<PermissionItem[]>("/roles/permissions/all"),
      ])
      setRoles(rolesRes || [])
      setPermissions(permsRes || [])

      // 加载每个角色的权限
      const rp: Record<string, string[]> = {}
      for (const role of rolesRes || []) {
        try {
          const perms = await api.get<PermissionItem[]>(`/roles/${role.id}/permissions`)
          rp[role.id] = (perms || []).map((p) => p.id)
        } catch {
          rp[role.id] = []
        }
      }
      setRolePermissions(rp)

      if (rolesRes && rolesRes.length > 0) {
        setSelectedRoleId(rolesRes[0].id)
      }
    } catch {
      toast.error("加载角色数据失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const togglePermission = (permId: string) => {
    if (!selectedRoleId) return
    setRolePermissions((prev) => {
      const current = prev[selectedRoleId] || []
      const next = current.includes(permId)
        ? current.filter((id) => id !== permId)
        : [...current, permId]
      return { ...prev, [selectedRoleId]: next }
    })
  }

  const handleSave = async () => {
    if (!selectedRoleId) return
    setSaving(true)
    try {
      await api.put(`/roles/${selectedRoleId}/permissions`, rolePermissions[selectedRoleId] || [])
      toast.success("权限分配已保存")
    } catch {
      toast.error("保存失败")
    } finally {
      setSaving(false)
    }
  }

  const selectedRole = roles.find((r) => r.id === selectedRoleId)
  const currentPermIds = selectedRoleId ? (rolePermissions[selectedRoleId] || []) : []

  return (
    <div className="space-y-6">
      <PageHeader />

      <div>
        <h2 className="text-xl font-bold text-[#292524] tracking-tight">角色与权限</h2>
        <p className="text-sm text-[#a8a29e] mt-1">管理角色并分配权限</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-6 animate-spin text-primary" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Role List */}
          <Card className="glass-card rounded-[10px] border-[#e7e5e4]">
            <CardContent className="p-4">
              <h3 className="text-sm font-bold text-foreground mb-3">角色列表</h3>
              <div className="space-y-1">
                {roles.map((role) => (
                  <button
                    key={role.id}
                    onClick={() => setSelectedRoleId(role.id)}
                    className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-left transition-all ${
                      selectedRoleId === role.id
                        ? "bg-primary/10 text-primary font-semibold border border-primary/15"
                        : "text-foreground hover:bg-[#f5f5f4]"
                    }`}
                  >
                    <Shield className="size-4" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm truncate">{role.name}</p>
                      <p className="text-[10px] text-muted-foreground truncate">{role.description || "—"}</p>
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Permission Assignment */}
          <Card className="lg:col-span-2 glass-card rounded-[10px] border-[#e7e5e4]">
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-sm font-bold text-foreground">
                    {selectedRole ? `${selectedRole.name} 的权限` : "权限分配"}
                  </h3>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    勾选权限分配给当前角色
                  </p>
                </div>
                <Button
                  size="sm"
                  className="btn-primary-gradient rounded-full"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4 mr-1" />}
                  保存
                </Button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {permissions.map((perm) => {
                  const checked = currentPermIds.includes(perm.id)
                  return (
                    <button
                      key={perm.id}
                      onClick={() => togglePermission(perm.id)}
                      className={`flex items-center gap-3 p-3 rounded-xl border text-left transition-all ${
                        checked
                          ? "bg-primary/5 border-primary/20"
                          : "bg-white border-[#e7e5e4] hover:border-primary/20"
                      }`}
                    >
                      <div
                        className={`w-5 h-5 rounded-md flex items-center justify-center border transition-all ${
                          checked
                            ? "bg-primary border-primary text-white"
                            : "border-[#d6d3d1]"
                        }`}
                      >
                        {checked && <Check className="size-3" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[#44403c]">{perm.name}</p>
                        <p className="text-[10px] text-[#a8a29e] truncate">{perm.code}</p>
                      </div>
                    </button>
                  )
                })}
              </div>

              {permissions.length === 0 && (
                <div className="text-center py-12 text-sm text-[#a8a29e]">暂无权限数据</div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
