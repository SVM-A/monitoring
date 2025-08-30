from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint, BigInteger, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base_sql import BaseSQL
from app.db.models.enums import RoleEnum

if TYPE_CHECKING:
     from app.db.models.tables import User, Role


class UserRole(BaseSQL):

    __tablename__ = 'user_role_association'
    __table_args__ = (
        UniqueConstraint('user_id', 'role_name', name='uq_user_role'),
    )

    user_id: Mapped[int] = mapped_column(BigInteger,
                                             ForeignKey("users.id", ondelete="CASCADE"))
    role_name: Mapped[RoleEnum] = mapped_column(SqlEnum(RoleEnum, name="role_enum"),
                                              ForeignKey("roles.name", ondelete="CASCADE"))
    user: Mapped['User'] = relationship(back_populates='roles_assoc')
    role: Mapped['Role'] = relationship(back_populates='users_assoc')

