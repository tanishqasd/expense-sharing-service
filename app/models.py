from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "paid_by"],
            ["group_members.group_id", "group_members.user_id"],
            name="fk_expense_payer_membership",
        ),
        UniqueConstraint("group_id", "id", name="uq_expense_group_id"),
        CheckConstraint(
            "typeof(amount_paise) = 'integer' AND amount_paise > 0",
            name="ck_expense_positive_paise",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int]
    paid_by: Mapped[int]
    amount_paise: Mapped[int]
    description: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp()
    )


class ExpenseShare(Base):
    __tablename__ = "expense_shares"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "expense_id"],
            ["expenses.group_id", "expenses.id"],
            name="fk_share_group_expense",
        ),
        ForeignKeyConstraint(
            ["group_id", "user_id"],
            ["group_members.group_id", "group_members.user_id"],
            name="fk_share_membership",
        ),
        CheckConstraint(
            "typeof(share_paise) = 'integer' AND share_paise >= 0",
            name="ck_share_nonnegative_paise",
        ),
    )

    expense_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int]
    share_paise: Mapped[int]