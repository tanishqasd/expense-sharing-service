from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.database import initialize_database
from app.expenses import router as expenses_router
from app.groups import router as groups_router
from app.users import router as users_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title="Expense Sharing Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(users_router)
app.include_router(groups_router)
app.include_router(expenses_router)


class HealthResponse(BaseModel):
    status: Literal["ok"]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")