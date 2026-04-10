"""
Backup & Restore router — pg_dump/pg_restore wrappers.

Security hardening:
  - All backup files are AES-256-GCM encrypted using PRIVATE_DATA_KEY
  - Stored with .enc extension — unreadable without the key
  - Even if an officer seizes the backup folder, they see only ciphertext
  - Restore decrypts in memory before piping to psql (never plaintext on disk)
"""
import asyncio
import io
import os
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.user import User

router = APIRouter(prefix="/api/v1/backup", tags=["Backup & Restore"])

import sys as _sys
if getattr(_sys, "frozen", False):
    # PyInstaller: store backups next to weighbridge.exe
    BACKUP_DIR = Path(_sys.executable).parent / "backups"
else:
    # Source: backend/backups/
    BACKUP_DIR = Path(__file__).parent.parent.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)


# ─── AES-256-GCM backup encryption ───────────────────────────────────────────

def _backup_key() -> bytes:
    hex_key = os.environ.get("PRIVATE_DATA_KEY", "")
    if not hex_key:
        try:
            from app.config import get_settings
            hex_key = get_settings().PRIVATE_DATA_KEY
        except Exception:
            pass
    if not hex_key or len(hex_key) < 64:
        raise RuntimeError("PRIVATE_DATA_KEY not set — cannot encrypt backup")
    return bytes.fromhex(hex_key[:64])


