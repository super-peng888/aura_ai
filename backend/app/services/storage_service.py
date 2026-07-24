"""File storage upload and management service (OSS / MinIO / S3-compatible)."""

import os
import uuid
import io
from typing import Optional, BinaryIO
from datetime import datetime, timedelta
import aiofiles

from app.config import get_settings

settings = get_settings()


class StorageService:
    """Handle file uploads to OSS/MinIO and URL generation."""

    def __init__(self):
        self.provider = settings.OSS_PROVIDER
        self.bucket = settings.OSS_BUCKET
        self.public_url = settings.OSS_PUBLIC_URL or settings.OSS_ENDPOINT

        if self.provider == "minio":
            self._init_minio()
        elif self.provider == "aliyun":
            self._init_aliyun()
        elif self.provider == "aws":
            self._init_aws()

    def _init_minio(self):
        from minio import Minio

        self.client = Minio(
            settings.OSS_ENDPOINT.replace("http://", "").replace("https://", ""),
            access_key=settings.OSS_ACCESS_KEY,
            secret_key=settings.OSS_SECRET_KEY,
            secure=settings.OSS_ENDPOINT.startswith("https"),
        )
        # Ensure bucket exists
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def _init_aliyun(self):
        import oss2

        self.auth = oss2.Auth(settings.OSS_ACCESS_KEY, settings.OSS_SECRET_KEY)
        self.client = oss2.Bucket(
            self.auth, settings.OSS_ENDPOINT, self.bucket
        )

    def _init_aws(self):
        import boto3

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.OSS_ENDPOINT,
            aws_access_key_id=settings.OSS_ACCESS_KEY,
            aws_secret_access_key=settings.OSS_SECRET_KEY,
            region_name=settings.OSS_REGION,
        )

    def _generate_object_key(
        self, document_id: str, filename: str, prefix: str = "files"
    ) -> str:
        """Generate a unique object key for OSS."""
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
        """Upload file bytes to OSS and return the object key."""
        object_key = self._generate_object_key(document_id, filename, prefix)

        if self.provider == "minio":
            await self._upload_minio(object_key, data, content_type)
        elif self.provider == "aliyun":
            await self._upload_aliyun(object_key, data, content_type)
        elif self.provider == "aws":
            await self._upload_aws(object_key, data, content_type)

        return object_key

    async def _upload_minio(self, object_key: str, data: bytes, content_type: str):
        # Run sync client in thread pool
        import asyncio

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

    async def _upload_aliyun(self, object_key: str, data: bytes, content_type: str):
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self.client.put_object, object_key, io.BytesIO(data)
        )

    async def _upload_aws(self, object_key: str, data: bytes, content_type: str):
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.client.put_object,
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )

    def get_url(self, object_key: str, expires: int = 3600 * 24 * 7) -> str:
        """Get a presigned URL or public URL for an object."""
        if not object_key:
            return ""

        # If public URL is configured, construct direct URL
        if settings.OSS_PUBLIC_URL:
            return f"{settings.OSS_PUBLIC_URL.rstrip('/')}/{object_key}"

        # Otherwise generate presigned URL
        if self.provider == "minio":
            from datetime import timedelta
            url = self.client.presigned_get_object(self.bucket, object_key, timedelta(seconds=expires))
            return url
        elif self.provider == "aliyun":
            url = self.client.sign_url("GET", object_key, expires)
            return url
        elif self.provider == "aws":
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=expires,
            )
            return url

        return f"{settings.OSS_ENDPOINT}/{self.bucket}/{object_key}"

    async def get_presigned_upload_url(self, object_key: str, content_type: str, expires: int = 900) -> str:
        """Get a presigned URL for uploading an object directly from client."""
        if self.provider == "minio":
            import asyncio
            from datetime import timedelta
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self.client.presigned_put_object,
                self.bucket,
                object_key,
                timedelta(seconds=expires),
            )
        elif self.provider == "aliyun":
            return self.client.sign_url("PUT", object_key, expires)
        elif self.provider == "aws":
            import asyncio
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.client.generate_presigned_url(
                    "put_object",
                    Params={"Bucket": self.bucket, "Key": object_key, "ContentType": content_type},
                    ExpiresIn=expires,
                ),
            )
        return ""

    async def generate_thumbnail(
        self, image_data: bytes, max_size: int = 400
    ) -> bytes:
        """Generate a thumbnail from image bytes."""
        from PIL import Image
        import asyncio

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
        import asyncio

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
