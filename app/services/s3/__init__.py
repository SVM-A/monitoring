from functools import lru_cache
from app.utils.logger import logger
from minio import Minio

from app.core.config import get_s3_storage_config

class S3Client:
    """
    🧰 Асинхронный клиент для работы с S3 (MinIO) или локальной файловой системой.

    📌 Используется для:
    - загрузки оригинала и превью изображений;
    - валидации и преобразования изображений;
    - получения или удаления файлов;

    🔁 Выбор между S3 и локальным хранилищем регулируется флагом `use_s3`.
    """

    def __init__(self, use_s3: bool = True):
        """
        🔧 Инициализация клиента: создаётся экземпляр MinIO или активируется локальный режим.
        """
        self.use_s3 = use_s3
        endpoint = (
            f"{get_s3_storage_config().MINIO_HOST}:{get_s3_storage_config().MINIO_PORT}"
        )
        self.client = Minio(
            endpoint,
            access_key=get_s3_storage_config().MINIO_USER,
            secret_key=get_s3_storage_config().MINIO_PASS.get_secret_value(),
            secure=False,
        )

        self.bucket_name = get_s3_storage_config().MINIO_USER_BASKET_NAME
        logger.info(
            f"S3Client инициализирован с endpoint: {endpoint}, bucket: {self.bucket_name}, use_s3: {self.use_s3}"
        )


@lru_cache
def get_s3_client() -> S3Client:
    return S3Client()