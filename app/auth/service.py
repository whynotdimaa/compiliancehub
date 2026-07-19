import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import LoginRequest, TenantRegisterRequest, TokenPair
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.tenants.models import Tenant, User, UserRole


class AuthError(Exception):
    pass


class TenantAlreadyExistsError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register_tenant(self, data: TenantRegisterRequest) -> tuple[Tenant, User]:
        existing = await self._session.scalar(
            select(Tenant).where(
                (Tenant.slug == data.tenant_slug) | (Tenant.name == data.tenant_name)
            )
        )
        if existing is not None:
            raise TenantAlreadyExistsError(f"Tenant '{data.tenant_slug}' already exists")

        tenant = Tenant(name=data.tenant_name, slug=data.tenant_slug)
        self._session.add(tenant)
        await self._session.flush()

        admin = User(
            tenant_id=tenant.id,
            email=data.admin_email.lower(),
            hashed_password=hash_password(data.admin_password),
            full_name=data.admin_full_name,
            role=UserRole.ADMIN,
        )
        self._session.add(admin)
        await self._session.commit()
        await self._session.refresh(tenant)
        await self._session.refresh(admin)
        return tenant, admin

    async def login(self, data: LoginRequest) -> TokenPair:
        user = await self._session.scalar(
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(Tenant.slug == data.tenant_slug, User.email == data.email.lower())
        )
        if user is None or not verify_password(data.password, user.hashed_password):
            raise InvalidCredentialsError("Invalid credentials")

        return TokenPair(
            access_token=create_access_token(user.id, user.tenant_id),
            refresh_token=create_refresh_token(user.id, user.tenant_id),
        )

    async def refresh(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user_id, tenant_id),
            refresh_token=create_refresh_token(user_id, tenant_id),
        )
