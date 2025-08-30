import secrets
from datetime import datetime, UTC, timedelta, timezone
from typing import List, TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, ForeignKey, Enum as SqlEnum, TIMESTAMP, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.models.enums import RoleEnum, GenderEnum, TokenTypeEnum
from app.db.models.base_sql import (BaseSQL, AbstractBaseSQL,
                                    str_1000_null_false, expires_at, str_255_uniq_null_true,
                                    str_255_uniq_null_false, bool_false, str_255_null_false)
from app.utils.http_exceptions import ValidErrorException

if TYPE_CHECKING:
    from app.db.models.associations import UserRole



class User(BaseSQL):
    __tablename__ = 'users'

    phone_number: Mapped[str_255_uniq_null_true] # type: ignore
    email: Mapped[str_255_uniq_null_false] # type: ignore
    password: Mapped[str]
    is_banned: Mapped[bool_false]  # type: ignore
    is_email_confirmed: Mapped[bool_false] # type: ignore
    is_phone_confirmed: Mapped[bool_false] # type: ignore
    ban_until: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_login_attempt: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(default=0)

    profile_id: Mapped[int | None] = mapped_column(ForeignKey('profiles.id'))
    profile: Mapped["Profile"] = relationship(
        "Profile",
        uselist=False,
        lazy="selectin",
        passive_deletes=True,
        back_populates="user",
    )


    roles_assoc: Mapped[List['UserRole']] = relationship(
        "UserRole",
        cascade="all, delete-orphan",
        lazy="selectin",
        back_populates='user',
    )

    refresh_token_assoc: Mapped[List["Token"]] = relationship(
        "Token",
        uselist=True,
        cascade="all, delete-orphan",
        back_populates="user",
        foreign_keys="[Token.user_id]",
    )

    @property
    def is_expired(self):
        return datetime.now(UTC) > self.ban_until

    def __post_init__(self):
        if self.is_expired:
            self.is_banned = False

    @property
    def roles(self):
        return [user_role.role_name for user_role in self.roles_assoc]

    @property
    def refresh_token(self):
        for token in self.refresh_token_assoc:
            if not token.ban and token.token_type == TokenTypeEnum.REFRESH:
                return token.token
        else:
            return None

    def __repr__(self):
        ban_info = f", ban_until={self.ban_until.strftime('%Y-%m-%d %H:%M:%S')}" if self.ban_until else ""
        return f"{self.__class__.__name__}(id={self.id}, is_banned={self.is_banned}{ban_info})"


class Token(BaseSQL):
    __tablename__ = 'tokens'

    token: Mapped[str_1000_null_false] = mapped_column(unique=True) # type: ignore
    token_type: Mapped[TokenTypeEnum] = mapped_column(SqlEnum(TokenTypeEnum, name="token_type_enum"),
                                                      nullable=False, comment="Тип токена: ACCESS или REFRESH")
    expires_at: Mapped[expires_at] # type: ignore
    ban: Mapped[bool_false] # type: ignore
    issued_by_admin_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"),
                                                           comment="ID администратора, использовавшего токен")

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user: Mapped['User'] = relationship(
        "User",
        lazy="selectin",
        back_populates="refresh_token_assoc",
        foreign_keys="[Token.user_id]",
    )


    @property
    def is_expired(self):
        return datetime.now(UTC) > self.expires_at

    def __post_init__(self):
        if self.is_expired:
            self.ban = True

    def __repr__(self):
        title_id = f'user_id={self.user_id}'
        adm = f', issued_by_admin_id={self.issued_by_admin_id}' if self.issued_by_admin_id else ''
        return f"{self.__class__.__name__}({title_id}, expires_at={self.expires_at}, ban={self.ban}{adm})"


class Profile(BaseSQL):
    __tablename__ = 'profiles'

    first_name: Mapped[str | None]
    last_name: Mapped[str | None]
    data_birth: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    gender: Mapped[GenderEnum] = mapped_column(SqlEnum(GenderEnum, name="gender_enum"), nullable=False,
                                               default=GenderEnum.NOT_SPECIFIED, comment="Пол пользователя")

    avatar: Mapped[Optional["Avatar"]] = relationship(
        "Avatar",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
        back_populates="profile",
    )

    user: Mapped["User"] = relationship(
        "User",
        uselist=False,
        lazy="selectin",
        passive_deletes=True,
        back_populates="profile"
    )

    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}"

class Avatar(BaseSQL):
    __tablename__ = 'avatars'

    orig_photo: Mapped[str_255_null_false]
    preview_photo: Mapped[str_255_null_false]

    profile_id = mapped_column(ForeignKey('profiles.id', ondelete='CASCADE'), nullable=False)
    profile = relationship(
        "Profile",
        uselist=False,
        lazy="selectin",
        back_populates="avatar",
    )

    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id})"


class Role(AbstractBaseSQL):
    __tablename__ = 'roles'

    name: Mapped[RoleEnum] = mapped_column(SqlEnum(RoleEnum, name="role_enum"), primary_key=True, unique=True)
    users_assoc: Mapped[List['UserRole']] = relationship(
        "UserRole",
        back_populates="role"
    )

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name})"


class EmailVerificationToken(BaseSQL):
    __tablename__ = 'email_verification_tokens'

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str_255_uniq_null_false] # type: ignore
    ban: Mapped[bool_false] # type: ignore
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


    def __init__(self, email: str, **kw: Any):
        super().__init__(**kw)
        self.email = email
        self.token = secrets.token_urlsafe(32)  # Генерация уникального токена
        self.expires_at = datetime.now(timezone.utc) + timedelta(days=30)


    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}"


class ChangeEmailVerificationToken(BaseSQL):
    __tablename__ = 'change_email_verification_tokens'

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str_255_uniq_null_false] # type: ignore
    ban: Mapped[bool_false] # type: ignore
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


    def __init__(self, email: str, **kw: Any) -> None:
        super().__init__(**kw)
        self.email = email
        self.token = secrets.token_urlsafe(32)  # Генерация уникального токена
        self.expires_at = datetime.now(timezone.utc) + timedelta(days=30)


    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}"

class ResetPasswordToken(BaseSQL):
    __tablename__ = 'reset_password_tokens'

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str_255_uniq_null_false] # type: ignore
    ban: Mapped[bool_false] # type: ignore
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


    def __init__(self, email: str, **kw: Any):
        super().__init__(**kw)
        self.email = email
        self.token = secrets.token_urlsafe(32)  # Генерация уникального токена
        self.expires_at = datetime.now(timezone.utc) + timedelta(days=30)


    def __repr__(self):
        return f"{self.__class__.__name__}(id={self.id}"


