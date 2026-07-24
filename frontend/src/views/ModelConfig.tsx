import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"

import { api } from "@/api/client"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import PageHeader from "@/components/layout/PageHeader"
import {
  Plus,
  Trash2,
  Pencil,
  Star,
  CheckCircle,
  Bot,
  Zap,
  Server,
  Key,
  Check,
  Eye,
  EyeOff,
} from "lucide-react"

interface CustomModelConfig {
  id: string
  model: string
  base_url: string
  max_tokens: number
  temperature: number
  top_p: number
  timeout: number
  api_key_masked: string
  is_current: boolean
}

function PasswordInput({ placeholder, value, onChange, disabled }: { placeholder: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
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
// Main Page
// ============================================================================

export default function ModelConfig() {
  const [defaultProvider, setDefaultProvider] = useState<string>("deepseek")
  const [customConfigs, setCustomConfigs] = useState<CustomModelConfig[]>([])
  const [formConfig, setFormConfig] = useState({
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o",
    max_tokens: 4096,
    temperature: 0.7,
    top_p: 0.9,
    timeout: 60,
  })
  const [apiKey, setApiKey] = useState("")
  const [showCustomDialog, setShowCustomDialog] = useState(false)
  const [editingConfigId, setEditingConfigId] = useState<string | null>(null)
  const [isSavingDefault, setIsSavingDefault] = useState(false)
  const [isSavingCustom, setIsSavingCustom] = useState(false)
  const [isModelLoading, setIsModelLoading] = useState(true)

  const loadModelConfig = async () => {
    setIsModelLoading(true)
    try {
      const [defaultRes, customRes] = await Promise.allSettled([
        api.get<{ provider: string }>("/users/me/default-model"),
        api.get<CustomModelConfig[]>("/users/me/model-config"),
      ])
      if (defaultRes.status === "fulfilled" && defaultRes.value) {
        setDefaultProvider(defaultRes.value.provider || "deepseek")
      }
      if (customRes.status === "fulfilled" && customRes.value) {
        setCustomConfigs(customRes.value || [])
      } else {
        setCustomConfigs([])
      }
    } catch {
      // ignore
    } finally {
      setIsModelLoading(false)
    }
  }

  const handleSetDefaultModel = async (provider: string, configId?: string) => {
    setIsSavingDefault(true)
    try {
      if (provider === "deepseek") {
        await api.put("/users/me/default-model", { provider: "deepseek" })
        setDefaultProvider("deepseek")
        toast.success("已切换为系统默认模型")
      } else if (configId) {
        await api.post(`/users/me/model-config/${configId}/set-default`)
        setDefaultProvider("custom")
        toast.success("已设为自定义模型")
      }
      loadModelConfig()
    } catch {
      // error toast by api client
    } finally {
      setIsSavingDefault(false)
    }
  }

  const openCreateModel = () => {
    setEditingConfigId(null)
    setFormConfig({
      base_url: "https://api.openai.com/v1",
      model: "gpt-4o",
      max_tokens: 4096,
      temperature: 0.7,
      top_p: 0.9,
      timeout: 60,
    })
    setApiKey("")
    setShowCustomDialog(true)
  }

  const openEditModel = (cfg: CustomModelConfig) => {
    setEditingConfigId(cfg.id)
    setFormConfig({
      base_url: cfg.base_url,
      model: cfg.model,
      max_tokens: cfg.max_tokens,
      temperature: cfg.temperature,
      top_p: cfg.top_p,
      timeout: cfg.timeout,
    })
    setApiKey("")
    setShowCustomDialog(true)
  }

  const handleSaveCustomConfig = async () => {
    setIsSavingCustom(true)
    try {
      const payload = {
        base_url: formConfig.base_url,
        model: formConfig.model,
        max_tokens: formConfig.max_tokens,
        temperature: formConfig.temperature,
        top_p: formConfig.top_p,
        timeout: formConfig.timeout,
        api_key: apiKey.trim() || undefined,
      }
      if (editingConfigId) {
        await api.put(`/users/me/model-config/${editingConfigId}`, payload)
        toast.success("自定义模型已更新")
      } else {
        await api.post("/users/me/model-config", payload)
        toast.success("自定义模型已保存")
      }
      setShowCustomDialog(false)
      setApiKey("")
      loadModelConfig()
    } catch {
      // error toast by api client
    } finally {
      setIsSavingCustom(false)
    }
  }

  const handleDeleteCustomConfig = async (id: string) => {
    if (!confirm("确定要删除该自定义模型配置吗？")) return
    try {
      await api.delete(`/users/me/model-config/${id}`)
      // 如果删除的是当前默认，defaultProvider 会被后端重置为 deepseek
      if (defaultProvider === "custom") {
        setDefaultProvider("deepseek")
      }
      toast.success("自定义模型已删除")
      loadModelConfig()
    } catch {
      // error toast by api client
    }
  }

  useEffect(() => {
    loadModelConfig()
  }, [])

  // defaultProvider 有效取值为 "deepseek" | "custom"；历史脏数据（qwen/glm 等）
  // 后端按 deepseek 处理，这里统一宽容显示为系统默认选中
  const isSystemDefault = defaultProvider !== "custom"

  return (
    <div className="space-y-6">
      <PageHeader />

      {/* ===================== 模型配置 Section ===================== */}
      <section className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
        <div className="px-6 py-4 border-b border-[#f5f5f4] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center">
              <Bot className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#292524]">模型配置</h3>
              <p className="text-xs text-[#a8a29e]">系统内置模型开箱即用，也可配置自定义模型</p>
            </div>
          </div>
          <Button
            onClick={openCreateModel}
            className="btn-primary-gradient rounded-xl px-4 flex items-center gap-2 text-xs"
          >
            <Plus className="size-3.5" />
            添加自定义模型
          </Button>
        </div>

        {isModelLoading ? (
          <div className="p-6 flex items-center justify-center">
            <div className="size-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          </div>
        ) : (
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {/* 系统默认模型卡片 */}
              <div
                className={cn(
                  "bg-white rounded-2xl border p-5 transition-all hover-lift",
                  isSystemDefault
                    ? "border-primary ring-2 ring-primary/10"
                    : "border-[#e7e5e4]"
                )}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-emerald-100 flex items-center justify-center">
                      <Zap className="size-5 text-emerald-600" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-[#292524]">DeepSeek</h3>
                      <p className="text-[10px] text-[#a8a29e]">系统内置 · 无需配置</p>
                    </div>
                  </div>
                  {isSystemDefault && (
                    <span className="px-2 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-medium border border-primary/20 flex items-center gap-1">
                      <Star className="size-3" />
                      默认
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1.5 mb-4 text-[10px] text-[#78716c]">
                  <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600 border border-emerald-100">
                    系统内置
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-[#f5f5f4] border border-[#e7e5e4] font-mono">
                    deepseek-v4-flash
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {!isSystemDefault && (
                    <button
                      onClick={() => handleSetDefaultModel("deepseek")}
                      disabled={isSavingDefault}
                      className="flex-1 h-8 rounded-lg text-xs font-medium text-primary border border-primary/20 hover:bg-primary/5 transition-all flex items-center justify-center gap-1"
                    >
                      <CheckCircle className="size-3.5" />
                      设为默认
                    </button>
                  )}
                </div>
              </div>

              {/* 自定义模型卡片列表 */}
              {customConfigs.map((cfg) => (
                <div
                  key={cfg.id}
                  className={cn(
                    "bg-white rounded-2xl border p-5 transition-all hover-lift",
                    defaultProvider === "custom" && cfg.is_current
                      ? "border-primary ring-2 ring-primary/10"
                      : "border-[#e7e5e4]"
                  )}
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                        <Server className="size-5 text-primary" />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-[#292524]">{cfg.model}</h3>
                        <p className="text-[10px] text-[#a8a29e] font-mono truncate max-w-[160px]">
                          {cfg.base_url}
                        </p>
                      </div>
                    </div>
                    {defaultProvider === "custom" && cfg.is_current && (
                      <span className="px-2 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-medium border border-primary/20 flex items-center gap-1">
                        <Star className="size-3" />
                        默认
                      </span>
                    )}
                  </div>

                  <div className="grid grid-cols-3 gap-2 mb-4">
                    <div className="p-2 rounded-lg bg-[#fafaf9] border border-[#e7e5e4] text-center">
                      <p className="text-[10px] text-[#a8a29e]">Temperature</p>
                      <p className="text-xs font-semibold text-[#44403c]">{cfg.temperature}</p>
                    </div>
                    <div className="p-2 rounded-lg bg-[#fafaf9] border border-[#e7e5e4] text-center">
                      <p className="text-[10px] text-[#a8a29e]">Max Tokens</p>
                      <p className="text-xs font-semibold text-[#44403c]">{cfg.max_tokens}</p>
                    </div>
                    <div className="p-2 rounded-lg bg-[#fafaf9] border border-[#e7e5e4] text-center">
                      <p className="text-[10px] text-[#a8a29e]">Timeout</p>
                      <p className="text-xs font-semibold text-[#44403c]">{cfg.timeout}s</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5 mb-4 text-[10px] text-[#78716c]">
                    <span className="px-1.5 py-0.5 rounded bg-purple-50 text-purple-600 border border-purple-100">
                      自定义
                    </span>
                    <span className="px-1.5 py-0.5 rounded bg-[#f5f5f4] border border-[#e7e5e4]">
                      API Key: {cfg.api_key_masked}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {!(defaultProvider === "custom" && cfg.is_current) && (
                      <button
                        onClick={() => handleSetDefaultModel("custom", cfg.id)}
                        disabled={isSavingDefault}
                        className="flex-1 h-8 rounded-lg text-xs font-medium text-primary border border-primary/20 hover:bg-primary/5 transition-all flex items-center justify-center gap-1"
                      >
                        <CheckCircle className="size-3.5" />
                        设为默认
                      </button>
                    )}
                    <button
                      onClick={() => openEditModel(cfg)}
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-[#78716c] hover:bg-[#f5f5f4] transition-all"
                      title="编辑"
                    >
                      <Pencil className="size-3.5" />
                    </button>
                    <button
                      onClick={() => handleDeleteCustomConfig(cfg.id)}
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-[#a8a29e] hover:bg-red-50 hover:text-red-500 transition-all"
                      title="删除"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                </div>
              ))}


            </div>
          </div>
        )}
      </section>

      {/* 自定义模型配置弹窗 */}
      <Dialog open={showCustomDialog} onOpenChange={setShowCustomDialog}>
        <DialogContent className="bg-white rounded-2xl border border-[#e7e5e4] shadow-[0_10px_15px_-3px_rgba(0,0,0,0.04)] max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-[#292524]">
              <Server className="size-5 text-primary" />
              {editingConfigId ? "编辑自定义模型" : "添加自定义模型"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-[#78716c]">模型名称</Label>
              <Input
                value={formConfig.model}
                onChange={(e) => setFormConfig((prev) => ({ ...prev, model: e.target.value }))}
                placeholder="例如：gpt-4o、deepseek-chat、glm-4"
                className="py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm font-mono text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5 text-xs font-medium text-[#78716c]">
                <Server className="size-3.5 text-[#a8a29e]" />
                Base URL
              </Label>
              <Input
                value={formConfig.base_url}
                onChange={(e) => setFormConfig((prev) => ({ ...prev, base_url: e.target.value }))}
                placeholder="https://api.example.com/v1"
                className="py-2.5 rounded-xl bg-[#fafaf9] border-[#e7e5e4] text-sm font-mono text-[#44403c] focus:border-primary focus:ring-4 focus:ring-primary/10 focus:bg-white transition-all"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5 text-xs font-medium text-[#78716c]">
                <Key className="size-3.5 text-[#a8a29e]" />
                API Key
              </Label>
              <PasswordInput
                placeholder={editingConfigId ? "留空则保持不变" : "请输入 API Key"}
                value={apiKey}
                onChange={setApiKey}
              />
              <p className="text-[11px] text-[#a8a29e]">留空将保持当前配置。你的 Key 将被加密存储。</p>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-[#78716c]">Temperature</Label>
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={formConfig.temperature}
                  onChange={(e) => setFormConfig((prev) => ({ ...prev, temperature: parseFloat(e.target.value) }))}
                  className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-[#78716c]">Max Tokens</Label>
                <Input
                  type="number"
                  min="1"
                  max="128000"
                  value={formConfig.max_tokens}
                  onChange={(e) => setFormConfig((prev) => ({ ...prev, max_tokens: parseInt(e.target.value) }))}
                  className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-[#78716c]">Top P</Label>
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={formConfig.top_p}
                  onChange={(e) => setFormConfig((prev) => ({ ...prev, top_p: parseFloat(e.target.value) }))}
                  className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs font-medium text-[#78716c]">Timeout (s)</Label>
                <Input
                  type="number"
                  min="1"
                  max="300"
                  value={formConfig.timeout}
                  onChange={(e) => setFormConfig((prev) => ({ ...prev, timeout: parseInt(e.target.value) }))}
                  className="py-2 rounded-lg bg-[#fafaf9] border-[#e7e5e4] text-sm text-[#44403c] focus:bg-white"
                />
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2">
            {editingConfigId && (
              <Button
                variant="outline"
                onClick={() => {
                  setShowCustomDialog(false)
                  handleDeleteCustomConfig(editingConfigId)
                }}
                className="rounded-xl border-[#e7e5e4] text-destructive hover:bg-red-50 hover:text-destructive"
              >
                <Trash2 className="size-4 mr-2" />
                删除
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => setShowCustomDialog(false)}
              className="rounded-xl border-[#e7e5e4] text-[#57534e] hover:bg-[#f5f5f4]"
            >
              取消
            </Button>
            <Button
              onClick={handleSaveCustomConfig}
              disabled={isSavingCustom}
              className="btn-primary-gradient rounded-xl"
            >
              {isSavingCustom ? (
                <span className="inline-block size-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Check className="size-4 mr-2" />
              )}
              保存并使用
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
