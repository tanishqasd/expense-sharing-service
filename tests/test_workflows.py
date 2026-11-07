from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app import database
from app.balances import suggest_payments
from app.expenses import parse_paise
from app.main import app
from app.models import Expense, ExpenseShare


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    test_engine = database.create_sqlite_engine(tmp_path / "test.db")
    monkeypatch.setattr(database, "engine", test_engine)

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        test_engine.dispose()


def post_created(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_group(
    client: TestClient,
    name: str,
    member_ids: tuple[int, ...] = (),
) -> int:
    group_id = post_created(client, "/groups", {"name": name})["id"]
    for user_id in member_ids:
        post_created(
            client, f"/groups/{group_id}/members", {"user_id": user_id}
        )
    return group_id


def create_trip(client: TestClient) -> tuple[int, tuple[int, ...]]:
    user_ids = tuple(
        post_created(client, "/users", {"name": name})["id"]
        for name in ("Mohit", "Rahul", "Ankit")
    )
    group_id = create_group(client, "Goa Trip", user_ids)
    return group_id, user_ids


def record_expense(
    client: TestClient,
    group_id: int,
    payer_id: int,
    amount: str,
    description: str,
) -> dict:
    return post_created(
        client,
        "/expenses",
        {
            "group_id": group_id,
            "paid_by": payer_id,
            "amount": amount,
            "description": description,
        },
    )


def test_users_groups_and_membership_errors(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/users").json() == []

    user = post_created(client, "/users", {"name": "  Mohit  "})
    assert user["name"] == "Mohit"
    assert client.get("/users").json() == [user]
    assert client.post("/users", json={"name": ""}).status_code == 422
    assert client.post("/users", json={"name": "   "}).status_code == 422

    group = post_created(client, "/groups", {"name": "  Goa Trip  "})
    assert group["name"] == "Goa Trip"
    assert client.post("/groups", json={"name": "   "}).status_code == 422

    members_path = f"/groups/{group['id']}/members"
    empty = client.get(members_path)
    assert empty.status_code == 200
    assert empty.json() == []

    membership = {"user_id": user["id"]}
    assert post_created(client, members_path, membership) == user
    assert client.post(members_path, json=membership).status_code == 409
    assert client.post(members_path, json={"user_id": 999999}).status_code == 404
    assert client.post(
        "/groups/999999/members", json=membership
    ).status_code == 404
    assert client.get("/groups/999999/members").status_code == 404
    assert client.get(members_path).json() == [user]


def test_expense_creation_saves_equal_shares(client: TestClient) -> None:
    group_id, user_ids = create_trip(client)
    dinner = record_expense(client, group_id, user_ids[0], "1200.00", "Dinner")

    assert dinner["group_id"] == group_id
    assert dinner["paid_by"] == user_ids[0]
    assert dinner["amount"] == "1200.00"
    assert dinner["shares"] == [
        {"user_id": user_id, "amount": "400.00"} for user_id in user_ids
    ]

    with database.engine.connect() as connection:
        total = connection.scalar(
            select(Expense.amount_paise).where(Expense.id == dinner["id"])
        )
        shares = connection.scalars(
            select(ExpenseShare.share_paise)
            .where(ExpenseShare.expense_id == dinner["id"])
            .order_by(ExpenseShare.user_id)
        ).all()

    assert total == 120000
    assert shares == [40000, 40000, 40000]
    assert sum(shares) == total

    history = client.get(f"/groups/{group_id}/expenses")
    assert history.status_code == 200
    assert history.json() == [
        {
            "id": dinner["id"],
            "description": "Dinner",
            "amount": "1200.00",
            "paid_by": user_ids[0],
            "payer_name": "Mohit",
            "created_at": dinner["created_at"],
        }
    ]


def test_rounding_and_late_join_preserve_saved_shares(client: TestClient) -> None:
    group_id, user_ids = create_trip(client)
    taxi = record_expense(client, group_id, user_ids[0], "100.00", "Taxi")
    tiny = record_expense(client, group_id, user_ids[0], "0.01", "Small charge")

    assert [share["amount"] for share in taxi["shares"]] == [
        "33.34", "33.33", "33.33"
    ]
    assert [share["amount"] for share in tiny["shares"]] == [
        "0.01", "0.00", "0.00"
    ]

    late_user = post_created(client, "/users", {"name": "Priya"})
    post_created(
        client,
        f"/groups/{group_id}/members",
        {"user_id": late_user["id"]},
    )

    with database.engine.connect() as connection:
        saved = connection.execute(
            select(ExpenseShare.user_id, ExpenseShare.share_paise)
            .where(ExpenseShare.expense_id == taxi["id"])
            .order_by(ExpenseShare.user_id)
        ).all()

    assert [tuple(row) for row in saved] == list(zip(user_ids, (3334, 3333, 3333)))
    assert sum(row.share_paise for row in saved) == 10000

    next_expense = record_expense(client, group_id, user_ids[0], "4.00", "Tea")
    assert next_expense["shares"][-1] == {
        "user_id": late_user["id"],
        "amount": "1.00",
    }


def test_invalid_expenses_leave_no_rows(client: TestClient) -> None:
    group_id, user_ids = create_trip(client)
    empty_group_id = create_group(client, "Empty Group")
    outsider = post_created(client, "/users", {"name": "Outsider"})

    valid = {
        "group_id": group_id,
        "paid_by": user_ids[0],
        "amount": "100.00",
        "description": "Dinner",
    }
    cases = [
        ({"amount": "0"}, 422),
        ({"amount": "-5.00"}, 422),
        ({"amount": "10.001"}, 422),
        ({"amount": 100}, 422),
        ({"amount": "92233720368547758.08"}, 422),
        ({"description": "   "}, 422),
        ({"group_id": 999999}, 404),
        ({"paid_by": 999999}, 404),
        ({"paid_by": outsider["id"]}, 422),
        ({"group_id": empty_group_id}, 409),
    ]

    for changes, expected_status in cases:
        response = client.post("/expenses", json=valid | changes)
        assert response.status_code == expected_status, (changes, response.text)

    with database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Expense)) == 0
        assert connection.scalar(select(func.count()).select_from(ExpenseShare)) == 0


