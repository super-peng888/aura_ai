"""Authentication API endpoints (register, login, JWT)."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.models.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    UserInfoResponse,
    BaseResponse,
    PermissionResponse,
)
from app.db.base import AsyncSessionLocal
from app.db.repository import user_repo, role_repo, permission_repo
from app.db.models import User
from app.utils.request_context import set_current_user_id
from app.utils.tree import build_tree, tree_to_dict

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Auth"])

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(user_id: str, username: str, role: str = "user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    async with AsyncSessionLocal() as session:
        user = await user_repo.get(session, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # 将用户 ID 注入请求状态，供审计中间件使用
    request.state.user_id = str(user.id)

    # 写入请求上下文（contextvars），供下游 LLM 配置解析等读取。
    # FastAPI 每个请求在独立 task/context 中运行，整条 await 链可见，无需 reset。
    set_current_user_id(str(user.id))

    return user


async def _get_user_permissions(user: User) -> set[str]:
    """获取用户的所有权限编码集合（优先使用 user_roles 关联表，同时兼容 user.role 字符串）。"""
    async with AsyncSessionLocal() as session:
        # 1. 通过 user_roles 多对多表查询
        perms = await permission_repo.get_by_user(session, str(user.id))
        perm_codes = {p.code for p in perms}

        # 2. 兼容旧逻辑：同时检查 user.role 字符串对应的角色权限
        role = await role_repo.get_by_name(session, user.role)
        if role:
            role_perms = await permission_repo.get_by_role(session, str(role.id))
            perm_codes |= {p.code for p in role_perms}

    return perm_codes


def require_permission(permission_code: str):
    """返回一个 FastAPI dependency，校验当前用户是否拥有指定权限。"""
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        # admin 角色拥有全部权限
        if current_user.role == "admin":
            return current_user

        perm_codes = await _get_user_permissions(current_user)
        if permission_code not in perm_codes:
            raise HTTPException(status_code=403, detail=f"Permission denied: {permission_code}")

        return current_user
    return checker


@router.post("/register", response_model=BaseResponse)
async def register(request: UserRegisterRequest):
    async with AsyncSessionLocal() as session:
        existing = await user_repo.get_by_username(session, request.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")

        password_hash = hash_password(request.password)
        user = User(
            username=request.username,
            password_hash=password_hash,
            email=request.email,
            phone=request.phone,
        )
        await user_repo.create(session, user)
        await session.commit()

    return BaseResponse(data={"user_id": user.id, "username": user.username})


@router.post("/login", response_model=BaseResponse)
async def login(request: UserLoginRequest):
    async with AsyncSessionLocal() as session:
        user = await user_repo.get_by_username(session, request.username)

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is inactive or banned")

    access_token = create_access_token(str(user.id), user.username, user.role)

    return BaseResponse(
        data=TokenResponse(
            access_token=access_token,
            expires_in=settings.JWT_EXPIRATION_HOURS * 3600,
        ).model_dump()
    )


@router.get("/me", response_model=BaseResponse)
async def get_me(current_user: User = Depends(get_current_user)):
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


@router.get("/permissions", response_model=BaseResponse)
async def get_my_permissions(current_user: User = Depends(get_current_user)):
    """获取当前用户的权限列表。"""
    async with AsyncSessionLocal() as session:
        perms = list(await permission_repo.get_by_user(session, str(current_user.id)))
        # 兼容旧逻辑：同时纳入 user.role 对应的权限
        role = await role_repo.get_by_name(session, current_user.role)
        if role:
            role_perms = await permission_repo.get_by_role(session, str(role.id))
            seen = {p.id for p in perms}
            for rp in role_perms:
                if rp.id not in seen:
                    perms.append(rp)

        return BaseResponse(
            data=[
                PermissionResponse(
                    id=str(p.id),
                    code=p.code,
                    name=p.name,
                    description=p.description,
                    created_at=p.created_at,
                ).model_dump()
                for p in perms
            ]
        )


@router.get("/menus", response_model=BaseResponse)
async def get_my_menus(current_user: User = Depends(get_current_user)):
    """获取当前用户的菜单树（从 permissions 表筛选 type='menu'）。"""
    async with AsyncSessionLocal() as session:
        # admin 返回全部菜单
        if current_user.role == "admin":
            menus = list(await permission_repo.get_menus(session))
        else:
            # 优先通过 user_roles 关联表查询，同时兼容 user.role 字符串
            menus = list(await permission_repo.get_menus_by_user(session, str(current_user.id)))
            role = await role_repo.get_by_name(session, current_user.role)
            if role:
                role_menus = await permission_repo.get_menus(session, str(role.id))
                seen = {m.id for m in menus}
                for rm in role_menus:
                    if rm.id not in seen:
                        menus.append(rm)

        # 构建菜单树
        tree = build_tree(
            menus,
            id_getter=lambda m: str(m.id),
            parent_getter=lambda m: str(m.parent_id) if m.parent_id else None,
            sort_key=lambda m: m.sort_order,
        )

        result = tree_to_dict(
            tree,
            converter=lambda m: {
                "id": str(m.id),
                "name": m.name,
                "code": m.code,
                "path": m.path,
                "icon": m.icon,
                "type": m.type,
                "parent_id": str(m.parent_id) if m.parent_id else None,
                "sort_order": m.sort_order,
                "hidden": m.hidden,
                "created_at": m.created_at,
            },
        )

    return BaseResponse(data=result)
