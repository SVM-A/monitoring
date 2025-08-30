# docs/responses_variants.py

from app.db.schemas.user import AccessTokenSchema, ErrorResponseSchema, ValidationResponseSchema, ServerErrorResponseSchema, \
    SuccessfulResponseSchema, SUserInfo, SUserInfoRole, ErrorValidResponseSchema, ValidErrorExceptionSchema, \
    CheckPhoneModel, CheckEmailModel, AvailableExceptionSchema, ProfileInfo, SRoleInfo

check_email_resps = {
    200: {
        "description": "Результат проверки почты",
        "model": SuccessfulResponseSchema,
        "content": {
            "application/json": {
                "examples": {
                    "EmailExists": {
                        "summary": "Почта найдена в базе данных",
                        "value": {
                            "status": "success",
                            "message": "Email exists",
                            "data": {
                                "exists": True
                            }
                        }
                    },
                    "EmailNotFound": {
                        "summary": "Почта не найдена в базе данных",
                        "value": {
                            "status": "success",
                            "message": "Email not found",
                            "data": {
                                "exists": False
                            }
                        }
                    }
                }
            }
        },
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2011'
                }
            }
        }
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1006
                }
            }
        }
    },
}
check_phone_resps = {
    200: {
        "description": "Результат проверки номера телефона",
        "model": SuccessfulResponseSchema,
        "content": {
            "application/json": {
                "examples": {
                    "PhoneExists": {
                        "summary": "Номер телефона найден в базе данных",
                        "value": {
                            "status": "success",
                            "message": "Phone number exists",
                            "data": {
                                "exists": True
                            }
                        }
                    },
                    "PhoneNotFound": {
                        "summary": "Номер телефона не найден в базе данных",
                        "value": {
                            "status": "success",
                            "message": "Phone number not found",
                            "data": {
                                "exists": False
                            }
                        }
                    }
                }
            }
        },
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2012'
                }
            }
        }
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1006
                }
            }
        }
    },
}

standard_headers = {
    "Access-Control-Allow-Credentials": {
        "description": "Указывает, разрешены ли учетные данные для CORS-запроса",
        "schema": {
            "type": "boolean",
            "example": True
        }
    },
    "Content-Type": {
        "description": "Тип содержимого ответа",
        "schema": {
            "type": "string",
            "example": "application/json"
        }
    },
    "Date": {
        "description": "Дата и время ответа",
        "schema": {
            "type": "string",
            "example": "Mon, 13 Jan 2025 20:03:10 GMT"
        }
    },
    "Server": {
        "description": "Информация о сервере",
        "schema": {
            "type": "string",
            "example": "uvicorn"
        }
    },
}
set_cookie = {
    "Set-Cookie": {
        "description": "Cookies для хранения refresh_token (HttpOnly) и csrf_token.",
        "schema": {
            "type": "string",
            "examples": [
                "refresh_token=<token_value>; HttpOnly; Secure=False; SameSite=Strict",
                "csrf_token=<csrf_token_value>; Secure=False; SameSite=Strict"
            ]
        }
    }
}

register_resps = {
    200: {
        "description": "Успешная регистрация пользователя",
        "model": AccessTokenSchema,
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2001'
                },
            },**set_cookie
        },
    },
    400: {
        "description": "Некорректные данные (почта или номер телефона)",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1001
                }
            }
        }
    },
    401: {
        "description": "Неверные учетные данные (почта/телефон или пароль)",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1003
                }
            }
        }
    },
    406: {
        "description": "Пароль не соответствует требованиям",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1004
                }
            }
        }
    },
    409: {
        "description": "Пользователь уже зарегистрирован",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1002
                }
            }
        }
    },
    422: {
        "description": "Ошибка валидации данных",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1006
                }
            }
        }
    },
}
login_resps = {
    200: {
        "description": "Успешная авторизация или обновление токена",
        "model": AccessTokenSchema,
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2002'
                },
            }, **set_cookie
        },
    },
    400: {
        "description": "Некорректный запрос. Отсутствует обязательный параметр или неправильный формат.",
        "model": ErrorValidResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1009
                }
            }
        },
    },
    401: {
        "description": "Неверные учетные данные или токен обновления отсутствует/некорректен",
        "model": ErrorValidResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1010
                }
            }
        }
    },
    403: {
        "description": "Пользователь заблокирован или refresh_token недействителен",
        "model": ErrorValidResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1011
                }
            }
        }
    },
    404: {
        "description": "Пользователь не найден",
        "model": ErrorValidResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1007
                }
            }
        }
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1006
                }
            }
        }
    },
}
logout_resps = {
    200: {
        "description": "Успешный выход из системы",
        "model": SuccessfulResponseSchema,
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2003'
                },
            }, **set_cookie
        },
    },
    401: {
        "description": "Неверные учетные данные или токен обновления отсутствует/некорректен",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1010
                }
            }
        }
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1006
                }
            }
        }
    },
}
password_reset_resps = {
    200: {
        "description": "Успешный запрос на сброс пароля",
        "model": SuccessfulResponseSchema,
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2003'
                },
            },
        },
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": "1006"
                }
            }
        }
    },
}
email_verify_resps = {
    200: {
        "description": "Успешный запрос на подтверждение email адреса",
        "model": SuccessfulResponseSchema,
        "headers": {
            "X-Success-Code": {
                "description": "Код успешного выполнения",
                "schema": {
                    "type": "string",
                    "example": '2003'
                },
            },
        },
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": "1006"
                }
            }
        }
    },
}



