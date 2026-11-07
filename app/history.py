from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.expenses import format_paise
from app.groups import GroupId
from app.models import Expense, Group, User


router = APIRouter(prefix="/groups", tags=["Expenses"])


class ExpenseHistoryItem(BaseModel):
    id: int
    description: str
    amount: str
    paid_by: int
    payer_name: str
    created_at: datetime


@router.get("/{group_id}/expenses")
def list_group_expenses(
    group_id: GroupId,
    db: Annotated[Session, Depends(get_session)],
    search: Annotated[
        str | None,
        Query(description="Find a case-insensitive substring in the description."),
    ] = None,
) -> list[ExpenseHistoryItem]:
    if db.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found.")

    query = (
        select(Expense, User.name)
        .join(User, User.id == Expense.paid_by)
        .where(Expense.group_id == group_id)
        .order_by(Expense.created_at.desc(), Expense.id.desc())
    )

    search_term = search.strip().casefold() if search is not None else ""
    if search_term:
        query = query.where(
            func.instr(func.unicode_casefold(Expense.description), search_term) > 0
        )

    rows = db.execute(query)

    return [
        ExpenseHistoryItem(
            id=expense.id,
            description=expense.description,
            amount=format_paise(expense.amount_paise),
            paid_by=expense.paid_by,
            payer_name=payer_name,
            created_at=expense.created_at.replace(tzinfo=UTC),
        )
        for expense, payer_name in rows
    ]