"""Where finished images go: a Cloudflare R2 / S3 bucket (signed URLs), or ./outputs if no bucket is set."""
import asyncio
import logging

from .config import ROOT, Settings

log = logging.getLogger("qwen-api")


class Storage:
    def __init__(self, s: Settings):
        self.s = s
        self.local_dir = ROOT / "outputs"
        self.client = None
        if s.r2_bucket and s.r2_access_key_id and s.r2_secret_access_key and s.r2_endpoint:
            import boto3
            from botocore.config import Config

            self.client = boto3.client(
                "s3", endpoint_url=s.r2_endpoint, region_name=s.r2_region,
                aws_access_key_id=s.r2_access_key_id, aws_secret_access_key=s.r2_secret_access_key,
                config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}))
            log.info("storage: bucket %s at %s", s.r2_bucket, s.r2_endpoint)
        else:
            self.local_dir.mkdir(exist_ok=True)
            log.warning("storage: R2 not configured, saving to %s (served at /files/)", self.local_dir)

    @property
    def is_bucket(self) -> bool:
        return self.client is not None

    def key(self, name: str) -> str:
        return f"{self.s.r2_prefix.strip('/')}/{name}".lstrip("/")

    async def save(self, name: str, data: bytes, content_type: str) -> None:
        if self.client:
            await asyncio.to_thread(self.client.put_object, Bucket=self.s.r2_bucket, Key=self.key(name),
                                    Body=data, ContentType=content_type)
        else:
            await asyncio.to_thread((self.local_dir / name).write_bytes, data)

    async def delete(self, name: str) -> None:
        if self.client:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.s.r2_bucket, Key=self.key(name))
        else:
            (self.local_dir / name).unlink(missing_ok=True)

    def url(self, name: str) -> str:
        """Bucket: signed GET URL (fresh on every call). Local: path under /files/ (made absolute by the API)."""
        if not self.client:
            return f"/files/{name}"
        if self.s.r2_public_base_url:
            return f"{self.s.r2_public_base_url.rstrip('/')}/{self.key(name)}"
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.s.r2_bucket, "Key": self.key(name)},
            ExpiresIn=self.s.r2_url_expires)
