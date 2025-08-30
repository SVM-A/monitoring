from datetime import timedelta
from enum import Enum


class RoleEnum(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    SYSADMIN = "SYSADMIN"
    MODERATOR = "MODERATOR"
    MANAGER = "MANAGER"
    SUPPORT = "SUPPORT"
    DEVELOPER = "DEVELOPER"

class GenderEnum(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NOT_SPECIFIED = "NOT_SPECIFIED"


class StatusPost(str, Enum):
    PUBLISHED = "опубликован"
    DELETED = "удален"
    UNDER_MODERATION = "на модерации"
    DRAFT = "черновик"
    SCHEDULED = "отложенная публикация"

class TokenTypeEnum(str, Enum):
    ACCESS = "ACCESS"
    REFRESH = "REFRESH"


class BanTimeEnum(str, Enum):
    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"
    FOREVER = "FOREVER"

    @property
    def duration(self) -> timedelta:
        durations = {
            BanTimeEnum.HOUR: timedelta(hours=1),
            BanTimeEnum.DAY: timedelta(days=1),
            BanTimeEnum.WEEK: timedelta(weeks=1),
            BanTimeEnum.MONTH: timedelta(days=30),
            BanTimeEnum.YEAR: timedelta(days=365),
            BanTimeEnum.FOREVER: timedelta(days=365 * 100),
        }
        return durations[self]