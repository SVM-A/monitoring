# app/database/load_docs.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import get_pstgr_settings
from ._session import DatabaseSessionManager

async_engine = create_async_engine(url=get_pstgr_settings().async_user_pstgr_url)
async_session_maker = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)

# sync_engine = create_engine(PSTGR_URL_SYNC, pool_pre_ping=True)
# sync_session_maker = sessionmaker(bind=sync_engine)

# Создаём менеджер сессий
async_session_manager = DatabaseSessionManager(async_session_maker)
# sync_session_manager = DatabaseSessionManager(sync_session_maker)

# Декораторы
async_connect_db = async_session_manager.async_connection
# sync_connect_db = sync_session_manager.sync_connection

# FastAPI зависимости
SessionDep = async_session_manager.async_session_dependency
TransactionSessionDep = async_session_manager.async_transaction_session_dependency
# SessionDepSync = sync_session_manager.sync_session_dependency
# TransactionSessionDepSync = sync_session_manager.sync_transaction_session_dependency

