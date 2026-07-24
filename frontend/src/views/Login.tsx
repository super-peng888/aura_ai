import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import {
  User,
  Lock,
  Mail,
  Phone,
  ArrowRight,
  Zap,
  BookOpen,
  Brain,
  ShieldCheck,
  Eye,
  EyeOff,
} from "lucide-react"

export default function Login() {
  const navigate = useNavigate()
  const { login, register } = useAuth()
  const [isRegister, setIsRegister] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showPwd, setShowPwd] = useState(false)
  const [showConfirmPwd, setShowConfirmPwd] = useState(false)

  const [form, setForm] = useState({
    username: "",
    password: "",
    email: "",
    phone: "",
    confirmPassword: "",
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (isSubmitting) return

    if (!form.username.trim() || !form.password.trim()) {
      toast.error("请填写用户名和密码")
      return
    }

    setIsSubmitting(true)
    try {
      if (isRegister) {
        if (form.password !== form.confirmPassword) {
          toast.error("两次输入的密码不一致")
          return
        }
        if (form.password.length < 6) {
          toast.error("密码至少 6 位")
          return
        }
        await register({
          username: form.username,
          password: form.password,
          email: form.email || undefined,
          phone: form.phone || undefined,
        })
        setIsRegister(false)
        setForm((prev) => ({ ...prev, password: "", confirmPassword: "" }))
      } else {
        await login(form.username, form.password)
        navigate("/", { replace: true })
      }
    } catch {
      // 错误已在 api client 中 toast
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* 左侧品牌区 */}
      <div
        className="hidden lg:flex lg:w-[45%] xl:w-[42%] relative overflow-hidden"
        style={{
          background: "linear-gradient(160deg, #1e3a8a 0%, #1e40af 35%, #2563eb 70%, #3b82f6 100%)",
        }}
      >
        {/* 装饰圆 */}
        <div
          className="absolute -top-40 -left-40 w-96 h-96 rounded-full bg-white/[0.05]"
          style={{ animation: "float 6s ease-in-out infinite" }}
        />
        <div
          className="absolute top-1/3 -right-20 w-72 h-72 rounded-full bg-white/[0.05]"
          style={{ animation: "float 6s ease-in-out infinite 1.5s" }}
        />
        <div
          className="absolute -bottom-32 left-1/4 w-80 h-80 rounded-full bg-white/[0.05]"
          style={{ animation: "float 6s ease-in-out infinite 3s" }}
        />

        <div className="relative z-10 flex flex-col justify-between p-12 xl:p-16 text-white">
          <div>
            <div className="flex items-center gap-3 mb-12">
              <div className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center backdrop-blur-sm border border-white/10">
                <Zap className="size-5" />
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight leading-none">Aura AI</h1>
                <p className="text-[11px] text-white/50 mt-0.5 tracking-widest uppercase">Enterprise</p>
              </div>
            </div>

            <h2 className="text-3xl xl:text-4xl font-bold leading-tight mb-6">
              企业级智能
              <br />
              知识管理平台
            </h2>
            <p className="text-white/60 text-base leading-relaxed max-w-sm">
              基于 RAG 技术的文档智能解析与对话系统，让每一份文档都能被深度理解、随时问答。
            </p>
          </div>

          <div className="space-y-5">
            <div className="rounded-2xl p-5 flex items-start gap-4 bg-white/[0.08] backdrop-blur-md border border-white/10">
              <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center flex-shrink-0">
                <BookOpen className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold mb-1">文档智能解析</p>
                <p className="text-xs text-white/50 leading-relaxed">支持 PDF、Word、Excel 等格式，自动提取文本、图片与表格</p>
              </div>
            </div>
            <div className="rounded-2xl p-5 flex items-start gap-4 bg-white/[0.08] backdrop-blur-md border border-white/10">
              <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center flex-shrink-0">
                <Brain className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold mb-1">多路召回 RAG</p>
                <p className="text-xs text-white/50 leading-relaxed">向量检索 + 关键词检索 + 重排序，精准定位答案来源</p>
              </div>
            </div>
            <div className="rounded-2xl p-5 flex items-start gap-4 bg-white/[0.08] backdrop-blur-md border border-white/10">
              <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center flex-shrink-0">
                <ShieldCheck className="size-4" />
              </div>
              <div>
                <p className="text-sm font-semibold mb-1">企业级安全</p>
                <p className="text-xs text-white/50 leading-relaxed">API Key 加密存储、JWT 认证、细粒度权限控制</p>
              </div>
            </div>
          </div>
        </div>

        <style>{`
          @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-12px); }
          }
        `}</style>
      </div>

      {/* 右侧表单区 */}
      <div className="flex-1 flex items-center justify-center p-6 lg:p-12 bg-background">
        <div className="w-full max-w-[420px]">
          {/* 移动端 Logo */}
          <div className="lg:hidden flex items-center gap-3 mb-10">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary to-[#1e40af] flex items-center justify-center shadow-[0_0_20px_rgba(37,99,235,0.15)]">
              <Zap className="size-4 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold text-[#292524] tracking-tight leading-none">Aura AI</h1>
              <p className="text-[11px] text-[#a8a29e] mt-0.5 tracking-wide uppercase">Enterprise</p>
            </div>
          </div>

          {/* Tab 切换 */}
          <div className="bg-[#f5f5f4] rounded-2xl p-1 flex mb-8">
            <button
              onClick={() => {
                setIsRegister(false)
                setForm({ username: "", password: "", email: "", phone: "", confirmPassword: "" })
              }}
              className={cn(
                "flex-1 py-2.5 rounded-xl text-sm font-medium transition-all",
                !isRegister ? "bg-white text-[#292524] shadow-[0_1px_3px_rgba(0,0,0,0.04)]" : "text-[#78716c] hover:text-[#57534e]"
              )}
            >
              登录
            </button>
            <button
              onClick={() => {
                setIsRegister(true)
                setForm({ username: "", password: "", email: "", phone: "", confirmPassword: "" })
              }}
              className={cn(
                "flex-1 py-2.5 rounded-xl text-sm font-medium transition-all",
                isRegister ? "bg-white text-[#292524] shadow-[0_1px_3px_rgba(0,0,0,0.04)]" : "text-[#78716c] hover:text-[#57534e]"
              )}
            >
              注册账号
            </button>
          </div>

          <div className="space-y-5">
            <div>
              <h2 className="text-2xl font-bold text-[#292524] mb-1">
                {isRegister ? "创建账号" : "欢迎回来"}
              </h2>
              <p className="text-sm text-[#a8a29e]">
                {isRegister ? "填写以下信息开始使用 Aura AI" : "请输入你的账号信息以继续"}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Username */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[#78716c]">用户名</label>
                <div className="relative">
                  <User className="absolute left-4 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
                  <input
                    name="username"
                    type="text"
                    placeholder="请输入用户名"
                    value={form.username}
                    onChange={handleChange}
                    className="w-full pl-11 pr-4 py-3 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                  />
                </div>
              </div>

              {isRegister && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-[#78716c]">邮箱地址</label>
                    <div className="relative">
                      <Mail className="absolute left-4 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
                      <input
                        name="email"
                        type="email"
                        placeholder="name@company.com"
                        value={form.email}
                        onChange={handleChange}
                        className="w-full pl-11 pr-4 py-3 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-[#78716c]">手机号</label>
                    <div className="relative">
                      <Phone className="absolute left-4 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
                      <input
                        name="phone"
                        type="tel"
                        placeholder="选填"
                        value={form.phone}
                        onChange={handleChange}
                        className="w-full pl-11 pr-4 py-3 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                      />
                    </div>
                  </div>
                </>
              )}

              {/* Password */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[#78716c]">密码</label>
                <div className="relative">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
                  <input
                    name="password"
                    type={showPwd ? "text" : "password"}
                    placeholder={isRegister ? "至少 6 位字符" : "请输入密码"}
                    value={form.password}
                    onChange={handleChange}
                    className="w-full pl-11 pr-11 py-3 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPwd(!showPwd)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-[#a8a29e] hover:text-[#57534e] transition-colors"
                  >
                    {showPwd ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </div>

              {isRegister && (
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-[#78716c]">确认密码</label>
                  <div className="relative">
                    <Lock className="absolute left-4 top-1/2 -translate-y-1/2 size-4 text-[#a8a29e]" />
                    <input
                      name="confirmPassword"
                      type={showConfirmPwd ? "text" : "password"}
                      placeholder="再次输入密码"
                      value={form.confirmPassword}
                      onChange={handleChange}
                      className="w-full pl-11 pr-11 py-3 rounded-xl bg-white border border-[#e7e5e4] text-sm text-[#44403c] placeholder:text-[#a8a29e] outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirmPwd(!showConfirmPwd)}
                      className="absolute right-4 top-1/2 -translate-y-1/2 text-[#a8a29e] hover:text-[#57534e] transition-colors"
                    >
                      {showConfirmPwd ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                </div>
              )}

              {!isRegister && (
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" className="w-4 h-4 rounded border-[#d6d3d1] text-primary focus:ring-primary/20" />
                    <span className="text-xs text-[#78716c]">记住我</span>
                  </label>
                  <button type="button" className="text-xs text-primary hover:text-[#1e40af] font-medium transition-colors">
                    忘记密码？
                  </button>
                </div>
              )}

              {isRegister && (
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" className="w-4 h-4 mt-0.5 rounded border-[#d6d3d1] text-primary focus:ring-primary/20" />
                  <span className="text-xs text-[#78716c] leading-relaxed">
                    我已阅读并同意 <a href="#" className="text-primary hover:underline">服务条款</a> 和{" "}
                    <a href="#" className="text-primary hover:underline">隐私政策</a>
                  </span>
                </label>
              )}

              <button
                type="submit"
                disabled={isSubmitting}
                className={cn(
                  "w-full py-3 rounded-xl text-white text-sm font-semibold transition-all shadow-[0_0_20px_rgba(37,99,235,0.15)] active:scale-[0.98]",
                  "bg-gradient-to-r from-primary to-[#3b82f6] hover:shadow-[0_0_28px_rgba(37,99,235,0.25)]",
                  isSubmitting && "opacity-70 cursor-not-allowed"
                )}
              >
                {isSubmitting ? (
                  <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <span className="flex items-center justify-center gap-2">
                    {isRegister ? "创建账号" : "登录"}
                    <ArrowRight className="size-4" />
                  </span>
                )}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}
