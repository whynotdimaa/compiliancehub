import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session, get_tenant_session
from app.core.security import decode_token
from app.core.tenant_context import current_tenant_id
from app.tenants.models import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticatedUser:
    """Lightweight identity extracted from JWT (no DB hit)."""

    def __init__(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id


async def get_token_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    """Validate JWT and bind the tenant into the request context (RLS)."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc

    current_tenant_id.set(tenant_id)
    return AuthenticatedUser(user_id=user_id, tenant_id=tenant_id)


TokenIdentity = Annotated[AuthenticatedUser, Depends(get_token_identity)]
# NB: get_tenant_session depends on the tenant context set above,
# so TokenIdentity must appear before TenantSession in endpoint signatures.
TenantSession = Annotated[AsyncSession, Depends(get_tenant_session)]
PublicSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(identity: TokenIdentity, session: TenantSession) -> User:
    user = await session.scalar(select(User).where(User.id == identity.user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole):
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker
