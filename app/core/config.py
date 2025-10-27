# app/core/config.py

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import List


from pydantic import EmailStr, SecretStr, IPvAnyAddress, Field
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
    
    @property
    def get_debug_mode(self) -> bool:
        return self.TYPE_NETWORK == TypeNetwork.LOCAL

class ChatIdsConfig(Settings):
    CHAT_ID: int
    STATIC_ADMIN_LIST: str

    @property
    def admin_ids(self) -> List[int]:
        return [int(admin_id) for admin_id in self.STATIC_ADMIN_LIST.split(' ')]

class WebhookSettings(Settings):
    WEBHOOK_PATH: str = "/updates"
    WEBHOOK_URL: str = "https://beahea.ru/api/tg-bot"

    @property
    def webhook_full_path(self) -> str:
        return f"{self.WEBHOOK_URL}{self.WEBHOOK_PATH}"

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

class TokensConfig(Settings):
    TOKEN_ACCESS_SECRET_KEY: SecretStr
    TOKEN_REFRESH_SECRET_KEY: SecretStr
    TOKEN_STREAM_SECRET_KEY: SecretStr
    TOKEN_PEPPER_SECRET_KEY: SecretStr
    WEBHOOK_SECRET_KEY: SecretStr
    TELEGRAM_TOKEN: SecretStr
    ALGORITHM: str = "HS256"

class ProjectPathSettings(Settings):
    BASE_LOGS_PATH: Path = BASE_PATH / "logs"
    BASE_STATIC_PATH: Path = BASE_PATH / "app/frontend/static"
    BASE_TEMPLATES_PATH: Path = BASE_PATH / "app/frontend/templates"
    BASE_PHOTO_PATH: Path = BASE_PATH / "imgs"
    FSM_STORAGE_PATH: Path = BASE_PATH / "bot/fsm-storage"


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

class DebugFlags(Settings):
    """
    Флаги отладки. Удобно включать/выключать через .env:
      ONVIF_DEBUG=true/false
      FFPROXY_DEBUG=true/false
      GRABBER_DEBUG=true/false
      UI_DEBUG=true/false
    """
    ONVIF_DEBUG: bool = False      # печать HTTP/Soap сниппетов для ONVIF
    FFPROXY_DEBUG: bool = False    # печать stderr ffmpeg и причины таймаутов
    GRABBER_DEBUG: bool = False    # подробные логи граббера (кадры/переключения)
    UI_DEBUG: bool = False         # будущие отладочные метки UI


class VideoTuning(Settings):
    """
    Технические параметры для видео-подсистемы (прокси и т.п.)
    Можно править в .env, например:
      FFPROXY_LISTEN_TIMEOUT_S=12
      FFPROXY_BASE_PORT=8554
    """
    FFPROXY_LISTEN_TIMEOUT_S: float = 12.0   # сколько ждать поднятия RTSP-листенера
    FFPROXY_BASE_PORT: int = 8554            # базовый порт для RTSP-прокси


class OnvifSettings(Settings):
    ONVIF_ENABLE: bool = True   # по умолчанию ONVIF включен

@lru_cache()
def get_onvif_settings() -> OnvifSettings:
    return OnvifSettings()

@lru_cache()
def get_debug_flags() -> DebugFlags:
    return DebugFlags()

@lru_cache()
def get_video_tuning() -> VideoTuning:
    return VideoTuning()

@lru_cache()
def debug_mode() -> bool:
    return AppMetaSettings().get_debug_mode

@lru_cache()
def webhooks_full_path() -> str:
    return WebhookSettings().webhook_full_path

@lru_cache()
def webhook_path() -> str:
    return WebhookSettings().WEBHOOK_PATH


@lru_cache()
def get_app_settings() -> AppMetaSettings:
    return AppMetaSettings()


@lru_cache()
def get_cors_settings() -> CorsSettings:
    return CorsSettings()


@lru_cache()
def get_api_tokens() -> TokensConfig:
    return TokensConfig()


@lru_cache()
def get_projects_path() -> ProjectPathSettings:
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
    return TokensConfig().TOKEN_ACCESS_SECRET_KEY.get_secret_value()


@lru_cache()
def refresh_token_env() -> str:
    return TokensConfig().TOKEN_REFRESH_SECRET_KEY.get_secret_value()

@lru_cache()
def pepper_token_env() -> str:
    return TokensConfig().TOKEN_PEPPER_SECRET_KEY.get_secret_value()


@lru_cache()
def stream_token_env() -> str:
    return TokensConfig().TOKEN_STREAM_SECRET_KEY.get_secret_value()

@lru_cache()
def bot_token_env() -> str:
    return TokensConfig().TELEGRAM_TOKEN.get_secret_value()

@lru_cache()
def webhook_token_env() -> str:
    return TokensConfig().WEBHOOK_SECRET_KEY.get_secret_value()

@lru_cache()
def algorithm_env() -> str:
    return TokensConfig().ALGORITHM


@lru_cache()
def base_api_user_url() -> str:
    return UrlsToServices().BASE_USER_API_URL


@lru_cache()
def base_photo_path() -> Path:
    return ProjectPathSettings().BASE_PHOTO_PATH


@lru_cache()
def developer_chat_id() -> int:
    return ChatIdsConfig().CHAT_ID

@lru_cache()
def get_admin_ids() -> List[int]:
    return ChatIdsConfig().admin_ids

@lru_cache()
def get_mail_config() -> MailSenderConfig:
    return MailSenderConfig()