def test_group_balances_and_deterministic_payments(client: TestClient) -> None:
    group_id, (mohit, rahul, ankit) = create_trip(client)
    other_id = create_group(client, "History Check", (mohit, rahul))
    empty_id = create_group(client, "Empty Group")

    record_expense(client, group_id, mohit, "1200.00", "Dinner")
    record_expense(client, group_id, rahul, "300.00", "Lunch")
    record_expense(client, other_id, rahul, "20.00", "Snacks")

    path = f"/groups/{group_id}/balances"
    response = client.get(path)
    assert response.status_code == 200
    result = response.json()
    assert result["group_id"] == group_id
    assert result["balances"] == [
        {"user_id": mohit, "name": "Mohit", "net_balance": "700.00"},
        {"user_id": rahul, "name": "Rahul", "net_balance": "-200.00"},
        {"user_id": ankit, "name": "Ankit", "net_balance": "-500.00"},
    ]
    assert result["suggested_payments"] == [
        {"from_user_id": rahul, "to_user_id": mohit, "amount": "200.00"},
        {"from_user_id": ankit, "to_user_id": mohit, "amount": "500.00"},
    ]
    assert client.get(path).json() == result

    other = client.get(f"/groups/{other_id}/balances").json()
    assert other["balances"] == [
        {"user_id": mohit, "name": "Mohit", "net_balance": "-10.00"},
        {"user_id": rahul, "name": "Rahul", "net_balance": "10.00"},
    ]
    assert other["suggested_payments"] == [
        {"from_user_id": mohit, "to_user_id": rahul, "amount": "10.00"}
    ]

    assert client.get(f"/groups/{empty_id}/balances").json() == {
        "group_id": empty_id,
        "balances": [],
        "suggested_payments": [],
    }
    assert client.get("/groups/999999/balances").status_code == 404


def test_suggested_payments_clear_multiple_debtors_and_creditors() -> None:
    net = {4: 300, 1: -400, 3: 200, 2: -100, 5: 0}
    payments = suggest_payments(net)

    assert [
        (payment.from_user_id, payment.to_user_id, payment.amount)
        for payment in payments
    ] == [(1, 3, "2.00"), (1, 4, "2.00"), (2, 4, "1.00")]

    remaining = net.copy()
    for payment in payments:
        amount = parse_paise(payment.amount)
        remaining[payment.from_user_id] += amount
        remaining[payment.to_user_id] -= amount

    assert remaining == dict.fromkeys(net, 0)


def test_history_search_is_literal_case_insensitive_and_group_scoped(
    client: TestClient,
) -> None:
    group_id, user_ids = create_trip(client)
    other_id = create_group(client, "Other Group", (user_ids[0],))
    empty_id = create_group(client, "Empty Group")

    dinner = record_expense(client, group_id, user_ids[0], "30.00", "Dinner")
    newer = record_expense(
        client, group_id, user_ids[0], "20.00", "Dinner on Straße 100%_test"
    )
    other = record_expense(client, other_id, user_ids[0], "10.00", "Dinner")

    with database.engine.begin() as connection:
        connection.execute(
            update(Expense)
            .where(Expense.group_id == group_id)
            .values(created_at=datetime(2026, 1, 1))
        )

    path = f"/groups/{group_id}/expenses"
    normal = client.get(path).json()
    assert [row["id"] for row in normal] == [newer["id"], dinner["id"]]
    assert client.get(path, params={"search": "   "}).json() == normal

    mixed_case = client.get(path, params={"search": "dIn"}).json()
    assert mixed_case == normal

    unicode_match = client.get(path, params={"search": "STRASSE"}).json()
    assert [row["id"] for row in unicode_match] == [newer["id"]]

    literal_match = client.get(path, params={"search": "%_"}).json()
    assert [row["id"] for row in literal_match] == [newer["id"]]

    other_match = client.get(
        f"/groups/{other_id}/expenses", params={"search": "DINNER"}
    ).json()
    assert [row["id"] for row in other_match] == [other["id"]]
    assert client.get(path, params={"search": "hotel"}).json() == []
    assert client.get(f"/groups/{empty_id}/expenses").json() == []
    assert client.get("/groups/999999/expenses").status_code == 404