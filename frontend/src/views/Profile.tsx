import { useState, useRef, useCallback, useEffect } from "react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { useAuth } from "@/context/AuthContext"
import { api } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import PageHeader from "@/components/layout/PageHeader"
import {
  User,
  Phone,
  Mail,
  Lock,
  Camera,
  AlertCircle,
  Save,
  ShieldCheck,
  Eye,
  EyeOff,
  Sparkles,
} from "lucide-react"

// ============================================================================
// Sub-components
// ============================================================================

function FormGroup({
  label,
  children,
  icon: Icon,
  hint,
  error,
}: {
  label: string
  children: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  hint?: string
  error?: string
}) {
  return (
    <div className="space-y-1.5">
      <Label className="flex items-center gap-1.5 text-xs font-medium text-[#78716c]">
        {Icon && <Icon className="size-3.5 text-[#a8a29e]" />}
        {label}
      </Label>
      <div className="relative">{children}</div>
      {hint && !error && <p className="text-[11px] text-[#a8a29e]">{hint}</p>}
      {error && (
        <p className="text-xs text-destructive flex items-center gap-1">
          <AlertCircle className="size-3" />
          {error}
        </p>
      )}
    </div>
  )
}

function PasswordInput({
  placeholder,
  value,
  onChange,
}: {
  placeholder: string
  value: string
  onChange: (v: string) => void
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full pr-10 py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-[#a8a29e] hover:text-[#57534e] transition-colors"
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}

// ============================================================================
// Main Profile Page
// ============================================================================

export default function Profile() {
  const { user, refreshUser } = useAuth()
  const [isSaving, setIsSaving] = useState(false)
  const [isUploading, setIsUploading] = useState(false)

  // Basic info
  const [avatarPreview, setAvatarPreview] = useState(user?.avatar_url || "")
  const [username, setUsername] = useState(user?.username || "")
  const [phone, setPhone] = useState(user?.phone || "")
  const [email, setEmail] = useState(user?.email || "")

  // Password states
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [passwordError, setPasswordError] = useState("")

  const fileInputRef = useRef<HTMLInputElement>(null)

  // Sync user
  useEffect(() => {
    if (user) {
      setAvatarPreview(user.avatar_url || "")
      setUsername(user.username || "")
      setPhone(user.phone || "")
      setEmail(user.email || "")
    }
  }, [user])



  // Avatar upload
  const handleAvatarClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      if (!file.type.startsWith("image/")) {
        toast.error("请上传图片文件")
        return
      }
      const reader = new FileReader()
      reader.onload = () => setAvatarPreview(reader.result as string)
      reader.readAsDataURL(file)

      setIsUploading(true)
      try {
        const formData = new FormData()
        formData.append("file", file)
        const res = await fetch("/api/v1/uploads/avatar", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("aura_token") || ""}`,
          },
          body: formData,
        })
        const data = await res.json()
        if (!res.ok || data.code !== 0) throw new Error(data.message || "上传失败")
        toast.success("头像已上传")
        await refreshUser()
      } catch (err: any) {
        toast.error(err.message || "头像上传失败")
      } finally {
        setIsUploading(false)
      }
      e.target.value = ""
    },
    [refreshUser]
  )

  // Save basic info
  const handleSaveBasic = useCallback(async () => {
    if (!username.trim()) {
      toast.error("用户名不能为空")
      return
    }
    setIsSaving(true)
    try {
      await api.put("/users/me", {
        username,
        email: email || undefined,
        phone: phone || undefined,
        avatar_url: avatarPreview || undefined,
      })
      await refreshUser()
      toast.success("基本信息已保存")
    } catch {
      // 错误已在 api client 中 toast
    } finally {
      setIsSaving(false)
    }
  }, [username, email, phone, avatarPreview, refreshUser])

  // Save password
  const handleSavePassword = useCallback(async () => {
    setPasswordError("")
    if (!oldPassword) {
      setPasswordError("请输入当前密码")
      return
    }
    if (!newPassword || newPassword.length < 6) {
      setPasswordError("新密码至少 6 位")
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致")
      return
    }
    try {
      await api.put("/users/me/password", {
        current_password: oldPassword,
        new_password: newPassword,
      })
      setOldPassword("")
      setNewPassword("")
      setConfirmPassword("")
      toast.success("密码已修改")
    } catch {
      // 错误已在 api client 中 toast
    }
  }, [oldPassword, newPassword, confirmPassword])

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="size-8 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <PageHeader />

      {/* 个人信息 */}
      <section className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
        <div className="px-6 py-4 border-b border-[#f5f5f4] flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
            <User className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#292524]">个人信息</h3>
            <p className="text-xs text-[#a8a29e]">管理你的基本资料与头像</p>
          </div>
        </div>
        <div className="p-6 space-y-5">
          <div className="flex items-center gap-5">
            <div className="relative">
              <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-amber-200 to-amber-500 flex items-center justify-center text-white text-2xl font-bold shadow-md overflow-hidden">
                {avatarPreview ? (
                  <img src={avatarPreview} alt={username} className="w-full h-full object-cover" />
                ) : (
                  username?.slice(0, 2).toUpperCase() || "U"
                )}
              </div>
              <button
                onClick={handleAvatarClick}
                disabled={isUploading}
                className="absolute -bottom-1 -right-1 w-7 h-7 rounded-lg bg-white border border-[#e7e5e4] text-[#78716c] hover:text-primary hover:border-primary/30 flex items-center justify-center shadow-sm transition-all"
              >
                {isUploading ? (
                  <span className="inline-block size-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
                ) : (
                  <Camera className="size-3" />
                )}
              </button>
              <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
            </div>
            <div>
              <p className="text-sm font-medium text-[#44403c]">头像</p>
              <p className="text-xs text-[#a8a29e] mt-0.5">支持 JPG、PNG 格式，最大 2MB</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <FormGroup label="用户名" icon={User}>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                className="py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"
              />
            </FormGroup>
            <FormGroup label="邮箱" icon={Mail}>
              <Input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="请输入邮箱"
                className="py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"
              />
            </FormGroup>
          </div>

          <FormGroup label="手机号" icon={Phone} hint="绑定手机号可用于登录和找回密码">
            <Input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="请输入手机号"
              className="py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"
            />
          </FormGroup>

          <div className="flex justify-end">
            <Button
              onClick={handleSaveBasic}
              disabled={isSaving}
              className="btn-primary-gradient rounded-xl px-6"
            >
              {isSaving ? (
                <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Save className="size-4 mr-2" />
              )}
              保存修改
            </Button>
          </div>
        </div>
      </section>

      {/* 用量统计 */}
      <section className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
        <div className="px-6 py-4 border-b border-[#f5f5f4] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
              <Sparkles className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#292524]">本月用量</h3>
              <p className="text-xs text-[#a8a29e]">Token 消耗配额统计</p>
            </div>
          </div>
        </div>
        <div className="p-6 space-y-5">
          {(() => {
            const used = user?.token_used_monthly || 0
            const quota = user?.token_quota_monthly || 1_000_000
            const pct = Math.min(100, Math.round((used / quota) * 100))
            return (
              <>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-[#44403c]">已用 Token</span>
                  <span className="font-semibold text-[#292524]">
                    {used.toLocaleString()} / {quota.toLocaleString()}
                  </span>
                </div>
                <div className="h-3 rounded-full bg-[#f5f5f4] overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all duration-500",
                      pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-primary"
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="flex items-center justify-between text-xs text-[#a8a29e]">
                  <span>{pct}%</span>
                  <span>{quota - used > 0 ? `剩余 ${(quota - used).toLocaleString()}` : "配额已用尽"}</span>
                </div>
              </>
            )
          })()}
        </div>
      </section>

      {/* 安全设置 */}
      <section className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
        <div className="px-6 py-4 border-b border-[#f5f5f4] flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-rose-50 text-rose-600 flex items-center justify-center">
            <ShieldCheck className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#292524]">安全设置</h3>
            <p className="text-xs text-[#a8a29e]">修改密码与账号安全</p>
          </div>
        </div>
        <div className="p-6 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <FormGroup label="当前密码" icon={Lock}>
              <PasswordInput placeholder="输入当前密码" value={oldPassword} onChange={setOldPassword} />
            </FormGroup>
            <FormGroup label="新密码" icon={Lock}>
              <PasswordInput placeholder="至少 6 位字符" value={newPassword} onChange={setNewPassword} />
            </FormGroup>
          </div>
          <div className="md:w-1/2">
            <FormGroup label="确认新密码" icon={Lock} error={passwordError}>
              <PasswordInput placeholder="再次输入新密码" value={confirmPassword} onChange={setConfirmPassword} />
            </FormGroup>
          </div>
          <div className="flex justify-end">
            <Button onClick={handleSavePassword} className="btn-primary-gradient rounded-xl px-6">
              <Save className="size-4 mr-2" />
              更新密码
            </Button>
          </div>
        </div>
      </section>

      {/* 危险区域 */}
      <section className="bg-white rounded-2xl border border-red-100 shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden mb-8">
        <div className="px-6 py-4 border-b border-red-50 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-red-50 text-red-600 flex items-center justify-center">
            <AlertCircle className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#292524]">危险操作</h3>
            <p className="text-xs text-[#a8a29e]">以下操作不可撤销，请谨慎</p>
          </div>
        </div>
        <div className="p-6 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-[#44403c]">清除所有对话记录</p>
            <p className="text-xs text-[#a8a29e] mt-0.5">此操作将删除你的所有历史对话，但保留文档数据</p>
          </div>
          <Button
            variant="outline"
            className="rounded-xl border-red-200 text-red-600 hover:bg-red-50 hover:border-red-300 hover:text-red-700"
          >
            清除记录
          </Button>
        </div>
      </section>
    </div>
  )
}
