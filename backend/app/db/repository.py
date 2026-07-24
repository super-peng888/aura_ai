"""Repository pattern with SQLAlchemy 2.0 async."""

from typing import Generic, TypeVar, Type, Optional, List, Sequence
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, func, text, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    DocumentChunk,
    DocumentImage,
    User,
    Conversation,
    Message,
    ParseTask,
    Category,
    Role,
    Permission,
    RolePermission,
    UserRole,
    AuditLog,
    DocumentVersion,
    PromptTemplate,
    ParseStrategy,
    UserModelConfig,
    SystemRetrievalConfig,
    SystemParseConfig,
    KGEntity,
    KGRelation,
    KGChunkEntity,
    KGCommunity,
)

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic async repository."""

    def __init__(self, model: Type[T]):
        self.model = model

    async def get(self, session: AsyncSession, obj_id: str) -> Optional[T]:
        return await session.get(self.model, obj_id)

    async def list(self, session: AsyncSession, *, limit: int = 100, offset: int = 0) -> Sequence[T]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def create(self, session: AsyncSession, obj: T) -> T:
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, obj: T) -> None:
        await session.delete(obj)
        await session.flush()

    async def count(self, session: AsyncSession) -> int:
        stmt = select(func.count()).select_from(self.model)
        result = await session.execute(stmt)
        return result.scalar_one()


class DocumentRepository(BaseRepository[Document]):
    def __init__(self):
        super().__init__(Document)

    async def get_by_status(self, session: AsyncSession, status: str, limit: int = 100) -> Sequence[Document]:
        stmt = select(Document).where(Document.parse_status == status).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


class ChunkRepository(BaseRepository[DocumentChunk]):
    def __init__(self):
        super().__init__(DocumentChunk)

    async def list_by_document(self, session: AsyncSession, document_id: str) -> Sequence[DocumentChunk]:
        stmt = select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_milvus_ids(self, session: AsyncSession, milvus_ids: List[str]) -> Sequence[DocumentChunk]:
        if not milvus_ids:
            return []
        stmt = select(DocumentChunk).where(DocumentChunk.milvus_id.in_(milvus_ids))
        result = await session.execute(stmt)
        return result.scalars().all()


class ImageRepository(BaseRepository[DocumentImage]):
    def __init__(self):
        super().__init__(DocumentImage)

    async def get_by_ref_ids(self, session: AsyncSession, ref_ids: List[str]) -> Sequence[DocumentImage]:
        if not ref_ids:
            return []
        stmt = select(DocumentImage).where(DocumentImage.image_ref_id.in_(ref_ids))
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_document(self, session: AsyncSession, document_id: str) -> Sequence[DocumentImage]:
        stmt = select(DocumentImage).where(DocumentImage.document_id == document_id).order_by(DocumentImage.page_number)
        result = await session.execute(stmt)
        return result.scalars().all()


class UserRepository(BaseRepository[User]):
    def __init__(self):
        super().__init__(User)

    async def get_by_username(self, session: AsyncSession, username: str) -> Optional[User]:
        stmt = select(User).where(User.username == username)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self):
        super().__init__(Conversation)

    async def list_by_user(self, session: AsyncSession, user_id: str, limit: int = 100, offset: int = 0) -> Sequence[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_share_token(self, session: AsyncSession, token: str) -> Optional[Conversation]:
        stmt = select(Conversation).where(Conversation.share_token == token, Conversation.is_shared == True)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class MessageRepository(BaseRepository[Message]):
    def __init__(self):
        super().__init__(Message)

    async def list_by_conversation(self, session: AsyncSession, conversation_id: str, limit: int = 100) -> Sequence[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


class ParseTaskRepository(BaseRepository[ParseTask]):
    def __init__(self):
        super().__init__(ParseTask)


class CategoryRepository(BaseRepository[Category]):
    def __init__(self):
        super().__init__(Category)

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Sequence[Category]:
        stmt = select(Category).where(Category.user_id == user_id).order_by(Category.sort_order, Category.created_at)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_roots(self, session: AsyncSession) -> Sequence[Category]:
        stmt = select(Category).where(Category.parent_id.is_(None)).order_by(Category.sort_order, Category.created_at)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def count_documents(self, session: AsyncSession, category_id: str) -> int:
        stmt = select(func.count()).select_from(Document).where(Document.category_id == category_id)
        result = await session.execute(stmt)
        return result.scalar_one()

    async def get_documents_by_category(
        self, session: AsyncSession, category_id: str, limit: int = 100, offset: int = 0
    ) -> Sequence[Document]:
        stmt = (
            select(Document)
            .where(Document.category_id == category_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


class AuditLogRepository(BaseRepository[AuditLog]):
    def __init__(self):
        super().__init__(AuditLog)

    async def query(
        self,
        session: AsyncSession,
        *,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        from sqlalchemy import select
        stmt = select(AuditLog)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if start_date:
            stmt = stmt.where(AuditLog.created_at >= start_date)
        if end_date:
            stmt = stmt.where(AuditLog.created_at <= end_date)
        stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def count_with_filters(
        self,
        session: AsyncSession,
        *,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> int:
        from sqlalchemy import select
        stmt = select(func.count()).select_from(AuditLog)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if start_date:
            stmt = stmt.where(AuditLog.created_at >= start_date)
        if end_date:
            stmt = stmt.where(AuditLog.created_at <= end_date)
        result = await session.execute(stmt)
        return result.scalar_one()


class RoleRepository(BaseRepository[Role]):
    def __init__(self):
        super().__init__(Role)

    async def get_by_name(self, session: AsyncSession, name: str) -> Optional[Role]:
        stmt = select(Role).where(Role.name == name)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class PermissionRepository(BaseRepository[Permission]):
    def __init__(self):
        super().__init__(Permission)

    async def get_by_code(self, session: AsyncSession, code: str) -> Optional[Permission]:
        stmt = select(Permission).where(Permission.code == code)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_role(self, session: AsyncSession, role_id: str) -> Sequence[Permission]:
        stmt = (
            select(Permission)
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .where(RolePermission.role_id == role_id)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Sequence[Permission]:
        """获取用户的所有权限（通过 user_roles → roles → role_permissions → permissions）。"""
        stmt = (
            select(Permission)
            .distinct()
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_menus(self, session: AsyncSession, role_id: Optional[str] = None) -> Sequence[Permission]:
        """获取菜单类型的权限列表（用于前端导航）。"""
        stmt = select(Permission).where(Permission.type == "menu").order_by(Permission.sort_order.asc())
        if role_id:
            stmt = (
                select(Permission)
                .join(RolePermission, Permission.id == RolePermission.permission_id)
                .where(RolePermission.role_id == role_id, Permission.type == "menu")
                .order_by(Permission.sort_order.asc())
            )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_menus_by_user(self, session: AsyncSession, user_id: str) -> Sequence[Permission]:
        """获取用户的所有菜单权限（通过 user_roles 关联）。"""
        stmt = (
            select(Permission)
            .distinct()
            .join(RolePermission, Permission.id == RolePermission.permission_id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Permission.type == "menu")
            .order_by(Permission.sort_order.asc())
        )
        result = await session.execute(stmt)
        return result.scalars().all()


class UserRoleRepository(BaseRepository[UserRole]):
    def __init__(self):
        super().__init__(UserRole)

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Sequence[UserRole]:
        stmt = select(UserRole).where(UserRole.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_roles_by_user(self, session: AsyncSession, user_id: str) -> Sequence[Role]:
        stmt = select(Role).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def sync_user_role(self, session: AsyncSession, user_id: str, role_name: str) -> None:
        """同步用户的角色关联：删除旧关联，创建与新角色的关联。"""
        # 删除旧关联
        old_links = await session.execute(select(UserRole).where(UserRole.user_id == user_id))
        for link in old_links.scalars().all():
            await session.delete(link)

        # 查找新角色
        role_result = await session.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if role:
            session.add(UserRole(user_id=user_id, role_id=str(role.id)))
        await session.flush()


class PromptTemplateRepository(BaseRepository[PromptTemplate]):
    def __init__(self):
        super().__init__(PromptTemplate)

    async def get_by_category(self, session: AsyncSession, category: str) -> Sequence[PromptTemplate]:
        stmt = select(PromptTemplate).where(PromptTemplate.category == category)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_system_templates(self, session: AsyncSession) -> Sequence[PromptTemplate]:
        stmt = select(PromptTemplate).where(PromptTemplate.is_system == True)
        result = await session.execute(stmt)
        return result.scalars().all()


class ParseStrategyRepository(BaseRepository[ParseStrategy]):
    def __init__(self):
        super().__init__(ParseStrategy)

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Sequence[ParseStrategy]:
        stmt = select(ParseStrategy).where(ParseStrategy.user_id == user_id).order_by(ParseStrategy.created_at.desc())
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_default_by_user(self, session: AsyncSession, user_id: str) -> Optional[ParseStrategy]:
        stmt = select(ParseStrategy).where(
            ParseStrategy.user_id == user_id,
            ParseStrategy.is_default == True,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def clear_default_by_user(self, session: AsyncSession, user_id: str) -> None:
        stmt = select(ParseStrategy).where(ParseStrategy.user_id == user_id, ParseStrategy.is_default == True)
        result = await session.execute(stmt)
        for strategy in result.scalars().all():
            strategy.is_default = False
        await session.flush()


class DataSourceRepository(BaseRepository["DataSource"]):
    def __init__(self):
        from app.db.models import DataSource
        super().__init__(DataSource)

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Sequence["DataSource"]:
        from app.db.models import DataSource
        stmt = select(DataSource).where(DataSource.user_id == user_id).order_by(DataSource.created_at.desc())
        result = await session.execute(stmt)
        return result.scalars().all()


class BIQueryLogRepository(BaseRepository["BIQueryLog"]):
    def __init__(self):
        from app.db.models import BIQueryLog
        super().__init__(BIQueryLog)

    async def list_by_user(self, session: AsyncSession, user_id: str, limit: int = 50) -> Sequence["BIQueryLog"]:
        from app.db.models import BIQueryLog
        stmt = select(BIQueryLog).where(BIQueryLog.user_id == user_id).order_by(BIQueryLog.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


class BIReportRepository(BaseRepository["BIReport"]):
    def __init__(self):
        from app.db.models import BIReport
        super().__init__(BIReport)

    async def list_by_user(self, session: AsyncSession, user_id: str, limit: int = 50) -> Sequence["BIReport"]:
        from app.db.models import BIReport
        stmt = select(BIReport).where(BIReport.user_id == user_id).order_by(BIReport.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_share_token(self, session: AsyncSession, token: str) -> Optional["BIReport"]:
        from app.db.models import BIReport
        stmt = select(BIReport).where(BIReport.share_token == token, BIReport.is_shared == True)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class UserModelConfigRepository(BaseRepository[UserModelConfig]):
    def __init__(self):
        super().__init__(UserModelConfig)

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Optional[UserModelConfig]:
        """Legacy: get first config for user (deprecated, use get_current_by_user or list_by_user)."""
        stmt = select(UserModelConfig).where(UserModelConfig.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, session: AsyncSession, user_id: str) -> Sequence[UserModelConfig]:
        stmt = select(UserModelConfig).where(UserModelConfig.user_id == user_id).order_by(UserModelConfig.created_at.desc())
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_current_by_user(self, session: AsyncSession, user_id: str) -> Optional[UserModelConfig]:
        stmt = select(UserModelConfig).where(
            UserModelConfig.user_id == user_id,
            UserModelConfig.is_current == True,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def clear_current_by_user(self, session: AsyncSession, user_id: str) -> None:
        stmt = select(UserModelConfig).where(
            UserModelConfig.user_id == user_id,
            UserModelConfig.is_current == True,
        )
        result = await session.execute(stmt)
        for cfg in result.scalars().all():
            cfg.is_current = False
        await session.flush()


class RetrievalConfigRepository(BaseRepository[SystemRetrievalConfig]):
    """系统级检索配置（单行表）。"""

    UPDATABLE_FIELDS = (
        "rerank_top_k", "similarity_threshold",
        "enable_query_rewrite", "enable_keyword_search", "enable_vector_search", "enable_rerank",
        "rag_mode", "enable_graph_rag", "graph_search_mode",
    )

    def __init__(self):
        super().__init__(SystemRetrievalConfig)

    async def get_singleton(self, session: AsyncSession) -> Optional[SystemRetrievalConfig]:
        stmt = select(SystemRetrievalConfig).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, session: AsyncSession, config: SystemRetrievalConfig) -> SystemRetrievalConfig:
        existing = await self.get_singleton(session)
        if existing is None:
            return await self.create(session, config)
        for field in self.UPDATABLE_FIELDS:
            setattr(existing, field, getattr(config, field))
        await session.flush()
        await session.refresh(existing)
        return existing


class ParseConfigRepository(BaseRepository[SystemParseConfig]):
    """系统级解析配置（单行表，VLM 视觉解析模型）。"""

    UPDATABLE_FIELDS = (
        "vlm_model", "vlm_base_url", "vlm_api_key", "vlm_detail_level", "vlm_max_tokens",
    )

    def __init__(self):
        super().__init__(SystemParseConfig)

    async def get_singleton(self, session: AsyncSession) -> Optional[SystemParseConfig]:
        stmt = select(SystemParseConfig).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, session: AsyncSession, config: SystemParseConfig) -> SystemParseConfig:
        existing = await self.get_singleton(session)
        if existing is None:
            return await self.create(session, config)
        for field in self.UPDATABLE_FIELDS:
            setattr(existing, field, getattr(config, field))
        await session.flush()
        await session.refresh(existing)
        return existing


class DataPermissionRepository(BaseRepository["DataPermission"]):
    def __init__(self):
        from app.db.models import DataPermission
        super().__init__(DataPermission)

    async def get_by_user(self, session: AsyncSession, user_id: str) -> Sequence["DataPermission"]:
        from app.db.models import DataPermission
        stmt = select(DataPermission).where(DataPermission.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_user_and_source(self, session: AsyncSession, user_id: str, data_source_id: str) -> Optional["DataPermission"]:
        from app.db.models import DataPermission
        stmt = select(DataPermission).where(
            DataPermission.user_id == user_id,
            DataPermission.data_source_id == data_source_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class DocumentVersionRepository(BaseRepository[DocumentVersion]):
    def __init__(self):
        super().__init__(DocumentVersion)

    async def get_by_document(self, session: AsyncSession, document_id: str) -> Sequence[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_next_version(self, session: AsyncSession, document_id: str) -> int:
        stmt = (
            select(func.max(DocumentVersion.version))
            .where(DocumentVersion.document_id == document_id)
        )
        result = await session.execute(stmt)
        max_version = result.scalar_one_or_none()
        return (max_version or 0) + 1


class KnowledgeGraphRepository:
    """GraphRAG 知识图谱仓储（kg_entities / kg_relations / kg_chunk_entities / kg_communities）。

    入库侧：upsert_entity / add_relation / link_chunk_entity / remove_document_graph / replace_communities
    检索侧：find_entities_by_names / search_entities / get_entity_neighbors /
            get_chunk_ids_by_entities / get_entities_by_chunk_ids / list_communities
    """

    # ------------------------------------------------------------------
    # 实体
    # ------------------------------------------------------------------
    async def get_entity_by_normalized(self, session: AsyncSession, name_normalized: str) -> Optional[KGEntity]:
        stmt = select(KGEntity).where(KGEntity.name_normalized == name_normalized)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_entities_by_names(self, session: AsyncSession, names_normalized: List[str]) -> Sequence[KGEntity]:
        if not names_normalized:
            return []
        stmt = select(KGEntity).where(KGEntity.name_normalized.in_(names_normalized))
        result = await session.execute(stmt)
        return result.scalars().all()

    async def search_entities(self, session: AsyncSession, keyword: str, limit: int = 10) -> Sequence[KGEntity]:
        """按名称模糊匹配实体（检索侧 query -> 实体锚定用）。"""
        stmt = (
            select(KGEntity)
            .where(KGEntity.name.ilike(f"%{keyword}%"))
            .order_by(KGEntity.chunk_count.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def upsert_entity(
        self,
        session: AsyncSession,
        *,
        name: str,
        entity_type: Optional[str],
        description: Optional[str],
        name_normalized: str,
        chunk_delta: int = 0,
    ) -> KGEntity:
        """按 name_normalized 幂等 upsert 实体：存在则合并描述并累加 chunk_count。"""
        existing = await self.get_entity_by_normalized(session, name_normalized)
        if existing is not None:
            if chunk_delta:
                existing.chunk_count = (existing.chunk_count or 0) + chunk_delta
            if description and len(description) > len(existing.description or ""):
                existing.description = description
            if entity_type and not existing.entity_type:
                existing.entity_type = entity_type
            await session.flush()
            return existing
        entity = KGEntity(
            name=name,
            entity_type=entity_type,
            description=description,
            name_normalized=name_normalized,
            chunk_count=max(0, chunk_delta),
        )
        session.add(entity)
        await session.flush()
        return entity

    async def list_entities(self, session: AsyncSession, limit: int = 10000) -> Sequence[KGEntity]:
        stmt = select(KGEntity).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def count_entities(self, session: AsyncSession) -> int:
        stmt = select(func.count()).select_from(KGEntity)
        result = await session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 关系
    # ------------------------------------------------------------------
    async def add_relation(
        self,
        session: AsyncSession,
        *,
        source_entity_id,
        target_entity_id,
        relation_type: Optional[str],
        description: Optional[str],
        weight: float = 1.0,
        chunk_id: Optional[str] = None,
    ) -> KGRelation:
        """写入关系；同一 (source, target, relation_type, chunk_id) 已存在则合并（累加权重）。"""
        stmt = select(KGRelation).where(
            KGRelation.source_entity_id == source_entity_id,
            KGRelation.target_entity_id == target_entity_id,
            KGRelation.relation_type == relation_type,
            KGRelation.chunk_id == chunk_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.weight = (existing.weight or 1.0) + max(0.0, weight - 1.0)
            if description and len(description) > len(existing.description or ""):
                existing.description = description
            await session.flush()
            return existing
        relation = KGRelation(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            description=description,
            weight=weight,
            chunk_id=chunk_id,
        )
        session.add(relation)
        await session.flush()
        return relation

    async def list_relations(self, session: AsyncSession, limit: int = 50000) -> Sequence[KGRelation]:
        stmt = select(KGRelation).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_entity_neighbors(self, session: AsyncSession, entity_id) -> List[tuple]:
        """实体的一跳邻居：返回 [(KGRelation, 邻居 KGEntity), ...]（检索侧扩展用）。"""
        stmt = select(KGRelation).where(
            (KGRelation.source_entity_id == entity_id) | (KGRelation.target_entity_id == entity_id)
        )
        result = await session.execute(stmt)
        relations = result.scalars().all()
        neighbor_ids = {
            r.target_entity_id if r.source_entity_id == entity_id else r.source_entity_id
            for r in relations
        }
        if not neighbor_ids:
            return []
        ent_result = await session.execute(select(KGEntity).where(KGEntity.id.in_(neighbor_ids)))
        ent_map = {e.id: e for e in ent_result.scalars().all()}
        pairs = []
        for r in relations:
            neighbor_id = r.target_entity_id if r.source_entity_id == entity_id else r.source_entity_id
            neighbor = ent_map.get(neighbor_id)
            if neighbor is not None:
                pairs.append((r, neighbor))
        return pairs

    # ------------------------------------------------------------------
    # chunk <-> entity 关联
    # ------------------------------------------------------------------
    async def link_chunk_entity(
        self,
        session: AsyncSession,
        *,
        chunk_id: str,
        entity_id,
        doc_id: Optional[str] = None,
    ) -> None:
        """建立 chunk-entity 关联，已存在则跳过（幂等）。"""
        existing = await session.get(KGChunkEntity, {"chunk_id": chunk_id, "entity_id": entity_id})
        if existing is not None:
            return
        session.add(KGChunkEntity(chunk_id=chunk_id, entity_id=entity_id, doc_id=doc_id))
        await session.flush()

    async def get_chunk_ids_by_entities(self, session: AsyncSession, entity_ids: List) -> List[str]:
        """按实体集合取关联的 chunk_id 列表（检索侧实体 -> chunk 映射）。"""
        if not entity_ids:
            return []
        stmt = select(KGChunkEntity.chunk_id).where(KGChunkEntity.entity_id.in_(entity_ids)).distinct()
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_entities_by_chunk_ids(self, session: AsyncSession, chunk_ids: List[str]) -> Sequence[KGEntity]:
        """按 chunk_id 集合取关联实体（检索侧 chunk -> 实体反查）。"""
        if not chunk_ids:
            return []
        stmt = (
            select(KGEntity)
            .join(KGChunkEntity, KGEntity.id == KGChunkEntity.entity_id)
            .where(KGChunkEntity.chunk_id.in_(chunk_ids))
            .distinct()
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    # ------------------------------------------------------------------
    # 文档图谱清理（重建幂等）
    # ------------------------------------------------------------------
    async def remove_document_graph(self, session: AsyncSession, *, document_id: str, chunk_ids: List[str]) -> None:
        """删除该文档的 chunk 关联与其产生的孤立关系，并清理失去关联的孤立实体。"""
        if chunk_ids:
            await session.execute(delete(KGRelation).where(KGRelation.chunk_id.in_(chunk_ids)))

        # 统计该文档每个实体即将删除的关联数，递减 chunk_count
        count_stmt = (
            select(KGChunkEntity.entity_id, func.count())
            .where(KGChunkEntity.doc_id == document_id)
            .group_by(KGChunkEntity.entity_id)
        )
        affected = (await session.execute(count_stmt)).all()
        for entity_id, cnt in affected:
            await session.execute(
                update(KGEntity)
                .where(KGEntity.id == entity_id)
                .values(chunk_count=func.greatest(0, KGEntity.chunk_count - cnt))
            )
        await session.execute(delete(KGChunkEntity).where(KGChunkEntity.doc_id == document_id))

        # 清理受影响实体中已无任何 chunk 关联的孤立实体（其关系随 ON DELETE CASCADE 清除）
        if affected:
            affected_ids = [entity_id for entity_id, _ in affected]
            has_links = select(KGChunkEntity.entity_id).where(KGChunkEntity.entity_id == KGEntity.id).exists()
            await session.execute(delete(KGEntity).where(KGEntity.id.in_(affected_ids), ~has_links))
        await session.flush()

    # ------------------------------------------------------------------
    # 社区
    # ------------------------------------------------------------------
    async def replace_communities(self, session: AsyncSession, communities: List[dict]) -> None:
        """整体重写 kg_communities。"""
        await session.execute(delete(KGCommunity))
        for row in communities:
            session.add(KGCommunity(**row))
        await session.flush()

    async def list_communities(self, session: AsyncSession) -> Sequence[KGCommunity]:
        stmt = select(KGCommunity).order_by(KGCommunity.level, KGCommunity.community_key)
        result = await session.execute(stmt)
        return result.scalars().all()


# Global singletons
document_repo = DocumentRepository()
chunk_repo = ChunkRepository()
image_repo = ImageRepository()
user_repo = UserRepository()
conversation_repo = ConversationRepository()
message_repo = MessageRepository()
parse_task_repo = ParseTaskRepository()
category_repo = CategoryRepository()
role_repo = RoleRepository()
permission_repo = PermissionRepository()
user_role_repo = UserRoleRepository()
audit_repo = AuditLogRepository()
document_version_repo = DocumentVersionRepository()
prompt_template_repo = PromptTemplateRepository()
parse_strategy_repo = ParseStrategyRepository()
data_source_repo = DataSourceRepository()
bi_query_log_repo = BIQueryLogRepository()
bi_report_repo = BIReportRepository()
data_permission_repo = DataPermissionRepository()
user_model_config_repo = UserModelConfigRepository()
retrieval_config_repo = RetrievalConfigRepository()
parse_config_repo = ParseConfigRepository()
kg_repo = KnowledgeGraphRepository()
