"""User management API endpoints — 增加用户级 LLM 配置管理。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.schemas import (
    UserUpdateRequest,
    PasswordChangeRequest,
    UserInfoResponse,
    BaseResponse,
    LLMConfig,
    LLMConfigResponse,
    DefaultModelUpdate,
    UserRoleUpdate,
)
from app.db.models import User
from app.db.base import AsyncSessionLocal
from app.db.repository import user_repo, user_role_repo
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
    """获取当前用户的对话模型绑定：model_id 或 'system'（跟随系统默认对话模型）。"""
    return BaseResponse(
        data={
            "provider": current_user.default_model_id or "system",
        }
    )


@router.put("/me/default-model", response_model=BaseResponse)
async def update_default_model(
    request: DefaultModelUpdate,
    current_user: User = Depends(get_current_user),
):
    """设置当前用户的对话模型：'system'=跟随系统默认对话模型，uuid=provider_models.id
    （仅系统或本人私有的 text/multi_modal 模型）。"""
    if request.provider == "system":
        current_user.default_model_id = None
    else:
        from app.services.system_model_service import system_model_service

        cfg = await system_model_service.resolve_model_by_id(
            request.provider, str(current_user.id)
        )
        if cfg is None:
            raise HTTPException(status_code=400, detail="模型不存在或不可用于对话")
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
