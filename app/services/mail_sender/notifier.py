from smtplib import SMTPException
from typing import List

from pydantic import EmailStr, SecretStr

from fastapi import HTTPException
from fastapi_mail import FastMail, MessageSchema,ConnectionConfig, MessageType
from fastapi.responses import JSONResponse
from fastapi_mail.errors import ConnectionErrors, PydanticClassRequired

from app.utils.logger import logger
from app.core.config import get_mail_sender_config


class EmailSendingError(Exception):
    """Кастомное исключение для ошибок отправки email"""
    pass


class WorkingWithEmail:

    def __init__(self):
        self.conf = ConnectionConfig(
            MAIL_USERNAME=str(get_mail_sender_config().MAIL_USERNAME),
            MAIL_PASSWORD=get_mail_sender_config().MAIL_PASSWORD,
            MAIL_FROM=get_mail_sender_config().MAIL_FROM,
            MAIL_FROM_NAME='Anwill',
            MAIL_PORT=get_mail_sender_config().MAIL_PORT,
            MAIL_SERVER=get_mail_sender_config().MAIL_SERVER,
            MAIL_STARTTLS=True,
            MAIL_SSL_TLS=False,
            USE_CREDENTIALS=True
        )

    async def send_email_to_user(self, subject: str, body: str, emails: List[EmailStr]):
        """
        Отправка email с обработкой специфичных исключений
        Возвращает True при успехе, иначе выбрасывает EmailSendingError
        """
        try:
            message = MessageSchema(
                subject=subject,
                recipients=emails,
                body=body,
                subtype=MessageType.html
            )
            logger.info(f'Отправка email: {subject}')
            fm = FastMail(self.conf)
            await fm.send_message(message)
            return True

        except PydanticClassRequired as e:
            logger.error(f"Ошибка: требуется Pydantic-класс: {e}")
            raise EmailSendingError("Некорректные параметры письма")

        except ConnectionErrors as e:
            logger.error(f"SMTP ошибка соединения: {e}")
            raise EmailSendingError("Ошибка подключения к почтовому серверу")

        except TimeoutError as e:
            logger.error(f"Таймаут отправки письма: {e}")
            raise EmailSendingError("Таймаут при отправке письма")

        except SMTPException as e:
            logger.error(f"SMTP ошибка: {e}")
            raise EmailSendingError("Ошибка SMTP сервера")

        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке: {e}")
            raise EmailSendingError("Внутренняя ошибка сервера")

    async def send_email(
            self,
            subject: str,
            body: str,
            emails: List[EmailStr],
            resp: str
    ):
        """
        Обертка для отправки с возвратом JSONResponse
        """
        try:
            await self.send_email_to_user(
                subject=subject,
                body=body,
                emails=emails
            )
            return JSONResponse(
                status_code=200,
                content={"message": resp}
            )

        except EmailSendingError as e:
            logger.error(f"Ошибка отправки: {str(e)}")
            raise HTTPException(
                status_code=400 if "Некорректные" in str(e) else 500,
                detail="Не удалось отправить письмо"
            )

