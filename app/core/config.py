# app/core/config.py

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import EmailStr, SecretStr
from pydantic_settings import BaseSettings

BASE_PATH = Path(__file__).resolve().parent.parent.parent


class TypeNetwork(str, Enum):
    LOCAL = "local"
    SERVER = "server"

class TypeServer(str, Enum):
    DEVELOPMENT = "dev"
    PRODUCTION = "prod"
    TESTING = "test"

class Settings(BaseSettings):
    class Config:
        env_file = BASE_PATH / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

class AppMetaSettings(Settings):
    TYPE_NETWORK: str = TypeNetwork.LOCAL
    TYPE_SERVER: str = TypeServer.DEVELOPMENT

class CorsSettings(Settings):
    CORS_ALLOWED_ORIGINS: set[str] = {
        "http://localhost:5173",
        "https://beahea.ru",
    }
    VALID_USER_AGENTS: list[str] = [
        r"Chrome/\d+\.\d+\.\d+\.\d+",
        r"Firefox/\d+\.\d+",
        r"Safari/\d+\.\d+",
        r"Mobile Safari/\d+\.\d+",
        r"OPR/\d+\.\d+",
        r"Edge/\d+\.\d+",
        r"EdgA/\d+\.\d+",
        r"SamsungBrowser/\d+\.\d+",
    ]

class UrlsToServices(Settings):
    BASE_USER_API_URL: str

class IPsToServices(Settings):
    BASE_USER_API_IP: str

class ApiTokens(Settings):
    TOKEN_ACCESS_SECRET_KEY: SecretStr
    TOKEN_REFRESH_SECRET_KEY: SecretStr
    TOKEN_STREAM_SECRET_KEY: SecretStr
    TOKEN_PEPPER_SECRET_KEY: SecretStr
    ALGORITHM: str = "HS256"

class ProjectPathSettings(Settings):
    BASE_LOGS_PATH: Path = BASE_PATH / "logs"
    BASE_STATIC_PATH: Path = BASE_PATH / "app/frontend/static"
    BASE_TEMPLATES_PATH: Path = BASE_PATH / "app/frontend/templates"
    BASE_PHOTO_PATH: Path = BASE_PATH / "imgs"

    @property
    def static_mounts(self) -> dict[str, Path]:
        return {
            "static": self.BASE_STATIC_PATH,
            "imgs": self.BASE_PHOTO_PATH,
            "logs": self.BASE_LOGS_PATH,
        }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.BASE_LOGS_PATH.mkdir(parents=True, exist_ok=True)
        self.BASE_STATIC_PATH.mkdir(parents=True, exist_ok=True)
        self.BASE_PHOTO_PATH.mkdir(parents=True, exist_ok=True)

class PstgrUserBaseSettings(Settings):
    USER_PSTGR_USER: str
    USER_PSTGR_PASS: SecretStr
    USER_PSTGR_NAME: str
    USER_PSTGR_HOST: str
    USER_PSTGR_PORT: int

    @property
    def async_user_pstgr_url(self) -> str:
        return f"postgresql+asyncpg://{self.USER_PSTGR_USER}:{self.USER_PSTGR_PASS.get_secret_value()}@{self.USER_PSTGR_HOST}:{self.USER_PSTGR_PORT}/{self.USER_PSTGR_NAME}"

    @property
    def sync_user_pstgr_url(self) -> str:
        return f"postgresql://{self.USER_PSTGR_USER}:{self.USER_PSTGR_PASS.get_secret_value()}@{self.USER_PSTGR_HOST}:{self.USER_PSTGR_PORT}/{self.USER_PSTGR_NAME}"

class RabbitMqSetting(Settings):
    RABBITMQ_USER: str
    RABBITMQ_PASS: SecretStr
    RABBITMQ_HOST: str
    RABBITMQ_PORT: int

    @property
    def rabbitmq_broker_url(self) -> str:
        return f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASS.get_secret_value()}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/"

class RedisSetting(Settings):
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASS: SecretStr
    REDIS_BAN_LIST_INDEX: int
    REDIS_USER_INDEX: int

    @property
    def redis_ban_list_url(self) -> str:
        return f"redis://:{self.REDIS_PASS.get_secret_value()}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_BAN_LIST_INDEX}"

class S3StorageConfig(Settings):
    MINIO_USER: str
    MINIO_PASS: SecretStr
    MINIO_HOST: str
    MINIO_PORT: int
    MINIO_USER_BASKET_NAME: str = 'user'
    BASE_PHOTO_PATH: Path = BASE_PATH / "imgs"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.BASE_PHOTO_PATH.mkdir(parents=True, exist_ok=True)

class UserFlowerSettings(Settings):
    USER_FLOWER_LOGIN: str
    USER_FLOWER_PASSWORD: SecretStr

class MailSenderConfig(Settings):
    MAIL_USERNAME: EmailStr
    MAIL_PASSWORD: SecretStr
    MAIL_SERVER: str
    MAIL_PORT: int

class FalconEyeResiverSettings(Settings):
    IP_ADDRESS: str = '192.168.1.20'
    PORT_ADDRESS: int = 554
    USERNAME_CAMERAS: str = 'admin'
    PASSWORD_CAMERAS: str

    @property
    def cam_stream(self, num_cam: int = 2, subtype: int = 0) -> str:
        return f'rtsp://{self.USERNAME}:{self.PASSWORD}@{self.IP_ADRESS}:{self.PORT_ADRESS}/cam/realmonitor?channel={num_cam}&subtype={subtype}'


class FalconEyeMainCameraSettings(Settings):
    PORT_ADDRESS: int = 554
    USERNAME_CAMERAS: str = 'admin'
    PASSWORD_CAMERAS: str

    @property
    def main_cam_stream(self, mode: str = 'real', idc: int = 1, ids: int = 1) -> str:
        return f"rtsp://{self.USERNAME}:{self.PASSWORD}@192.168.1.10:{self.PORT_ADRESS}/stream?mode={mode}&idc={idc}&ids={ids}"

    @property
    def second_cam_stream(self, mode: str = 'real', idc: int = 1, ids: int = 1) -> str:
        return f"rtsp://{self.USERNAME}:{self.PASSWORD}@192.168.1.10:{self.PORT_ADRESS}/stream?mode={mode}&idc={idc}&ids={ids}"


# Lazy обёртки{self.IP_ADDRESS}
@lru_cache()
def get_app_settings() -> AppMetaSettings:
    return AppMetaSettings()


@lru_cache()
def get_cors_settings() -> CorsSettings:
    return CorsSettings()


@lru_cache()
def get_api_tokens() -> ApiTokens:
    return ApiTokens()


@lru_cache()
def get_project_path_settings() -> ProjectPathSettings:
    return ProjectPathSettings()


@lru_cache()
def get_pstgr_settings() -> PstgrUserBaseSettings:
    return PstgrUserBaseSettings()


@lru_cache()
def get_rabbitmq_settings() -> RabbitMqSetting:
    return RabbitMqSetting()


@lru_cache()
def get_redis_settings() -> RedisSetting:
    return RedisSetting()


@lru_cache()
def get_mail_sender_config() -> MailSenderConfig:
    return MailSenderConfig()


@lru_cache()
def get_urls_to_services() -> UrlsToServices:
    return UrlsToServices()


@lru_cache()
def get_s3_storage_config() -> S3StorageConfig:
    return S3StorageConfig()


@lru_cache()
def get_ips_to_services() -> IPsToServices:
    return IPsToServices()


@lru_cache()
def get_user_flower_settings() -> UserFlowerSettings:
    return UserFlowerSettings()


@lru_cache()
def get_bit_by_bit_config() -> ProjectPathSettings:
    return ProjectPathSettings()


@lru_cache()
def access_token_env() -> str:
    return ApiTokens().TOKEN_ACCESS_SECRET_KEY.get_secret_value()


@lru_cache()
def refresh_token_env() -> str:
    return ApiTokens().TOKEN_REFRESH_SECRET_KEY.get_secret_value()

@lru_cache()
def pepper_token_env() -> str:
    return ApiTokens().TOKEN_PEPPER_SECRET_KEY.get_secret_value()


@lru_cache()
def stream_token_env() -> str:
    return ApiTokens().TOKEN_STREAM_SECRET_KEY.get_secret_value()


@lru_cache()
def algorithm_env() -> str:
    return ApiTokens().ALGORITHM


@lru_cache()
def base_api_user_url() -> str:
    return UrlsToServices().BASE_USER_API_URL


@lru_cache()
def base_photo_path() -> Path:
    return ProjectPathSettings().BASE_PHOTO_PATH
