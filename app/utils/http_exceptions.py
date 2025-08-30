from fastapi import HTTPException, status


class UserAlreadyExistsException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь уже зарегистрирован",
            headers={"X-Error-Code": "1001"}
        )

class IncorrectPasswordException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Пароль должен содержать минимум 8 символов и включать хотя бы одну цифру.",
            headers={"X-Error-Code": "1021"}
        )

class IncorrectPhoneOrEmailException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат ввода. Введите email или номер телефона.",
            headers={"X-Error-Code": "1005"}
        )

class NotValidateException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Не удалось проверить учетные данные",
            headers={"X-Error-Code": "1005"}
        )

class IncorrectRefreshPasswordException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный пароль",
            headers={"X-Error-Code": "1003"}
        )

class IncorrectEmailOrPasswordException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверная почта или пароль",
            headers={"X-Error-Code": "1003"}
        )

class IncorrectPhoneOrPasswordException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный телефон или пароль",
            headers={"X-Error-Code": "1003"}
        )

class EmailBusyException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email адрес уже зарегистрирован",
            headers={"X-Error-Code": "1003"}
        )

class PhoneBusyException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Номер телефона уже зарегистрирован",
            headers={"X-Error-Code": "1003"}
        )

class TokenExpiredException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Токен истек",
            headers={"X-Error-Code": "1011"}
        )

class TokenNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Токен не найден",
            headers={"X-Error-Code": "1011"}
        )

class TokenGenerationException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ошибка генерации токена",
            headers={"X-Error-Code": "1011"}
        )

class InvalidJwtException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен не валидный!",
            headers={"X-Error-Code": "1011"}
        )

class InvalidMatchJwtException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Токены не совпадают!",
            headers={"X-Error-Code": "1011"}
        )

class NoCsrfTokenException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF токен отсутствует или недействителен",
            headers={"X-Error-Code": "1011"}
        )

class ForbiddenAccessException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав!",
            headers={"X-Error-Code": "1011"}
        )

class UserIdNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Не найден ID пользователя",
            headers={"X-Error-Code": "1007"}
        )

class UserNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
            headers={"X-Error-Code": "1007"}
        )

class UserBannedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь заблокирован!",
            headers={"X-Error-Code": "1009"}
        )

class RoleAlreadyAssignedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="Роль пользователю уже присвоена",
            headers={"X-Error-Code": "1031"}
        )

class RoleNotFoundException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Роль не найдена",
            headers={"X-Error-Code": "1037"}
        )

class RoleNotAssignedException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="Роль для пользователя итак не доступна",
            headers={"X-Error-Code": "1031"}
        )

class DeleteErrorException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при удалении",
            headers={"X-Error-Code": "1050"}
        )

class DeleteEmailPhoneErrorException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ошибка при удалении. Невозможно удалить единственный контакт.",
            headers={"X-Error-Code": "1051"}
        )

class ValidErrorException(HTTPException):
    def __init__(self, mess):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=mess,
            headers={"X-Error-Code": "1005"}
        )

class UpdateErrorException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при обновлении",
            headers={"X-Error-Code": "1060"}
        )

class PostErrorException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при добавлении",
            headers={"X-Error-Code": "1070"}
        )

class PostEmailPhoneErrorException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при добавлении. Запись уже существует.",
            headers={"X-Error-Code": "1071"}
        )

class EmailAvailableException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Нету зарегистрированного email.",
            headers={"X-Success-Code": "2122"}
        )

class PhoneAvailableException(HTTPException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Нету зарегистрированного номера телефона.",
            headers={"X-Success-Code": "2122"}
        )

