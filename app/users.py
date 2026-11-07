from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import User


router = APIRouter(prefix="/users", tags=["Users"])


class UserCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_session)],
) -> UserResponse:
    with db.begin():
        user = User(name=payload.name)
        db.add(user)
        db.flush()
        response = UserResponse.model_validate(user)

    return response


@router.get("")
def list_users(db: Annotated[Session, Depends(get_session)]) -> list[UserResponse]:
    users = db.scalars(select(User).order_by(User.id))
    return [UserResponse.model_validate(user) for user in users]