"""Role and permission management API endpoints (admin only)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.models.schemas import (
    BaseResponse, RoleResponse, PermissionResponse,
    PermissionCreateRequest, PermissionUpdateRequest,
)
from app.db.base import AsyncSessionLocal
from app.db.repository import role_repo, permission_repo
from app.db.models import User, Role, Permission, RolePermission
from app.api.auth import require_permission
from app.utils.tree import build_tree, tree_to_dict

router = APIRouter(prefix="/roles", tags=["Roles"])


@router.get("", response_model=BaseResponse)
async def list_roles(current_user: User = Depends(require_permission("admin:all"))):
    """获取所有角色列表。"""
    async with AsyncSessionLocal() as session:
        roles = await role_repo.list(session, limit=100)
    return BaseResponse(
        data=[
            RoleResponse(
                id=str(r.id),
                name=r.name,
                description=r.description,
                created_at=r.created_at,
            ).model_dump()
            for r in roles
        ]
    )


@router.get("/{role_id}/permissions", response_model=BaseResponse)
async def get_role_permissions(
    role_id: str,
    current_user: User = Depends(require_permission("admin:all")),
):
    """获取某个角色的权限列表（包含 menu/api/button 全部类型）。"""
    async with AsyncSessionLocal() as session:
        role = await role_repo.get(session, role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        perms = await permission_repo.get_by_role(session, role_id)
    return BaseResponse(
        data=[
            PermissionResponse(
                id=str(p.id),
                code=p.code,
                name=p.name,
                description=p.description,
                type=p.type,
                path=p.path,
                icon=p.icon,
                parent_id=str(p.parent_id) if p.parent_id else None,
                sort_order=p.sort_order,
                hidden=p.hidden,
                created_at=p.created_at,
            ).model_dump()
            for p in perms
        ]
    )


@router.put("/{role_id}/permissions", response_model=BaseResponse)
async def update_role_permissions(
    role_id: str,
    permission_ids: list[str],
    current_user: User = Depends(require_permission("admin:all")),
):
    """更新角色的权限分配（全量替换，包含菜单和 API 权限）。"""
    async with AsyncSessionLocal() as session:
        role = await role_repo.get(session, role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # 删除旧关联
        old_links = await session.execute(
            select(RolePermission).where(RolePermission.role_id == role_id)
        )
        for link in old_links.scalars().all():
            await session.delete(link)

        # 创建新关联
        for perm_id in permission_ids:
            perm = await permission_repo.get(session, perm_id)
            if perm:
                session.add(RolePermission(role_id=role_id, permission_id=perm_id))

        await session.commit()
    return BaseResponse(data={"message": "Permissions updated"})


@router.get("/permissions/all", response_model=BaseResponse)
async def list_all_permissions(
    current_user: User = Depends(require_permission("admin:all")),
):
    """获取所有权限列表（包含 menu/api/button 全部类型）。"""
    async with AsyncSessionLocal() as session:
        perms = await permission_repo.list(session, limit=200)
    return BaseResponse(
        data=[
            PermissionResponse(
                id=str(p.id),
                code=p.code,
                name=p.name,
                description=p.description,
                type=p.type,
                path=p.path,
                icon=p.icon,
                parent_id=str(p.parent_id) if p.parent_id else None,
                sort_order=p.sort_order,
                hidden=p.hidden,
                created_at=p.created_at,
            ).model_dump()
            for p in perms
        ]
    )


@router.get("/permissions/tree", response_model=BaseResponse)
async def list_permission_tree(
    current_user: User = Depends(require_permission("admin:all")),
):
    """获取权限树（按层级组织，支持菜单嵌套）。"""
    async with AsyncSessionLocal() as session:
        perms = await permission_repo.list(session, limit=200)

    tree = build_tree(
        perms,
        id_getter=lambda p: str(p.id),
        parent_getter=lambda p: str(p.parent_id) if p.parent_id else None,
        sort_key=lambda p: p.sort_order,
    )

    result = tree_to_dict(
        tree,
        converter=lambda p: {
            "id": str(p.id),
            "code": p.code,
            "name": p.name,
            "description": p.description,
            "type": p.type,
            "path": p.path,
            "icon": p.icon,
            "parent_id": str(p.parent_id) if p.parent_id else None,
            "sort_order": p.sort_order,
            "hidden": p.hidden,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        },
    )

    return BaseResponse(data=result)


@router.post("/permissions", response_model=BaseResponse)
async def create_permission(
    request: PermissionCreateRequest,
    current_user: User = Depends(require_permission("admin:all")),
):
    """创建权限/菜单。"""
    async with AsyncSessionLocal() as session:
        # 检查 code 是否已存在
        existing = await permission_repo.get_by_code(session, request.code)
        if existing:
            raise HTTPException(status_code=409, detail="Permission code already exists")

        perm = Permission(
            code=request.code,
            name=request.name,
            description=request.description,
            type=request.type,
            path=request.path,
            icon=request.icon,
            parent_id=request.parent_id,
            sort_order=request.sort_order,
            hidden=request.hidden,
        )
        await permission_repo.create(session, perm)
        await session.commit()

    return BaseResponse(
        data=PermissionResponse(
            id=str(perm.id),
            code=perm.code,
            name=perm.name,
            description=perm.description,
            type=perm.type,
            path=perm.path,
            icon=perm.icon,
            parent_id=str(perm.parent_id) if perm.parent_id else None,
            sort_order=perm.sort_order,
            hidden=perm.hidden,
            created_at=perm.created_at,
        ).model_dump()
    )


@router.put("/permissions/{permission_id}", response_model=BaseResponse)
async def update_permission(
    permission_id: str,
    request: PermissionUpdateRequest,
    current_user: User = Depends(require_permission("admin:all")),
):
    """更新权限/菜单。"""
    async with AsyncSessionLocal() as session:
        perm = await permission_repo.get(session, permission_id)
        if not perm:
            raise HTTPException(status_code=404, detail="Permission not found")

        # 检查 code 唯一性
        if request.code is not None and request.code != perm.code:
            existing = await permission_repo.get_by_code(session, request.code)
            if existing:
                raise HTTPException(status_code=409, detail="Permission code already exists")
            perm.code = request.code

        if request.name is not None:
            perm.name = request.name
        if request.description is not None:
            perm.description = request.description
        if request.type is not None:
            perm.type = request.type
        if request.path is not None:
            perm.path = request.path
        if request.icon is not None:
            perm.icon = request.icon
        if request.parent_id is not None:
            perm.parent_id = request.parent_id
        if request.sort_order is not None:
            perm.sort_order = request.sort_order
        if request.hidden is not None:
            perm.hidden = request.hidden

        await session.commit()
        await session.refresh(perm)

    return BaseResponse(
        data=PermissionResponse(
            id=str(perm.id),
            code=perm.code,
            name=perm.name,
            description=perm.description,
            type=perm.type,
            path=perm.path,
            icon=perm.icon,
            parent_id=str(perm.parent_id) if perm.parent_id else None,
            sort_order=perm.sort_order,
            hidden=perm.hidden,
            created_at=perm.created_at,
        ).model_dump()
    )


@router.delete("/permissions/{permission_id}", response_model=BaseResponse)
async def delete_permission(
    permission_id: str,
    current_user: User = Depends(require_permission("admin:all")),
):
    """删除权限/菜单。"""
    async with AsyncSessionLocal() as session:
        perm = await permission_repo.get(session, permission_id)
        if not perm:
            raise HTTPException(status_code=404, detail="Permission not found")

        # 检查是否有子权限
        children = await session.execute(
            select(Permission).where(Permission.parent_id == permission_id)
        )
        if children.scalars().first():
            raise HTTPException(status_code=400, detail="Cannot delete permission with children")

        # 清理 role_permissions 关联
        links = await session.execute(
            select(RolePermission).where(RolePermission.permission_id == permission_id)
        )
        for link in links.scalars().all():
            await session.delete(link)

        await permission_repo.delete(session, perm)
        await session.commit()

    return BaseResponse(data={"message": "Permission deleted"})
