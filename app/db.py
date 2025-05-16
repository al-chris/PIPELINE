from collections.abc import AsyncGenerator
from sqlmodel import SQLModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from typing import Annotated, Optional
from fastapi import Depends
from app.logging import logger

from app.config import settings

class FileAnnotation(SQLModel, table=True):
    task_id: str = Field(primary_key=True, unique=True)
    file_url: str
    annotation: Optional[str]


DATABASE_URL = str(settings.DATABASE_URL).replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=True, future=True)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_db)]


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28

async def create_db_and_tables():
    logger.info("Creating database tables")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database tables created")