"""
Cloudflare R2 Storage utility for camera snapshots.

R2 is S3-compatible, so we use boto3 with a custom endpoint.
Images are uploaded with public-read ACL and served via R2 public URL.

Config via environment variables:
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
  R2_ENDPOINT_URL
  R2_BUCKET_NAME
  R2_PUBLIC_URL  (optional — custom domain or r2.dev URL)
"""

import io
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache()
def _get_r2_client():
    """Create and cache the boto3 S3 client for R2."""
    import boto3
    from app.config import get_settings
    settings = get_settings()

    endpoint = getattr(settings, "R2_ENDPOINT_URL", "")
    access_key = getattr(settings, "R2_ACCESS_KEY_ID", "")
    secret_key = getattr(settings, "R2_SECRET_ACCESS_KEY", "")

    if not endpoint or not access_key or not secret_key:
        logger.warning("R2 not configured — snapshots will be saved locally")
        return None

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    logger.info("R2 client initialized: %s", endpoint)
    return client


def is_r2_configured() -> bool:
    """Check if R2 credentials are configured."""
    from app.config import get_settings
    settings = get_settings()
    return bool(
        getattr(settings, "R2_ENDPOINT_URL", "")
        and getattr(settings, "R2_ACCESS_KEY_ID", "")
        and getattr(settings, "R2_SECRET_ACCESS_KEY", "")
    )


def upload_to_r2(content: bytes, key: str, content_type: str = "image/jpeg") -> str | None:
    """
    Upload file content to R2 bucket.

    Args:
        content: file bytes
        key: object key (e.g., "camera/token-id/front_first_weight_20260414.jpg")
        content_type: MIME type

    Returns:
        Public URL of the uploaded file, or None on failure.
    """
    from app.config import get_settings
    settings = get_settings()

    client = _get_r2_client()
    if client is None:
        return None

    bucket = getattr(settings, "R2_BUCKET_NAME", "weighbridge-snapshots")

    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

        # Build public URL
        public_base = getattr(settings, "R2_PUBLIC_URL", "")
        if public_base:
            url = f"{public_base.rstrip('/')}/{key}"
        else:
            # Fallback: use endpoint URL (won't work without public access)
            url = f"{settings.R2_ENDPOINT_URL}/{bucket}/{key}"

        logger.info("Uploaded to R2: %s (%d bytes)", key, len(content))
        return url

    except Exception as e:
        logger.error("R2 upload failed for %s: %s", key, e)
        return None


def delete_from_r2(key: str) -> bool:
    """Delete a file from R2."""
    from app.config import get_settings
    settings = get_settings()

    client = _get_r2_client()
    if client is None:
        return False

    bucket = getattr(settings, "R2_BUCKET_NAME", "weighbridge-snapshots")

    try:
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        logger.error("R2 delete failed for %s: %s", key, e)
        return False
