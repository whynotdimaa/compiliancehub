import uuid

from fastapi import APIRouter, HTTPException, status
from jose import JWTError

from app.auth.deps import CurrentUser, PublicSession
from app.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    TenantOut,
    TenantRegisterRequest,
    TokenPair,
    UserOut,
)
from app.auth.service import (
    AuthService,
    InvalidCredentialsError,
    TenantAlreadyExistsError,
)
from app.core.security import decode_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def register_tenant(data: TenantRegisterRequest, session: PublicSession) -> TenantOut:
    try:
        tenant, _ = await AuthService(session).register_tenant(data)
    except TenantAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return TenantOut.model_validate(tenant)


@router.post("/login", response_model=TokenPair)
async def login(data: LoginRequest, session: PublicSession) -> TokenPair:
    try:
        return await AuthService(session).login(data)
    except InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


@router.post("/refresh", response_model=TokenPair)
async def refresh(data: RefreshRequest, session: PublicSession) -> TokenPair:
    try:
        payload = decode_token(data.refresh_token, expected_type="refresh")
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    return await AuthService(session).refresh(user_id, tenant_id)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
