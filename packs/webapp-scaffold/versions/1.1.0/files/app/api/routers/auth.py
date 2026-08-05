"""Auth endpoints: login, logout, me, password change, API key management."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import (
    get_user_by_email,
    verify_password,
    hash_password,
    create_session,
    delete_session,
    get_user_orgs,
    update_password,
    generate_api_key,
    set_api_key,
    get_user_api_key,
    SESSION_EXPIRY_DAYS,
)
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate and create a session."""
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=401,
            detail={"code": "ERR_INVALID_CREDENTIALS", "message": "Invalid email or password"},
        )

    session_id = create_session(user["id"])

    response = JSONResponse(
        content={
            "status": "ok",
            "data": {
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "name": user["name"],
                    "role": user["role"],
                },
                "session_id": session_id,
            },
        }
    )
    response.set_cookie(
        key="{{project_name}}_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_EXPIRY_DAYS * 86400,
    )
    return response


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """Destroy session and clear cookie."""
    session_id = request.cookies.get("{{project_name}}_session")
    if session_id:
        delete_session(session_id)

    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key="{{project_name}}_session", path="/")
    return response


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return current user info with org memberships."""
    orgs = get_user_orgs(user["id"])
    return {
        "status": "ok",
        "data": {
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
                "orgs": orgs,
            },
        },
    }


@router.put("/password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """Change the current user's password."""
    # Verify current password
    full_user = get_user_by_email(user["email"])
    if not full_user or not verify_password(body.current_password, full_user["password_hash"]):
        raise HTTPException(
            status_code=400,
            detail={"code": "ERR_WRONG_PASSWORD", "message": "Current password is incorrect"},
        )

    # Validate new password
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail={"code": "ERR_WEAK_PASSWORD", "message": "New password must be at least 8 characters"},
        )

    update_password(user["id"], hash_password(body.new_password))
    return {"status": "ok", "data": {"message": "Password updated successfully"}}


@router.get("/api-key")
async def get_api_key(user: dict = Depends(get_current_user)):
    """Get the current user's API key (masked) or null if not set."""
    key = get_user_api_key(user["id"])
    return {
        "status": "ok",
        "data": {
            "api_key": key,
            "masked": _mask_key(key) if key else None,
        },
    }


@router.post("/api-key")
async def regenerate_api_key(user: dict = Depends(get_current_user)):
    """Generate (or regenerate) an API key for the current user.

    Returns the full key — this is the only time the full key is shown.
    """
    new_key = generate_api_key()
    set_api_key(user["id"], new_key)
    return {
        "status": "ok",
        "data": {
            "api_key": new_key,
            "message": "API key generated. Store it securely — it won't be shown in full again.",
        },
    }


def _mask_key(key: str) -> str:
    """Mask an API key, showing only the prefix and last 4 chars."""
    if len(key) <= 12:
        return key[:4] + "..." + key[-2:]
    return key[:8] + "..." + key[-4:]
