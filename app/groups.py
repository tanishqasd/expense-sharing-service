from sqlite3 import SQLITE_CONSTRAINT_FOREIGNKEY, SQLITE_CONSTRAINT_PRIMARYKEY
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Group, GroupMember, User
from app.users import UserResponse


router = APIRouter(prefix="/groups", tags=["Groups"])
MAX_SQLITE_ID = 2**63 - 1
GroupId = Annotated[int, Path(gt=0, le=MAX_SQLITE_ID)]


class GroupCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class GroupMemberCreate(BaseModel):
    user_id: Annotated[int, Field(strict=True, gt=0, le=MAX_SQLITE_ID)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupCreate,
    db: Annotated[Session, Depends(get_session)],
) -> GroupResponse:
    with db.begin():
        group = Group(name=payload.name)
        db.add(group)
        db.flush()
        response = GroupResponse.model_validate(group)

    return response


@router.post("/{group_id}/members", status_code=status.HTTP_201_CREATED)
def add_group_member(
    group_id: GroupId,
    payload: GroupMemberCreate,
    db: Annotated[Session, Depends(get_session)],
) -> UserResponse:
    try:
        with db.begin():
            db.add(GroupMember(group_id=group_id, user_id=payload.user_id))
            db.flush()
            user = db.get_one(User, payload.user_id)
            response = UserResponse.model_validate(user)
    except IntegrityError as error:
        error_code = getattr(error.orig, "sqlite_errorcode", None)
        if error_code == SQLITE_CONSTRAINT_PRIMARYKEY:
            raise HTTPException(
                status_code=409, detail="User is already a member of this group."
            ) from error
        if error_code == SQLITE_CONSTRAINT_FOREIGNKEY:
            raise HTTPException(
                status_code=404, detail="Group or user not found."
            ) from error
        raise

    return response


@router.get("/{group_id}/members")
def list_group_members(
    group_id: GroupId,
    db: Annotated[Session, Depends(get_session)],
) -> list[UserResponse]:
    if db.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found.")

    members = db.scalars(
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.id)
    )
    return [UserResponse.model_validate(member) for member in members]