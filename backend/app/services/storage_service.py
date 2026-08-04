"""File storage service for RustFS (local, S3-compatible via MinIO client)."""

import logging
import os
import uuid
import io
import asyncio
from datetime import datetime, timedelta

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class StorageService:
    """Handle file uploads to RustFS and URL generation (S3-compatible)."""

    def __init__(self):
        self.bucket = settings.OSS_BUCKET
        self.public_url = settings.OSS_PUBLIC_URL or settings.OSS_ENDPOINT

        from minio import Minio

        self.client = Minio(
            settings.OSS_ENDPOINT.replace("http://", "").replace("https://", ""),
            access_key=settings.OSS_ACCESS_KEY,
            secret_key=settings.OSS_SECRET_KEY,
            secure=settings.OSS_ENDPOINT.startswith("https"),
        )
        # 确保 bucket 存在。凭据/网络错误时仅记警告，不阻断应用启动
        # （否则存储不可用会连带 API、登录、聊天等全部无法启动）。
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except Exception as e:
            logger.warning(
                "RustFS bucket 检查/创建失败：%s。应用仍会启动，但上传/下载会失败，"
                "请核对 OSS_ENDPOINT / OSS_ACCESS_KEY / OSS_SECRET_KEY / OSS_BUCKET 配置。",
                e,
            )

    def _generate_object_key(
        self, document_id: str, filename: str, prefix: str = "files"
    ) -> str:
        """Generate a unique object key for storage."""
        ext = os.path.splitext(filename)[1].lower()
        unique_id = uuid.uuid4().hex[:12]
        timestamp = datetime.now().strftime("%Y%m%d")
        return f"{prefix}/{document_id}/{timestamp}/{unique_id}{ext}"

    async def upload_file(
        self,
        data: bytes,
        document_id: str,
        filename: str,
        content_type: str = "application/octet-stream",
        prefix: str = "files",
    ) -> str:
        """Upload file bytes to RustFS and return the object key."""
        object_key = self._generate_object_key(document_id, filename, prefix)

        # Run sync client in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.client.put_object,
            self.bucket,
            object_key,
            io.BytesIO(data),
            len(data),
            content_type,
        )
        return object_key

    def get_url(self, object_key: str, expires: int = 3600 * 24 * 7) -> str:
        """Get a presigned URL or public URL for an object."""
        if not object_key:
            return ""

        # If public URL is configured, construct direct URL
        if settings.OSS_PUBLIC_URL:
            return f"{settings.OSS_PUBLIC_URL.rstrip('/')}/{object_key}"

        # Otherwise generate presigned URL
        return self.client.presigned_get_object(
            self.bucket, object_key, timedelta(seconds=expires)
        )

    async def get_presigned_upload_url(
        self, object_key: str, content_type: str, expires: int = 900
    ) -> str:
        """Get a presigned URL for uploading an object directly from client."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.client.presigned_put_object,
            self.bucket,
            object_key,
            timedelta(seconds=expires),
        )

    async def generate_thumbnail(
        self, image_data: bytes, max_size: int = 400
    ) -> bytes:
        """Generate a thumbnail from image bytes."""
        from PIL import Image

        loop = asyncio.get_event_loop()

        def _resize():
            img = Image.open(io.BytesIO(image_data))
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            img_format = img.format or "PNG"
            img.save(output, format=img_format, quality=85)
            return output.getvalue()

        return await loop.run_in_executor(None, _resize)

    async def get_image_info(self, image_data: bytes) -> dict:
        """Get image dimensions and format."""
        from PIL import Image

        loop = asyncio.get_event_loop()

        def _info():
            img = Image.open(io.BytesIO(image_data))
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
            }

        return await loop.run_in_executor(None, _info)


# Global singleton
storage_service = StorageService()
