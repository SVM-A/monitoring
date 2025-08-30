import asyncio
import mimetypes
import os
from datetime import datetime
from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from app.utils.logger import logger
from minio.error import S3Error
from PIL import Image, UnidentifiedImageError

from app.core.config import base_photo_path
from app.services.s3 import get_s3_client

s3client = get_s3_client()


async def validate_image_file(file_buffer: bytes, filename: str) -> bool:
    """
    🧐 Проверка, что файл является допустимым изображением (и не превышает 10 МБ).
    """
    size_mb = len(file_buffer) / (1024 * 1024)
    logger.info(f"Проверка файла {filename}, размер: {size_mb:.2f} MB")
    if size_mb > 10:
        logger.warning(f"Файл {filename} превышает лимит 10 МБ")
        return False
    try:
        await asyncio.to_thread(lambda: Image.open(BytesIO(file_buffer)).verify())
        logger.info(f"Файл {filename} - изображение")
        return True
    except UnidentifiedImageError:
        logger.warning(f"Файл {filename} не является изображением")
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке файла {filename}: {e}")
        return False


async def convert_to_webp(file_buffer: bytes, quality: int = 80) -> bytes:
    """
    🔄 Конвертация изображения в формат WebP с заданным качеством.
    """
    logger.info("Начало конвертации в WebP")
    try:

        def _convert():
            with Image.open(BytesIO(file_buffer)) as img:
                img = img.convert("RGB")
                output = BytesIO()
                img.save(output, format="WEBP", quality=quality)
                return output.getvalue()

        webp_bytes = await asyncio.to_thread(_convert)
        logger.info(f"Конвертация завершена. Размер: {len(webp_bytes)/1024:.2f} KB")
        return webp_bytes
    except Exception as e:
        logger.error(f"Ошибка при конвертации: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при конвертации в WebP")


async def resize_and_crop(image: Image.Image, min_side=64) -> Image.Image:
    """
    ✂️ Масштабирование изображения с сохранением пропорций по минимальной стороне.
    """
    logger.info("Уменьшение изображения")
    try:
        width, height = image.size
        scale = min_side / min(width, height)
        new_size = (int(width * scale), int(height * scale))
        resized_image = await asyncio.to_thread(
            lambda: image.resize(new_size, Image.Resampling.LANCZOS)
        )
        logger.info(f"Изображение уменьшено до: {new_size}")
        return resized_image
    except Exception as e:
        logger.error(f"Ошибка при уменьшении: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при уменьшении изображения")


async def upload_and_prepare_images(
    photo_id: str, orig_file_buffer: bytes, date: datetime, object_type: str = 'avatar'
) -> tuple[str, str]:
    """
    📤 Подготовка и загрузка изображения:
    - конвертация оригинала;
    - создание превью;
    - загрузка в S3 или локально.
    """
    logger.info(f"Подготовка и загрузка изображения: {photo_id}")
    try:
        orig_webp_bytes = await convert_to_webp(orig_file_buffer)
        with Image.open(BytesIO(orig_file_buffer)) as img:
            img = img.convert("RGB")
            preview_img = await resize_and_crop(img)
            output = BytesIO()
            await asyncio.to_thread(preview_img.save, output, "WEBP", quality=80)
            preview_webp_bytes = output.getvalue()
            logger.info("Превью успешно создано")

        # Оборачиваем в BytesIO, чтобы передать в upload_photo_and_preview
        orig_stream = BytesIO(orig_webp_bytes)
        preview_stream = BytesIO(preview_webp_bytes)

        if s3client.use_s3:
            return await upload_photo_and_preview(
                photo_id, orig_stream, preview_stream, date, object_type
            )
        else:
            return await local_upload_photo_and_preview(
                photo_id, orig_stream, preview_stream, date, object_type
            )

    except HTTPException as e:
        logger.error(f"HTTPException: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Ошибка при подготовке и загрузке: {e}")
        raise HTTPException(
            status_code=500, detail="Неизвестная ошибка при подготовке и загрузке"
        )


