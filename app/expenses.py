from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import insert, literal, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Expense, ExpenseShare, Group, GroupMember, User


router = APIRouter(prefix="/expenses", tags=["Expenses"])
MAX_SQLITE_INTEGER = 2**63 - 1
PositiveId = Annotated[int, Field(strict=True, gt=0, le=MAX_SQLITE_INTEGER)]


class ExpenseCreate(BaseModel):
    group_id: PositiveId
    paid_by: PositiveId
    amount: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,17}(\.[0-9]{1,2})?$")]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExpenseShareResponse(BaseModel):
    user_id: int
    amount: str


class ExpenseResponse(BaseModel):
    id: int
    group_id: int
    paid_by: int
    amount: str
    description: str
    created_at: datetime
    shares: list[ExpenseShareResponse]


def parse_paise(amount: str) -> int:
    rupees, _, fraction = amount.partition(".")
    return int(rupees) * 100 + int(fraction.ljust(2, "0"))


def format_paise(amount_paise: int) -> str:
    rupees, paise = divmod(amount_paise, 100)
    return f"{rupees}.{paise:02d}"


@router.post("", status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    db: Annotated[Session, Depends(get_session)],
) -> ExpenseResponse:
    amount_paise = parse_paise(payload.amount)
    if not 0 < amount_paise <= MAX_SQLITE_INTEGER:
        raise HTTPException(status_code=422, detail="Amount is outside the supported range.")

    payer_membership = select(
        GroupMember.group_id,
        GroupMember.user_id,
        literal(amount_paise),
        literal(payload.description),
    ).where(
        GroupMember.group_id == payload.group_id,
        GroupMember.user_id == payload.paid_by,
    )

    with db.begin():
        expense = db.scalar(
            insert(Expense)
            .from_select(
                ["group_id", "paid_by", "amount_paise", "description"],
                payer_membership,
            )
            .returning(Expense)
        )

        member_ids = db.scalars(
            select(GroupMember.user_id)
            .where(GroupMember.group_id == payload.group_id)
            .order_by(GroupMember.user_id)
        ).all()

        if expense is None:
            if db.get(Group, payload.group_id) is None:
                raise HTTPException(status_code=404, detail="Group not found.")
            if db.get(User, payload.paid_by) is None:
                raise HTTPException(status_code=404, detail="Payer not found.")
            if not member_ids:
                raise HTTPException(status_code=409, detail="Group has no members.")
            raise HTTPException(status_code=422, detail="Payer must be a group member.")

        base_share, remainder = divmod(amount_paise, len(member_ids))
        shares = [
            ExpenseShare(
                expense_id=expense.id,
                group_id=expense.group_id,
                user_id=user_id,
                share_paise=base_share + (1 if index < remainder else 0),
            )
            for index, user_id in enumerate(member_ids)
        ]
        db.add_all(shares)

        return ExpenseResponse(
            id=expense.id,
            group_id=expense.group_id,
            paid_by=expense.paid_by,
            amount=format_paise(expense.amount_paise),
            description=expense.description,
            created_at=expense.created_at.replace(tzinfo=UTC),
            shares=[
                ExpenseShareResponse(
                    user_id=share.user_id,
                    amount=format_paise(share.share_paise),
                )
                for share in shares
            ],
        )