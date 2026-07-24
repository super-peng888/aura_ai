"""User management API endpoints — 增加用户级 LLM 配置管理。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from app.models.schemas import (
    UserUpdateRequest,
    PasswordChangeRequest,
    UserInfoResponse,
    BaseResponse,
    LLMConfig,
    LLMConfigResponse,
    DefaultModelUpdate,
    UserModelConfigCreate,
    UserModelConfigUpdate,
    UserModelConfigResponse,
    UserRoleUpdate,
)
from app.db.models import User
from app.db.base import AsyncSessionLocal
from app.db.repository import user_repo, user_role_repo, user_model_config_repo
from app.api.auth import get_current_user, hash_password, verify_password, require_permission
from app.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=BaseResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户基本信息。"""
    return BaseResponse(
        data=UserInfoResponse(
            id=str(current_user.id),
            username=current_user.username,
            email=current_user.email,
            phone=current_user.phone,
            avatar_url=current_user.avatar_url,
            role=current_user.role,
            token_quota_monthly=current_user.token_quota_monthly,
            token_used_monthly=current_user.token_used_monthly,
            token_reset_at=current_user.token_reset_at,
            default_model_id=current_user.default_model_id,
            created_at=current_user.created_at,
        ).model_dump()
    )


@router.put("/me", response_model=BaseResponse)
async def update_me(
    request: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """更新当前用户基本信息。"""
    update_fields = request.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    allowed = {"username", "email", "phone", "avatar_url"}
    for key, value in update_fields.items():
        if key in allowed and value is not None:
            setattr(current_user, key, value)

    async with AsyncSessionLocal() as session:
        await user_repo.create(session, current_user)
        await session.commit()

    return BaseResponse(data={"message": "Profile updated"})


@router.put("/me/password", response_model=BaseResponse)
async def change_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
):
    """修改当前用户密码。"""
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = hash_password(request.new_password)
    async with AsyncSessionLocal() as session:
        await user_repo.create(session, current_user)
        await session.commit()

    return BaseResponse(data={"message": "Password changed successfully"})


# =============================================================================
# 用户级 LLM 配置管理
# =============================================================================

@router.get("/me/llm-config", response_model=BaseResponse)
async def get_llm_config(current_user: User = Depends(get_current_user)):
    """
    获取当前用户的 LLM 配置。

    返回的数据中 api_key 会被掩码处理（如 sk-****xxxx），前端仅用于展示，
    真实的 API Key 由后端在调用模型时从数据库读取。
    """
    config = current_user.llm_config or {}
    response = LLMConfigResponse(
        provider=config.get("provider", "openai"),
        base_url=config.get("base_url", "https://api.openai.com/v1"),
        model=config.get("model", "gpt-4o"),
        temperature=config.get("temperature", 0.7),
        api_key_masked=LLMConfig(**config).mask_api_key() if config else "未配置",
    )
    return BaseResponse(data=response.model_dump())


@router.put("/me/llm-config", response_model=BaseResponse)
async def update_llm_config(
    request: LLMConfig,
    current_user: User = Depends(get_current_user),
):
    """
    更新当前用户的 LLM 配置。

    前端通过此接口保存用户自己的 API Key、模型选择等参数。
    保存时会对 API Key 进行简单加密（生产环境建议启用 Fernet 加密）。
    """
    from app.services.llm_service import encrypt_api_key

    new_config = {
        "provider": request.provider,
        "api_key": encrypt_api_key(request.api_key),
        "base_url": request.base_url,
        "model": request.model,
        "temperature": request.temperature,
    }

    current_user.llm_config = new_config
    async with AsyncSessionLocal() as session:
        await user_repo.create(session, current_user)
        await session.commit()

    return BaseResponse(
        data={
            "message": "LLM config updated",
            "provider": request.provider,
            "model": request.model,
            "api_key_masked": request.mask_api_key(),
        }
    )


@router.delete("/me/llm-config", response_model=BaseResponse)
async def clear_llm_config(current_user: User = Depends(get_current_user)):
    """清空当前用户的 LLM 配置，回退到系统默认模型。"""
    current_user.llm_config = {}
    async with AsyncSessionLocal() as session:
        await user_repo.create(session, current_user)
        await session.commit()

    return BaseResponse(data={"message": "LLM config cleared, using system default"})


# =============================================================================
# 用户默认模型绑定
# =============================================================================

@router.get("/me/default-model", response_model=BaseResponse)
async def get_default_model(current_user: User = Depends(get_current_user)):
    """获取当前用户绑定的默认模型。"""
    return BaseResponse(
        data={
            "provider": current_user.default_model_id or settings.LLM_PROVIDER,
        }
    )


@router.put("/me/default-model", response_model=BaseResponse)
async def update_default_model(
    request: DefaultModelUpdate,
    current_user: User = Depends(get_current_user),
):
    """设置当前用户的默认模型（绑定到用户）。"""
    current_user.default_model_id = request.provider
    async with AsyncSessionLocal() as session:
        await user_repo.create(session, current_user)
        await session.commit()

    # 清除 Redis 缓存，确保下次请求使用新配置
    from app.services.llm_service import UserModelConfigService
    await UserModelConfigService.invalidate_cache(str(current_user.id))

    return BaseResponse(
        data={
            "provider": request.provider,
            "message": "Default model updated",
        }
    )


# =============================================================================
# 用户自定义模型配置（支持多模型）
# =============================================================================

def _mask_key(key: Optional[str]) -> str:
    """掩码处理 API Key。"""
    if not key:
        return "未配置"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}****{key[-4:]}"


def _to_response(cfg) -> dict:
    return UserModelConfigResponse(
        id=str(cfg.id),
        model=cfg.model,
        base_url=cfg.base_url,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        timeout=cfg.timeout,
        api_key_masked=_mask_key(cfg.api_key),
        is_current=cfg.is_current,
    ).model_dump()


