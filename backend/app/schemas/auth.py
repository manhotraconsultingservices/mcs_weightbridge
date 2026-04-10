import uuid
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str = "operator"


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str | None
    email: str | None
    phone: str | None
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str