async def upload_photo_and_preview(
    photo_id: str, orig_stream: BytesIO, preview_stream: BytesIO, date: datetime, object_type: str
) -> tuple[str, str]:
    """
    ⬆️ Загрузка оригинального изображения и превью в S3-хранилище.
    """
    logger.info("Загрузка файлов в S3")
    date_str = date.strftime("%Y-%m-%d")
    orig_key = f"{object_type}/{date_str}/{photo_id}/orig.webp"
    preview_key = f"{object_type}/{date_str}/{photo_id}/preview.webp"

    try:
        orig_stream.seek(0)
        await asyncio.to_thread(
            s3client.client.put_object,
            s3client.bucket_name,
            orig_key,
            orig_stream,
            orig_stream.getbuffer().nbytes,
            "image/webp",
        )
        logger.info(f"Оригинальное изображение {orig_key} успешно загружено в S3")
    except S3Error as e:
        logger.error(f"S3Error при загрузке {orig_key}: {e}")
        raise HTTPException(status_code=500, detail=f"S3 ошибка: {e.code}")
    except Exception as e:
        logger.error(f"Ошибка при загрузке {orig_key}: {e}")
        raise HTTPException(
            status_code=500, detail="Ошибка при загрузке оригинала в S3"
        )

    try:
        orig_stream.seek(0)
        await asyncio.to_thread(
            s3client.client.put_object,
            s3client.bucket_name,
            preview_key,
            preview_stream,
            preview_stream.getbuffer().nbytes,
            "image/webp",
        )
        logger.info(f"Превью {preview_key} успешно загружено в S3")
    except S3Error as e:
        logger.error(f"S3Error при загрузке превью {preview_key}: {e}")
        raise HTTPException(status_code=500, detail=f"S3 ошибка: {e.code}")
    except Exception as e:
        logger.error(f"Ошибка при загрузке превью {preview_key}: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при загрузке превью в S3")

    return orig_key, preview_key


async def local_upload_photo_and_preview(
    photo_id: str, orig_stream: BytesIO, preview_stream: BytesIO, date: datetime, object_type: str
) -> tuple[str, str]:
    """
    💾 Загрузка оригинала и превью в локальную файловую систему.
    """
    logger.info("Загрузка файлов локально")
    date_str = date.strftime("%Y-%m-%d")
    orig_key = f"{object_type}/{date_str}/{photo_id}/orig.webp"
    preview_key = f"{object_type}/{date_str}/{photo_id}/preview.webp"
    orig_path = base_photo_path() / orig_key
    preview_path = base_photo_path() / preview_key

    try:
        os.makedirs(os.path.dirname(orig_path), exist_ok=True)
        logger.info(f"Директория для сохранения: {os.path.dirname(orig_path)}")
    except OSError as e:
        logger.error(f"Ошибка при создании директории: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при создании директории.")

    try:
        orig_stream.seek(0)
        with open(orig_path, "wb") as f:
            f.write(orig_stream.read())
        logger.info(f"Оригинальный файл сохранён: {orig_path}")
    except Exception as e:
        logger.error(f"Ошибка при записи оригинала: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при записи оригинала.")

    try:
        with open(preview_path, "wb") as f:
            f.write(preview_stream.read())
        logger.info(f"Превью сохранено: {preview_path}")
    except Exception as e:
        logger.error(f"Ошибка при записи превью: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при записи превью.")

    return orig_key, preview_key


async def delete_photo_file(link: str):
    """
    🗑 Удаление файла из хранилища (S3 или локально).
    """
    logger.info(f"Удаление файла: {link}")
    try:

        if s3client.use_s3:
            await asyncio.to_thread(
                s3client.client.remove_object, s3client.bucket_name, link
            )
            logger.info("Файл успешно удалён из S3")
            return True
        else:
            path = os.path.join(base_photo_path(), link)
            if os.path.exists(path):
                os.remove(path)
                logger.info("Файл успешно удалён локально")
                return True
            else:
                logger.warning("Файл для удаления не найден локально")
    except Exception as e:
        logger.error(f"Ошибка при удалении файла: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при удалении файла")


async def get_photo_file(
    object_type: str, date: str, identifier: int, filename: str
) -> StreamingResponse:
    """
    📥 Получение изображения из хранилища и отдача клиенту через StreamingResponse.
    """

    key = f"{object_type}/{date}/{identifier}/{filename}"
    logger.info(f"Получение файла: {key}")
    try:
        if s3client.use_s3:
            response = await asyncio.to_thread(
                s3client.client.get_object, s3client.bucket_name, key
            )
            media_type, _ = mimetypes.guess_type(filename)
            return StreamingResponse(
                response.stream(32 * 1024),
                media_type=media_type or "application/octet-stream",
            )
        else:
            path = os.path.join(base_photo_path(), key)
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="Файл не найден локально")
            return StreamingResponse(
                open(path, "rb"),
                media_type=mimetypes.guess_type(filename)[0]
                or "application/octet-stream",
            )
    except Exception as e:
        logger.error(f"Ошибка при получении файла: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при получении файла")
