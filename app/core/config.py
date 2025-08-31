# app/core/config.py

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional, Literal
from urllib.parse import quote


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

# ───────────────────────── FalconEye Receiver ─────────────────────────
class FalconEyeReceiverSettings(Settings):
    IP_ADDRESS_FOR_CAMS: IPvAnyAddress = Field('192.168.1.20')
    RTSP_PORT_FOR_CAMS: int = Field(554, ge=1, le=65535)
    USERNAME_FOR_CAMS: str = Field('admin')
    PASSWORD_FOR_CAMS: SecretStr  # из переменных окружения, .env и т.п.

    # дефолты для параметров потока
    default_channel: int = 2
    default_subtype: int = 0

    def rtsp(self, channel: Optional[int] = None, subtype: Optional[int] = None) -> str:
        """Собирает RTSP-URL. Если channel/subtype не заданы — берём дефолты."""
        ch = self.default_channel if channel is None else channel
        st = self.default_subtype if subtype is None else subtype
        pwd = quote(self.PASSWORD_FOR_CAMS.get_secret_value(), safe="")  # экранируем спецсимволы
        return (
            f"rtsp://{self.USERNAME_FOR_CAMS}:{pwd}@{self.IP_ADDRESS_FOR_CAMS}:{self.RTSP_PORT_FOR_CAMS}"
            f"/cam/realmonitor?channel={ch}&subtype={st}"
        )

    @property
    def default_rtsp(self) -> str:
        """Готовый URL с дефолтными параметрами."""
        return self.rtsp()


# ───────────────────────── FalconEye Cameras ─────────────────────────
class FalconEyeCameraSettings(Settings):
    RTSP_PORT_FOR_CAMS: int = Field(554, ge=1, le=65535)
    USERNAME_FOR_CAMS: str = Field('admin')
    PASSWORD_FOR_CAMS: SecretStr

    IP_ADDRESS_FOR_MAIN_CAM: IPvAnyAddress = Field('192.168.1.10')
    IP_ADDRESS_FOR_SECOND_CAM: IPvAnyAddress = Field('192.168.1.11')

    default_mode: Literal['real', 'replay'] = 'real'
    default_idc: int = 1
    default_ids: int = 1

    def stream(
        self,
        which: Literal['main', 'second'] = 'main',
        mode: Optional[str] = None,
        idc: Optional[int] = None,
        ids: Optional[int] = None,
    ) -> str:
        """Собирает RTSP-URL для основной/второй камеры c дефолтами."""
        mode = self.default_mode if mode is None else mode
        idc = self.default_idc if idc is None else idc
        ids = self.default_ids if ids is None else ids
        ip = self.IP_ADDRESS_FOR_MAIN_CAM if which == 'main' else self.IP_ADDRESS_FOR_SECOND_CAM
        pwd = quote(self.PASSWORD_FOR_CAMS.get_secret_value(), safe="")
        return (
            f"rtsp://{self.USERNAME_FOR_CAMS}:{pwd}@{ip}:{self.RTSP_PORT_FOR_CAMS}"
            f"/stream?mode={mode}&idc={idc}&ids={ids}"
        )

    @property
    def main_default(self) -> str:
        return self.stream('main')

    @property
    def second_default(self) -> str:
        return self.stream('second')



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


@lru_cache
def get_receiver_settings() -> FalconEyeReceiverSettings:
    return FalconEyeReceiverSettings()

@lru_cache
def get_camera_settings() -> FalconEyeCameraSettings:
    return FalconEyeCameraSettings()

@lru_cache
def falcon_eye_receiver_url(channel: Optional[int] = None, subtype: Optional[int] = None) -> str:
    return get_receiver_settings().rtsp(channel=channel, subtype=subtype)


# # дефолтный URL ресивера
# url_default = get_receiver_settings().default_rtsp
#
# # с переопределением параметров
# url_custom = get_receiver_settings().rtsp(channel=1, subtype=1)
#
# # основная камера (дефолты)
# main_url = get_camera_settings().main_default
#
# # вторая камера с изменёнными параметрами
# second_url = get_camera_settings().stream('second', mode='real', idc=2, ids=3)
#
# # через функцию с кэшем (как у тебя)
# recv_url = falcon_eye_receiver_url()             # дефолты
# recv_url2 = falcon_eye_receiver_url(1, 1)        # переопределение