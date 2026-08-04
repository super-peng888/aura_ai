# 生产环境安全配置指南

> 本文档说明 Aura AI Enterprise 后端中用户 API Key 的加密存储方案、密钥管理流程以及前后端安全对接规范。

---

## 目录

- [1. 加密方案概述](#1-加密方案概述)
- [2. 首次部署：生成与配置密钥](#2-首次部署生成与配置密钥)
- [3. 加密与解密流程](#3-加密与解密流程)
- [4. 环境变量配置](#4-环境变量配置)
- [5. 前后端对接规范](#5-前后端对接规范)
  - [5.1 后端 API 接口](#51-后端-api-接口)
  - [5.2 前端配置页面示例](#52-前端配置页面示例)
  - [5.3 完整数据流](#53-完整数据流)
- [6. 密钥轮换与灾难恢复](#6-密钥轮换与灾难恢复)
- [7. 安全自检清单](#7-安全自检清单)
- [8. 常见问题](#8-常见问题)

---

## 1. 加密方案概述

| 项目 | 说明 |
|------|------|
| **加密算法** | Fernet（AES-128-CBC + HMAC-SHA256） |
| **密钥长度** | 32-byte base64 编码字符串 |
| **密钥存储** | 环境变量 `API_KEY_ENCRYPTION_KEY`（仅后端持有，永不暴露给前端） |
| **密文存储** | PostgreSQL `users.llm_config -> api_key` |
| **回退策略** | 若未配置密钥，明文透传（仅开发环境，生产环境必须配置） |

### 为什么选 Fernet

- **标准化**：Python `cryptography` 库原生支持，无需额外依赖
- **安全**：AES-128-CBC 加密 + HMAC-SHA256 认证，防篡改
- **易用**：单次函数调用完成加密/解密，适合 Key-Value 场景
- **可控**：对称加密，后端独占密钥，密钥泄露风险集中在一处

---

## 2. 首次部署：生成与配置密钥

### 2.1 生成密钥

进入项目目录并激活虚拟环境：

```bash
cd aura-ai-enterprise/backend
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate
```

执行以下命令生成随机密钥：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

输出示例（每次运行结果不同）：

```
c1XmXgMS6xyXs3j2_g_z0kIDbQq4g9JHjBVL8lJHuwY=
```

### 2.2 配置密钥

将生成的密钥写入 `.env` 文件：

```bash
# .env
API_KEY_ENCRYPTION_KEY=c1XmXgMS6xyXs3j2_g_z0kIDbQq4g9JHjBVL8lJHuwY=
```

> ⚠️ **安全警告**
> - 此密钥是解密**所有用户 API Key** 的唯一凭证，**丢失后无法恢复**
> - 不要提交到 Git，确保 `.env` 已在 `.gitignore` 中
> - 生产环境建议将密钥托管到专业密码管理器（HashiCorp Vault、AWS Secrets Manager、阿里云 KMS）

---

## 3. 加密与解密流程

### 3.1 代码实现

核心函数位于 `app/services/llm_service.py`：

```python
def encrypt_api_key(plain_text: str) -> str:
    """使用 Fernet 对称加密 API Key。"""
    if not plain_text:
        return plain_text
    fernet = settings.get_fernet()
    if fernet is None:
        return plain_text  # 未配置密钥时明文透传（开发环境）
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt_api_key(cipher_text: str) -> str:
    """使用 Fernet 对称解密 API Key。"""
    if not cipher_text:
        return cipher_text
    fernet = settings.get_fernet()
    if fernet is None:
        return cipher_text
    try:
        return fernet.decrypt(cipher_text.encode()).decode()
    except Exception:
        # 解密失败可能是明文存储的旧数据，兼容回退
        return cipher_text
```

### 3.2 流程验证

```bash
source .venv/Scripts/activate
python -c "
from app.services.llm_service import encrypt_api_key, decrypt_api_key

plain = 'sk-test123456789'
cipher = encrypt_api_key(plain)
decrypted = decrypt_api_key(cipher)

print('明文:', plain)
print('密文:', cipher)
print('解密:', decrypted)
print('验证通过:', plain == decrypted)
"
```

预期输出：

```
明文: sk-test123456789
密文: gAAAAAB...
解密: sk-test123456789
验证通过: True
```

---

## 4. 环境变量配置

完整的生产环境 `.env` 示例：

```bash
# ============================================
# App
# ============================================
APP_NAME="Aura AI Enterprise"
DEBUG=false

# ============================================
# Database
# ============================================
PG_HOST=localhost
PG_PORT=5432
PG_USER=aura
PG_PASSWORD=your-db-password
PG_DATABASE=aura_ai

# ============================================
# LLM（系统默认配置，用户未配置时回退到此）
# ============================================
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-system-default-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_CHAT_MODEL=gpt-4o

# ============================================
# API Key Encryption（必须配置）
# ============================================
API_KEY_ENCRYPTION_KEY=c1XmXgMS6xyXs3j2_g_z0kIDbQq4g9JHjBVL8lJHuwY=

# ============================================
# JWT
# ============================================
JWT_SECRET=your-jwt-secret-min-32-chars-long
JWT_EXPIRATION_HOURS=24

# ============================================
# Milvus
# ============================================
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

---

## 5. 前后端对接规范

### 5.1 后端 API 接口

#### 获取当前用户 LLM 配置

```http
GET /api/v1/users/me/llm-config
Authorization: Bearer <access_token>
```

**响应**：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "temperature": 0.7,
    "api_key_masked": "sk-****xxxx"
  }
}
```

> 注意：`api_key_masked` 仅用于展示，**不要**将其作为真实 Key 使用。

#### 更新 LLM 配置

```http
PUT /api/v1/users/me/llm-config
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "provider": "openai",
  "api_key": "sk-your-real-key",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "temperature": 0.7
}
```

后端处理流程：
1. 接收明文 API Key
2. 调用 `encrypt_api_key()` 生成密文
3. 将密文存入 `users.llm_config`

#### 清空 LLM 配置

```http
DELETE /api/v1/users/me/llm-config
Authorization: Bearer <access_token>
```

清空后，对话将回退到系统默认模型配置。

#### 对话接口

```http
POST /api/v1/chat
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "messages": [{"role": "user", "content": "你好"}],
  "stream": false
}
```

后端自动从 `current_user.llm_config` 读取配置并解密，使用用户的 API Key 调用模型。

---

### 5.2 前端配置页面示例

```vue
<template>
  <div class="llm-config">
    <h3>模型配置</h3>
    
    <label>Provider</label>
    <select v-model="config.provider">
      <option value="openai">OpenAI / 兼容接口</option>
    </select>
    
    <label>API Base URL</label>
    <input v-model="config.base_url" placeholder="https://api.openai.com/v1" />
    
    <label>Model</label>
    <input v-model="config.model" placeholder="gpt-4o" />
    
    <label>API Key</label>
    <input 
      v-model="config.api_key" 
      type="password" 
      placeholder="sk-..."
    />
    
    <label>Temperature: {{ config.temperature }}</label>
    <input 
      v-model.number="config.temperature" 
      type="range" 
      min="0" 
      max="2" 
      step="0.1"
    />
    
    <button @click="saveConfig">保存配置</button>
    <button @click="clearConfig" class="danger">恢复默认</button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const config = ref({
  provider: 'openai',
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4o',
  api_key: '',
  temperature: 0.7,
})

const token = localStorage.getItem('token')

async function loadConfig() {
  const res = await fetch('/api/v1/users/me/llm-config', {
    headers: { Authorization: `Bearer ${token}` }
  })
  const data = await res.json()
  if (data.code === 0) {
    // 后端只返回掩码 Key，不要覆盖用户正在输入的真实 Key
    Object.assign(config.value, {
      provider: data.data.provider,
      base_url: data.data.base_url,
      model: data.data.model,
      temperature: data.data.temperature,
    })
  }
}

async function saveConfig() {
  const res = await fetch('/api/v1/users/me/llm-config', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(config.value),
  })
  const data = await res.json()
  if (data.code === 0) {
    alert('配置已保存，将使用您的 API Key 进行对话')
    config.value.api_key = ''  // 清空输入框，避免前端留存
  }
}

async function clearConfig() {
  await fetch('/api/v1/users/me/llm-config', {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  alert('已恢复系统默认模型')
}

onMounted(loadConfig)
</script>
```

---

### 5.3 完整数据流

```
┌─────────────┐         HTTPS          ┌──────────────┐
│   前端       │  ───────────────────►  │   后端        │
│             │                        │              │
│ 1. 用户输入  │                        │ 2. JWT 认证   │
│    API Key   │                        │    current_user│
│             │                        │              │
└─────────────┘                        │ 3. 加密存储   │
                                       │    encrypt_api_key()
                                       │    → users.llm_config
                                       │              │
                                       │ 4. 对话请求   │
                                       │    _extract_user_llm_config()
                                       │    → decrypt_api_key()
                                       │    → 明文 Key
                                       │              │
                                       │ 5. 动态创建模型│
                                       │    LLMFactory.create()
                                       │    → ChatOpenAI(api_key=用户Key)
                                       │              │
                                       │ 6. 调用模型   │
                                       │    → OpenAI API
                                       └──────────────┘
```

---

## 6. 密钥轮换与灾难恢复

### 6.1 密钥轮换流程

当需要更换加密密钥时（如怀疑泄露、定期安全审计）：

```python
# scripts/rotate_encryption_key.py
"""
密钥轮换脚本：使用新密钥重新加密所有用户的 API Key。

执行步骤：
1. 设置环境变量 OLD_KEY 和 NEW_KEY
2. 运行脚本
3. 更新 .env 中的 API_KEY_ENCRYPTION_KEY 为 NEW_KEY
4. 重启服务
"""

import os
import asyncio
from cryptography.fernet import Fernet
from app.db.base import AsyncSessionLocal
from app.db.repository import user_repo
from app.db.models import User

OLD_KEY = os.environ["OLD_KEY"]
NEW_KEY = os.environ["NEW_KEY"]

old_fernet = Fernet(OLD_KEY.encode())
new_fernet = Fernet(NEW_KEY.encode())


async def rotate():
    async with AsyncSessionLocal() as session:
        users = await user_repo.list(session, limit=10000)
        for user in users:
            if not user.llm_config or not user.llm_config.get("api_key"):
                continue
            
            cipher = user.llm_config["api_key"]
            try:
                # 用旧密钥解密
                plain = old_fernet.decrypt(cipher.encode()).decode()
                # 用新密钥加密
                new_cipher = new_fernet.encrypt(plain.encode()).decode()
                user.llm_config["api_key"] = new_cipher
                await session.flush()
                print(f"Rotated key for user: {user.id}")
            except Exception as e:
                print(f"Failed for user {user.id}: {e}")
        
        await session.commit()
        print("Key rotation completed.")


if __name__ == "__main__":
    asyncio.run(rotate())
```

执行：

```bash
OLD_KEY=xxx NEW_KEY=yyy python scripts/rotate_encryption_key.py
```

### 6.2 灾难恢复

| 场景 | 恢复方案 |
|------|---------|
| 密钥丢失 | **无法恢复**。所有用户 API Key 永久丢失，需引导用户重新配置 |
| 数据库泄露 | 密文无法直接解密（没有密钥），风险可控。但仍需通知用户更换 API Key |
| 密钥泄露 | 立即执行密钥轮换，强制所有用户重新登录并建议更换 API Key |

---

## 7. 安全自检清单

部署到生产环境前，请逐项确认：

- [ ] `.env` 中已设置 `API_KEY_ENCRYPTION_KEY`（32-byte base64）
- [ ] `.env` 已加入 `.gitignore`，未提交到代码仓库
- [ ] 生产环境密钥已备份到密码管理器（Vault / KMS / Secrets Manager）
- [ ] 数据库连接使用独立账号，最小权限原则
- [ ] `users.llm_config` 字段未暴露在任何公共 API 响应中
- [ ] 前端输入框使用 `type="password"` 隐藏 API Key
- [ ] 前端仅显示掩码后的 Key（`sk-****xxxx`）
- [ ] HTTPS 已启用（TLS 1.2+）
- [ ] JWT Secret 长度 >= 32 字符，定期轮换
- [ ] 服务器日志中不打印用户 API Key（明文或密文）

---

## 8. 常见问题

### Q: 为什么不使用非对称加密（RSA）？

A: 非对称加密适合"多方互信"场景（如数字签名）。API Key 加密是"单方自治"场景——只有后端需要加解密，Fernet 对称加密性能更好、实现更简单。

### Q: 用户量很大时，密钥轮换会影响性能吗？

A: 密钥轮换是离线运维操作，通过后台脚本执行，不影响线上服务。建议在低峰期运行。

### Q: 能否为每个用户使用不同的密钥？

A: 技术上可行（为每个用户生成独立 Fernet 密钥，用主密钥加密后存储），但增加了复杂度。当前方案使用单一密钥已能满足绝大多数企业场景。

### Q: 开发环境可以不配置密钥吗？

A: 可以。未配置 `API_KEY_ENCRYPTION_KEY` 时，`encrypt_api_key()` 会明文透传，方便开发调试。但生产环境**必须**配置，否则所有用户 API Key 将以明文存储。

---

*文档版本：v1.0*  
*最后更新：2026-05-28*