@router.get("/me/model-config", response_model=BaseResponse)
async def list_model_configs(current_user: User = Depends(get_current_user)):
    """获取当前用户的所有自定义模型配置列表。"""
    async with AsyncSessionLocal() as session:
        configs = await user_model_config_repo.list_by_user(session, str(current_user.id))
    return BaseResponse(data=[_to_response(c) for c in configs])


@router.post("/me/model-config", response_model=BaseResponse)
async def create_model_config(
    request: UserModelConfigCreate,
    current_user: User = Depends(get_current_user),
):
    """新增自定义模型配置。API Key 加密存储。"""
    from app.services.llm_service import encrypt_api_key, UserModelConfigService
    from app.db.models import UserModelConfig

    async with AsyncSessionLocal() as session:
        cfg = UserModelConfig(
            user_id=str(current_user.id),
            model=request.model,
            base_url=request.base_url,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            timeout=request.timeout,
        )
        if request.api_key.strip():
            cfg.api_key = encrypt_api_key(request.api_key.strip())

        await user_model_config_repo.create(session, cfg)
        await session.commit()

    await UserModelConfigService.invalidate_cache(str(current_user.id))
    return BaseResponse(data=_to_response(cfg))


@router.put("/me/model-config/{config_id}", response_model=BaseResponse)
async def update_model_config(
    config_id: str,
    request: UserModelConfigUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新指定自定义模型配置。API Key 加密存储。"""
    from app.services.llm_service import encrypt_api_key, UserModelConfigService

    async with AsyncSessionLocal() as session:
        cfg = await user_model_config_repo.get(session, config_id)
        if not cfg or str(cfg.user_id) != str(current_user.id):
            raise HTTPException(status_code=404, detail="Model config not found")

        cfg.model = request.model
        cfg.base_url = request.base_url
        cfg.max_tokens = request.max_tokens
        cfg.temperature = request.temperature
        cfg.top_p = request.top_p
        cfg.timeout = request.timeout
        if request.api_key.strip():
            cfg.api_key = encrypt_api_key(request.api_key.strip())

        await user_model_config_repo.create(session, cfg)
        await session.commit()

    await UserModelConfigService.invalidate_cache(str(current_user.id))
    return BaseResponse(data=_to_response(cfg))


@router.delete("/me/model-config/{config_id}", response_model=BaseResponse)
async def delete_model_config(
    config_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除指定自定义模型配置。如果删除的是当前默认，自动切回系统内置。"""
    from app.services.llm_service import UserModelConfigService

    async with AsyncSessionLocal() as session:
        cfg = await user_model_config_repo.get(session, config_id)
        if not cfg or str(cfg.user_id) != str(current_user.id):
            raise HTTPException(status_code=404, detail="Model config not found")

        was_current = cfg.is_current
        await user_model_config_repo.delete(session, cfg)

        if was_current:
            current_user.default_model_id = "deepseek"
            await user_repo.create(session, current_user)

        await session.commit()

    await UserModelConfigService.invalidate_cache(str(current_user.id))
    return BaseResponse(data={"message": "Model config deleted"})


@router.post("/me/model-config/{config_id}/set-default", response_model=BaseResponse)
async def set_default_model_config(
    config_id: str,
    current_user: User = Depends(get_current_user),
):
    """将指定自定义模型设为当前默认。同时更新 users.default_model_id 为 'custom'。"""
    from app.services.llm_service import UserModelConfigService

    async with AsyncSessionLocal() as session:
        cfg = await user_model_config_repo.get(session, config_id)
        if not cfg or str(cfg.user_id) != str(current_user.id):
            raise HTTPException(status_code=404, detail="Model config not found")

        # 清除该用户所有自定义模型的 is_current
        await user_model_config_repo.clear_current_by_user(session, str(current_user.id))
        # 设置当前为默认
        cfg.is_current = True
        await session.flush()

        # 更新用户默认模型为 custom
        current_user.default_model_id = "custom"
        await user_repo.create(session, current_user)
        await session.commit()

    await UserModelConfigService.invalidate_cache(str(current_user.id))
    return BaseResponse(data=_to_response(cfg))


# =============================================================================
# 管理员接口
# =============================================================================

@router.get("", response_model=BaseResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission("user:manage")),
):
    """管理员获取用户列表。"""
    async with AsyncSessionLocal() as session:
        offset = (page - 1) * page_size
        users = await user_repo.list(session, limit=page_size, offset=offset)
        total = await user_repo.count(session)

        data = [
            UserInfoResponse(
                id=str(u.id),
                username=u.username,
                email=u.email,
                phone=u.phone,
                avatar_url=u.avatar_url,
                role=u.role,
                token_quota_monthly=u.token_quota_monthly,
                token_used_monthly=u.token_used_monthly,
                token_reset_at=u.token_reset_at,
                default_model_id=u.default_model_id,
                created_at=u.created_at,
            ).model_dump()
            for u in users
        ]

    return BaseResponse(data={"items": data, "total": total, "page": page, "page_size": page_size})


# =============================================================================
# 管理员接口
# =============================================================================

@router.put("/{user_id}/role", response_model=BaseResponse)
async def update_user_role(
    user_id: str,
    request: UserRoleUpdate,
    current_user: User = Depends(get_current_user),
):
    """管理员修改用户角色。同时更新 users.role 字符串和 user_roles 关联表。"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    async with AsyncSessionLocal() as session:
        target = await user_repo.get(session, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        target.role = request.role
        await user_role_repo.sync_user_role(session, user_id, request.role)
        await session.commit()

    return BaseResponse(data={"message": "Role updated"})
