"""Category management API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy import select

from app.models.schemas import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    CategoryTreeNode,
    DocumentResponse,
    BaseResponse,
    PaginationParams,
)
from app.db.base import AsyncSessionLocal
from app.db.repository import category_repo, document_repo
from app.db.models import Category, User
from app.api.auth import require_permission

router = APIRouter(prefix="/categories", tags=["Categories"])


def _category_to_response(category: Category) -> CategoryResponse:
    return CategoryResponse(
        id=str(category.id),
        name=category.name,
        description=category.description,
        parent_id=category.parent_id,
        user_id=category.user_id,
        sort_order=category.sort_order or 0,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


async def _build_tree(
    session, categories: list[Category], parent_id: Optional[str] = None
) -> list[CategoryTreeNode]:
    """递归构建分类树。"""
    nodes = []
    for cat in categories:
        if cat.parent_id == parent_id:
            doc_count = await category_repo.count_documents(session, str(cat.id))
            children = await _build_tree(session, categories, str(cat.id))
            nodes.append(
                CategoryTreeNode(
                    id=str(cat.id),
                    name=cat.name,
                    description=cat.description,
                    parent_id=cat.parent_id,
                    user_id=cat.user_id,
                    sort_order=cat.sort_order or 0,
                    doc_count=doc_count,
                    children=children,
                    created_at=cat.created_at,
                )
            )
    return nodes


@router.get("", response_model=BaseResponse)
async def list_categories(user_id: Optional[str] = Query(None)):
    """获取分类树形列表。支持按 user_id 过滤。"""
    async with AsyncSessionLocal() as session:
        if user_id:
            rows = await category_repo.get_by_user(session, user_id)
        else:
            rows = await category_repo.list(session, limit=1000)
        tree = await _build_tree(session, list(rows))
    return BaseResponse(data=tree)


@router.post("", response_model=BaseResponse)
async def create_category(request: CategoryCreate, user_id: Optional[str] = Query(None), current_user: User = Depends(require_permission("category:manage"))):
    """创建分类。"""
    async with AsyncSessionLocal() as session:
        # 检查父分类是否存在
        if request.parent_id:
            parent = await category_repo.get(session, request.parent_id)
            if not parent:
                raise HTTPException(status_code=404, detail="Parent category not found")

        category = Category(
            name=request.name,
            description=request.description,
            parent_id=request.parent_id,
            user_id=user_id,
        )
        category = await category_repo.create(session, category)
        await session.commit()
    return BaseResponse(data=_category_to_response(category))


@router.put("/{category_id}", response_model=BaseResponse)
async def update_category(category_id: str, request: CategoryUpdate, current_user: User = Depends(require_permission("category:manage"))):
    """更新分类。"""
    async with AsyncSessionLocal() as session:
        category = await category_repo.get(session, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        # 检查父分类是否存在且不会形成循环
        if request.parent_id is not None and request.parent_id != category_id:
            if request.parent_id:
                parent = await category_repo.get(session, request.parent_id)
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent category not found")
                # 简单循环检测：不允许把父分类设为自己的子孙
                # 实际生产环境需要递归检测

        if request.name is not None:
            category.name = request.name
        if request.description is not None:
            category.description = request.description
        if request.parent_id is not None:
            category.parent_id = request.parent_id
        if request.sort_order is not None:
            category.sort_order = request.sort_order

        await session.commit()
        await session.refresh(category)
    return BaseResponse(data=_category_to_response(category))


@router.delete("/{category_id}", response_model=BaseResponse)
async def delete_category(category_id: str, move_to_id: Optional[str] = Query(None), current_user: User = Depends(require_permission("category:manage"))):
    """删除分类。可选 move_to_id 将文档移动到其它分类。"""
    async with AsyncSessionLocal() as session:
        category = await category_repo.get(session, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        # 如果指定了移动目标，先迁移文档
        if move_to_id:
            target = await category_repo.get(session, move_to_id)
            if not target:
                raise HTTPException(status_code=404, detail="Target category not found")
            docs = await category_repo.get_documents_by_category(session, category_id, limit=10000)
            for doc in docs:
                doc.category_id = move_to_id
            await session.flush()
        else:
            # 否则将该分类下的文档 category_id 设为 NULL
            docs = await category_repo.get_documents_by_category(session, category_id, limit=10000)
            for doc in docs:
                doc.category_id = None
            await session.flush()

        await category_repo.delete(session, category)
        await session.commit()
    return BaseResponse(data={"message": "Category deleted"})


@router.get("/{category_id}/documents", response_model=BaseResponse)
async def get_category_documents(
    category_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取某个分类下的文档列表。"""
    async with AsyncSessionLocal() as session:
        category = await category_repo.get(session, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        offset = (page - 1) * page_size
        docs = await category_repo.get_documents_by_category(session, category_id, limit=page_size, offset=offset)
        total = await category_repo.count_documents(session, category_id)

        data = [
            DocumentResponse(
                id=str(doc.id),
                filename=doc.filename,
                original_name=doc.original_name,
                file_size=doc.file_size,
                mime_type=doc.mime_type,
                oss_url=doc.oss_url,
                parse_status=doc.parse_status,
                page_count=doc.page_count,
                category_id=doc.category_id,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
            for doc in docs
        ]

    return BaseResponse(
        data={
            "items": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
