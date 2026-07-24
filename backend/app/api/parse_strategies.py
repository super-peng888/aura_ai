"""解析策略管理 API。"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from app.models.schemas import (
    BaseResponse,
    ParseStrategyCreate,
    ParseStrategyUpdate,
    ParseStrategyResponse,
)
from app.db.base import AsyncSessionLocal
from app.db.repository import parse_strategy_repo, user_repo
from app.db.models import User, ParseStrategy
from app.api.auth import get_current_user

router = APIRouter(prefix="/parse-strategies", tags=["Parse Strategies"])


@router.get("", response_model=BaseResponse)
async def list_strategies(current_user: User = Depends(get_current_user)):
    """获取当前用户的所有解析策略。"""
    async with AsyncSessionLocal() as session:
        strategies = await parse_strategy_repo.get_by_user(session, str(current_user.id))

    return BaseResponse(
        data=[
            ParseStrategyResponse(
                id=str(s.id),
                name=s.name,
                user_id=str(s.user_id) if s.user_id else None,
                is_default=s.is_default,
                parse_mode=s.parse_mode,
                chunk_size=s.chunk_size,
                chunk_overlap=s.chunk_overlap,
                dimension=s.dimension,
                split_method=s.split_method,
                extract_images=s.extract_images,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in strategies
        ]
    )


@router.post("", response_model=BaseResponse)
async def create_strategy(
    request: ParseStrategyCreate,
    current_user: User = Depends(get_current_user),
):
    """创建解析策略。如果设为默认，清除该用户其他默认策略。"""
    async with AsyncSessionLocal() as session:
        strategy = ParseStrategy(
            name=request.name,
            user_id=str(current_user.id),
            parse_mode=request.parse_mode.value,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            dimension=request.dimension,
            split_method=request.split_method.value,
            extract_images=request.extract_images,
        )
        await parse_strategy_repo.create(session, strategy)
        await session.commit()

    return BaseResponse(
        data=ParseStrategyResponse(
            id=str(strategy.id),
            name=strategy.name,
            user_id=str(strategy.user_id) if strategy.user_id else None,
            is_default=strategy.is_default,
            parse_mode=strategy.parse_mode,
            chunk_size=strategy.chunk_size,
            chunk_overlap=strategy.chunk_overlap,
            dimension=strategy.dimension,
            split_method=strategy.split_method,
            extract_images=strategy.extract_images,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
        ).model_dump()
    )


@router.put("/{strategy_id}", response_model=BaseResponse)
async def update_strategy(
    strategy_id: str,
    request: ParseStrategyUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新解析策略。"""
    async with AsyncSessionLocal() as session:
        strategy = await parse_strategy_repo.get(session, strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if str(strategy.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="无权修改此策略")

        if request.name is not None:
            strategy.name = request.name
        if request.parse_mode is not None:
            strategy.parse_mode = request.parse_mode.value
        if request.chunk_size is not None:
            strategy.chunk_size = request.chunk_size
        if request.chunk_overlap is not None:
            strategy.chunk_overlap = request.chunk_overlap
        if request.dimension is not None:
            strategy.dimension = request.dimension
        if request.split_method is not None:
            strategy.split_method = request.split_method.value
        if request.extract_images is not None:
            strategy.extract_images = request.extract_images
        if request.is_default is not None:
            if request.is_default:
                await parse_strategy_repo.clear_default_by_user(session, str(current_user.id))
            strategy.is_default = request.is_default

        await session.commit()
        await session.refresh(strategy)

    return BaseResponse(
        data=ParseStrategyResponse(
            id=str(strategy.id),
            name=strategy.name,
            user_id=str(strategy.user_id) if strategy.user_id else None,
            is_default=strategy.is_default,
            parse_mode=strategy.parse_mode,
            chunk_size=strategy.chunk_size,
            chunk_overlap=strategy.chunk_overlap,
            dimension=strategy.dimension,
            split_method=strategy.split_method,
            extract_images=strategy.extract_images,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
        ).model_dump()
    )


@router.post("/{strategy_id}/set-default", response_model=BaseResponse)
async def set_default_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
):
    """将指定策略设为当前用户的默认策略。"""
    async with AsyncSessionLocal() as session:
        strategy = await parse_strategy_repo.get(session, strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if str(strategy.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="无权修改此策略")

        await parse_strategy_repo.clear_default_by_user(session, str(current_user.id))
        strategy.is_default = True
        await session.commit()

        user = await user_repo.get(session, str(current_user.id))
        user.default_strategy_id = strategy_id
        await session.commit()

    return BaseResponse(data={"message": "Default strategy set"})


@router.delete("/{strategy_id}", response_model=BaseResponse)
async def delete_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除解析策略。如果被用户设为默认，清除默认引用。"""
    async with AsyncSessionLocal() as session:
        strategy = await parse_strategy_repo.get(session, strategy_id)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if str(strategy.user_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="无权删除此策略")

        # 如果用户默认策略指向该策略，清除
        user = await user_repo.get(session, str(current_user.id))
        if user and user.default_strategy_id == strategy_id:
            user.default_strategy_id = None

        await parse_strategy_repo.delete(session, strategy)
        await session.commit()

    return BaseResponse(data={"message": "Strategy deleted"})
