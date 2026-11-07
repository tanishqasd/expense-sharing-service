from collections import deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.expenses import format_paise
from app.groups import GroupId
from app.models import Expense, ExpenseShare, Group, GroupMember, User


router = APIRouter(prefix="/groups", tags=["Balances"])


class MemberBalance(BaseModel):
    user_id: int
    name: str
    net_balance: str


class SuggestedPayment(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: str


class GroupBalances(BaseModel):
    group_id: int
    balances: list[MemberBalance]
    suggested_payments: list[SuggestedPayment]


def format_net_balance(net_paise: int) -> str:
    if net_paise < 0:
        return f"-{format_paise(-net_paise)}"
    return format_paise(net_paise)


def suggest_payments(net_by_user: dict[int, int]) -> list[SuggestedPayment]:
    ordered_balances = sorted(net_by_user.items())
    debtors = deque((user_id, -net) for user_id, net in ordered_balances if net < 0)
    creditors = deque((user_id, net) for user_id, net in ordered_balances if net > 0)

    payments = []
    while debtors and creditors:
        debtor_id, debt = debtors.popleft()
        creditor_id, credit = creditors.popleft()
        amount = min(debt, credit)

        payments.append(
            SuggestedPayment(
                from_user_id=debtor_id,
                to_user_id=creditor_id,
                amount=format_paise(amount),
            )
        )

        if debt > amount:
            debtors.appendleft((debtor_id, debt - amount))
        if credit > amount:
            creditors.appendleft((creditor_id, credit - amount))

    return payments


@router.get("/{group_id}/balances")
def get_group_balances(
    group_id: GroupId,
    db: Annotated[Session, Depends(get_session)],
) -> GroupBalances:
    if db.get(Group, group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found.")

    members = db.execute(
        select(User.id, User.name)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.id)
    ).all()
    net_by_user = {user_id: 0 for user_id, _ in members}

    expenses = db.execute(
        select(Expense.paid_by, Expense.amount_paise)
        .where(Expense.group_id == group_id)
    )
    for payer_id, amount_paise in expenses:
        net_by_user[payer_id] += amount_paise

    shares = db.execute(
        select(ExpenseShare.user_id, ExpenseShare.share_paise)
        .where(ExpenseShare.group_id == group_id)
    )
    for user_id, share_paise in shares:
        net_by_user[user_id] -= share_paise

    return GroupBalances(
        group_id=group_id,
        balances=[
            MemberBalance(
                user_id=user_id,
                name=name,
                net_balance=format_net_balance(net_by_user[user_id]),
            )
            for user_id, name in members
        ],
        suggested_payments=suggest_payments(net_by_user),
    )