standard_get_resps = {
    400: {
        "description": "Некорректный запрос. Отсутствует обязательный параметр или неправильный формат.",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1009
                }
            }
        }
    },
    403: {
        "description": "Пользователь заблокирован или refresh_token недействителен",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1011
                }
            }
        }
    },
    404: {
        "description": "Пользователь не найден",
        "model": ErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1007
                }
            }
        }
    },
    422: {
        "description": "Ошибка валидации данных формы",
        "model": ValidErrorExceptionSchema | ValidationResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1005
                }
            }
        }
    },
    500: {
        "description": "Внутренняя ошибка сервера",
        "model": ServerErrorResponseSchema,
        "headers": {
            "X-Error-Code": {
                "description": "Код ошибки",
                "schema": {
                    "type": "string",
                    "example": 1006
                }
            }
        }
    },
}

user_get_resps = standard_get_resps.copy()
users_get_resps = standard_get_resps.copy()
user_put_resps = standard_get_resps.copy()
user_patch_resps = standard_get_resps.copy()
user_del_resps = standard_get_resps.copy()

user_get_resps[200] = {
    "description": "Успешное извлечение данных пользователя",
    "model": SUserInfoRole,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2004'
            },
        }, **set_cookie
    },
}
users_get_resps[200] = {
    "description": "Успешное извлечение данных пользователей",
    "model": list[SUserInfoRole],
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2004'
            },
        }, **set_cookie
    },
}
user_put_resps[200] = {
    "description": "Успешная перезапись данных пользователей",
    "model": SUserInfo,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2006'
            },
        }, **set_cookie
    },
}
user_patch_resps[200] = {
    "description": "Успешное обновление данных пользователя",
    "model": SUserInfo,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2007'
            },
        }, **set_cookie
    },
}
user_del_resps[200] = {
    "description": "Успешное удаление пользователя",
    "model": SuccessfulResponseSchema,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2008'
            }
        },
    }
}

profile_get_resps = standard_get_resps.copy()
profile_put_resps = standard_get_resps.copy()

profile_get_resps[200] = {
    "description": "Успешное извлечение данных профиля пользователя",
    "model": ProfileInfo,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2004'
            },
        }, **set_cookie
    },
}
profile_put_resps[200] = {
    "description": "Успешное обновление данных профиля пользователя",
    "model": ProfileInfo,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2004'
            },
        }, **set_cookie
    },
}


role_get_resps = standard_get_resps.copy()
role_post_resps = standard_get_resps.copy()
role_put_resps = standard_get_resps.copy()
role_del_resps = standard_get_resps.copy()

role_get_resps[200] = {
    "description": "Успешное извлечение прав",
    "model": SRoleInfo,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2004'
            },
        }, **set_cookie
    },
}
role_post_resps[200] = {
    "description": "Успешное добавление прав",
    "model": SUserInfoRole,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2005'
            },
        }, **set_cookie
    },
}
role_put_resps[200] = {
    "description": "Успешная перезапись прав",
    "model": SUserInfoRole,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2006'
            },
        }, **set_cookie
    },
}
role_del_resps[200] = {
    "description": "Успешная удаление прав",
    "model": SUserInfoRole,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": 2008
            },
        }, **set_cookie
    },
}


email_phone_resps = standard_get_resps.copy()
email_phone_resps[200] = {
    "description": "Успешное извлечение email или телефона",
    "model": CheckEmailModel | CheckPhoneModel,
    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2004'
            },
        }, **set_cookie
    },
}
email_phone_resps[202] = {
    "description": "Успех, но данных нет.",
    "model": AvailableExceptionSchema,
    "content": {
        "application/json": {
            "examples": {
                "EmailNot": {
                    "summary": "Email отсутствует, но ошибок нету.",
                    "value": {
                        "detail": "Нету зарегистрированного email.",
                    }
                },
                "PhoneNumberNot": {
                    "summary": "Номер телефона отсутствует, но ошибок нету.",
                    "value": {
                        "detail": "Нету зарегистрированного номера телефона.",
                    }
                }
            }
        }
    },

    "headers": {
        "X-Success-Code": {
            "description": "Код успешного выполнения",
            "schema": {
                "type": "string",
                "example": '2122'
            },
        }, **set_cookie
    },
}
