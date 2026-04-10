"""
License status endpoint.

Provides a public (no-auth) endpoint for the frontend to check license
validity and display appropriate UI (expired page vs normal app).
"""

from fastapi import APIRouter

from app.services.license import get_license_status

router = APIRouter(prefix="/api/v1/license", tags=["License"])


@router.get("/status")
async def license_status():
    """
    Returns current license status. No authentication required so the
    frontend can show the license-expired page even when the user is
    not logged in.
    """
    return get_license_status()