def _encrypt_bytes(data: bytes) -> bytes:
    """Encrypt bytes with AES-256-GCM. Returns nonce(12) + ciphertext+tag."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _backup_key()
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return nonce + ct


def _decrypt_bytes(data: bytes) -> bytes:
    """Decrypt AES-256-GCM payload. Raises on tampering."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _backup_key()
    nonce, ct = data[:12], data[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


def _db_params() -> dict:
    """Parse DATABASE_URL into pg_dump params."""
    import re
    from app.config import get_settings
    settings = get_settings()
    # postgresql+asyncpg://user:pass@host:port/dbname
    m = re.match(
        r"postgresql\+?(?:asyncpg|psycopg)?://([^:@]+):([^@]*)@([^:/]+):?(\d*)/(\S+)",
        settings.DATABASE_URL,
    )
    if not m:
        raise RuntimeError("Cannot parse DATABASE_URL for pg_dump")
    return {"user": m[1], "password": m[2], "host": m[3], "port": m[4] or "5432", "dbname": m[5]}


@router.get("/list")
async def list_backups(
    current_user: User = Depends(require_role("admin")),
):
    """List all available encrypted backup files."""
    files = sorted(BACKUP_DIR.glob("*.sql.enc"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            "encrypted": True,
        }
        for f in files
    ]


@router.post("/create", status_code=201)
async def create_backup(
    current_user: User = Depends(require_role("admin")),
):
    """Run pg_dump, encrypt output with AES-256-GCM, save as .sql.enc file."""
    params = _db_params()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"weighbridge_backup_{ts}.sql.enc"
    filepath = BACKUP_DIR / filename

    env = os.environ.copy()
    env["PGPASSWORD"] = params["password"]

    # Strategy 1: docker exec (pg_dump lives inside the PostgreSQL container)
    # Strategy 2: native pg_dump from PostgreSQL client tools on host
    # Strategy 3: common Windows install paths
    import sys as _sys2
    docker_container = "weighbridge_db"

    async def _try_docker_exec() -> tuple[bytes, int, str]:
        cmd = [
            "docker", "exec",
            "-e", f"PGPASSWORD={params['password']}",
            docker_container,
            "pg_dump",
            "-U", params["user"],
            "-d", params["dbname"],
            "--clean",
            "--if-exists",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        return stdout, proc.returncode, stderr.decode(errors="replace")

    async def _try_native_pgdump() -> tuple[bytes, int, str]:
        # Add common PostgreSQL install paths on Windows
        if _sys2.platform == "win32":
            pg_dirs = [
                r"C:\Program Files\PostgreSQL\17\bin",
                r"C:\Program Files\PostgreSQL\16\bin",
                r"C:\Program Files\PostgreSQL\15\bin",
                r"C:\Program Files\PostgreSQL\14\bin",
            ]
            extra = os.pathsep.join(d for d in pg_dirs if os.path.isdir(d))
            if extra:
                env["PATH"] = extra + os.pathsep + env.get("PATH", "")
        cmd = [
            "pg_dump",
            "-h", params["host"], "-p", params["port"],
            "-U", params["user"], "-d", params["dbname"],
            "--no-password", "--clean", "--if-exists",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        return stdout, proc.returncode, stderr.decode(errors="replace")

    stdout = None
    last_error = ""
    for strategy in [_try_docker_exec, _try_native_pgdump]:
        try:
            out, rc, err = await strategy()
            if rc == 0 and out:
                stdout = out
                break
            last_error = err or f"exit code {rc}"
        except asyncio.TimeoutError:
            raise HTTPException(504, "pg_dump timed out (120s)")
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

    if not stdout:
        raise HTTPException(
            500,
            f"Backup failed: pg_dump not accessible. "
            f"Last error: {last_error[:300]}. "
            "Ensure weighbridge_db Docker container is running."
        )

    # Encrypt in memory before writing to disk
    encrypted = _encrypt_bytes(stdout)
    filepath.write_bytes(encrypted)

    size = filepath.stat().st_size
    return {
        "filename": filename,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "encrypted": True,
        "message": f"Encrypted backup created: {filename}",
    }


@router.get("/download/{filename}")
async def download_backup(
    filename: str,
    current_user: User = Depends(require_role("admin")),
):
    """Download an encrypted backup file (.sql.enc)."""
    if not re.match(r"^weighbridge_backup_[\d_]+\.sql\.enc$", filename):
        raise HTTPException(400, "Invalid filename")
    filepath = BACKUP_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Backup file not found")

    # Stream encrypted bytes — plaintext never sent over network
    data = filepath.read_bytes()
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/restore/{filename}")
async def restore_backup(
    filename: str,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Decrypt backup in memory and restore via psql stdin. ⚠️ Destructive."""
    if not re.match(r"^weighbridge_backup_[\d_]+\.sql\.enc$", filename):
        raise HTTPException(400, "Invalid filename")
    filepath = BACKUP_DIR / filename
    if not filepath.exists():
        raise HTTPException(404, "Backup file not found")

    # Decrypt in memory — never write plaintext to disk
    try:
        sql_bytes = _decrypt_bytes(filepath.read_bytes())
    except Exception:
        raise HTTPException(400, "Failed to decrypt backup — wrong key or tampered file")

    params = _db_params()
    env = os.environ.copy()
    env["PGPASSWORD"] = params["password"]

    cmd = [
        "psql",
        "-h", params["host"],
        "-p", params["port"],
        "-U", params["user"],
        "-d", params["dbname"],
        "--no-password",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(input=sql_bytes), timeout=300)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")
            if "ERROR" in err.upper() and "successfully" not in err.lower():
                raise HTTPException(500, f"psql restore had errors: {err[:500]}")

        return {"message": f"Restore from {filename} completed", "warnings": stderr.decode(errors="replace")[-200:] or None}
    except asyncio.TimeoutError:
        raise HTTPException(504, "Restore timed out (300s)")
    except FileNotFoundError:
        raise HTTPException(500, "psql not found. Ensure PostgreSQL client tools are installed.")


@router.delete("/{filename}", status_code=204)
async def delete_backup(
    filename: str,
    current_user: User = Depends(require_role("admin")),
):
    if not re.match(r"^weighbridge_backup_[\d_]+\.sql\.enc$", filename):
        raise HTTPException(400, "Invalid filename")
    filepath = BACKUP_DIR / filename
    if filepath.exists():
        filepath.unlink()


# ── Cloud Backup Status ─────────────────────────────────────────────────────

import json as _json

@router.get("/cloud-status")
async def cloud_backup_status(
    current_user: User = Depends(require_role("admin")),
):
    """Read backup-status.json written by Backup-ToCloud.ps1 scheduled task."""
    status_file = Path("C:/weighbridge/backup-status.json")

    # Also try relative path for dev
    if not status_file.exists():
        status_file = BACKUP_DIR.parent / "backup-status.json"

    if not status_file.exists():
        return {
            "configured": False,
            "status": "not_configured",
            "message": "Cloud backup not set up. Run Setup-CloudBackup.ps1 to configure.",
        }

    try:
        data = _json.loads(status_file.read_text(encoding="utf-8"))
        # Count total backups in local backup dir with .enc extension
        local_count = len(list(BACKUP_DIR.glob("*.enc")))

        return {
            "configured": True,
            "status": "healthy" if data.get("upload_success") else "error",
            "last_backup": data.get("last_backup"),
            "last_backup_file": data.get("last_backup_file"),
            "last_backup_size": data.get("last_backup_size"),
            "duration_sec": data.get("duration_sec"),
            "upload_success": data.get("upload_success", False),
            "error": data.get("error"),
            "backup_location": data.get("backup_location", ""),
            "next_scheduled": data.get("next_scheduled"),
            "client_id": data.get("client_id", ""),
            "local_backup_count": local_count,
        }
    except Exception as e:
        return {
            "configured": True,
            "status": "error",
            "message": f"Could not read backup status: {str(e)}",
        }
