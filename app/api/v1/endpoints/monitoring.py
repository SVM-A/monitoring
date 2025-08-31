import re
from datetime import datetime, timezone, timedelta, UTC
from typing import List, TypeVar, Optional
from uuid import uuid4

from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi import APIRouter, Response, Depends, Request, Security, Path, HTTPException, UploadFile, BackgroundTasks, \
    Cookie
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.endpoints.stream import StreemAPI
from app.core.config import algorithm_env, refresh_token_env, stream_token_env
from app.db.sessions import TransactionSessionDep, SessionDep
from app.api.v1.base_api import AnwillUserAPI
from app.db.models.base_sql import BaseSQL

from app.db.dao.user import BaseDAO


DAO = TypeVar("DAO", bound=BaseDAO)
PYDANTIC = TypeVar("PYDANTIC", bound=BaseModel)
SQL = TypeVar("SQL", bound=BaseSQL)


class ProfileAPI(AnwillUserAPI):

    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.prefix = f"/me/profile"
        self.tags = ['Profile']
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)

    async def setup_routes(self):
        pass