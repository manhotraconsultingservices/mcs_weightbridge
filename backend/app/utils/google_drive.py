"""Google Drive storage utilities for camera snapshots."""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _build_service(credentials_json: dict):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(
        credentials_json,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_image(credentials_json: dict, folder_id: str, filename: str, image_bytes: bytes) -> str:
    """Upload JPEG to Google Drive folder. Returns public view URL."""
    from googleapiclient.http import MediaInMemoryUpload

    service = _build_service(credentials_json)
    metadata = {"name": filename, "parents": [folder_id]}
    media = MediaInMemoryUpload(image_bytes, mimetype="image/jpeg")
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    file_id = file["id"]

    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return f"https://drive.google.com/uc?export=view&id={file_id}"


def list_old_files(credentials_json: dict, folder_id: str, older_than_days: int = 90) -> list:
    """Return all files in folder older than N days."""
    service = _build_service(credentials_json)
    cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and createdTime < '{cutoff}' and trashed = false",
            fields="nextPageToken, files(id, name, createdTime)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def move_to_folder(credentials_json: dict, file_id: str, new_folder_id: str, old_folder_id: str):
    """Move a file from one Drive folder to another."""
    service = _build_service(credentials_json)
    service.files().update(
        fileId=file_id,
        addParents=new_folder_id,
        removeParents=old_folder_id,
        fields="id",
    ).execute()


def delete_file(credentials_json: dict, file_id: str):
    """Permanently delete a file from Google Drive."""
    service = _build_service(credentials_json)
    service.files().delete(fileId=file_id).execute()


def test_connection(credentials_json: dict, folder_id: str) -> tuple:
    """Returns (success: bool, message: str)."""
    try:
        service = _build_service(credentials_json)
        folder = service.files().get(fileId=folder_id, fields="id, name").execute()
        return True, f"Connected to folder '{folder.get('name', folder_id)}'"
    except Exception as exc:
        return False, str(exc)
