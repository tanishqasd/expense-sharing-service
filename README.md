# Expense Sharing Service

A FastAPI backend for tracking shared expenses. Users can create groups, add members, record expenses split equally among current members, and see who should pay whom. Group expense history also supports case-insensitive search by description.

Built with Python 3.14, FastAPI, Pydantic, SQLAlchemy, and SQLite.

## Run locally on Windows

Install Python 3.14 and Git, then open PowerShell and run:

```powershell
git clone https://github.com/tanishqasd/expense-sharing-service.git
Set-Location .\expense-sharing-service
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Leave the server running. Open [Swagger UI](http://127.0.0.1:8001/docs) to try the endpoints or [OpenAPI JSON](http://127.0.0.1:8001/openapi.json) to view the API schema. The server creates `expense_sharing.db` in the repository root on first startup. The database file is local and ignored by Git.

In a second PowerShell terminal, check the API:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/health'
```

The response is `{"status":"ok"}`. Press **Ctrl+C** in the server terminal to stop Uvicorn.

## API reference

Base URL is `http://127.0.0.1:8001`. Send POST bodies as JSON with `Content-Type: application/json`. Example IDs below are illustrative. Use the IDs returned by your requests.

| Method and path | Request | Success |
|---|---|---|
| `GET /health` | None | `200` with `{"status":"ok"}` |
| `POST /users` | `{"name":"Mohit"}` | `201` with `{"id":1,"name":"Mohit"}` |
| `GET /users` | None | `200` with users in ascending ID order |
| `POST /groups` | `{"name":"Goa Trip"}` | `201` with `{"id":1,"name":"Goa Trip"}` |
| `POST /groups/{group_id}/members` | `{"user_id":1}` | `201` with the added user's ID and name |
| `GET /groups/{group_id}/members` | None | `200` with members in ascending user ID order |
| `POST /expenses` | `{"group_id":1,"paid_by":1,"amount":"1200.00","description":"Dinner"}` | `201` with the expense, UTC creation time, and saved shares |
| `GET /groups/{group_id}/expenses` | Optional `search` query parameter | `200` with history including the payer ID and name. Newest entries appear first, with higher expense IDs first when timestamps tie. |
| `GET /groups/{group_id}/balances` | None | `200` with `group_id`, `balances`, and `suggested_payments` |

Money is sent and returned as rupee strings. For example, send `"1200.00"` in JSON. Each share contains `user_id` and `amount`. A balance entry contains `user_id`, `name`, and `net_balance`. A suggested payment contains `from_user_id`, `to_user_id`, and `amount`.

| Error | When it occurs |
|---|---|
| `404 Not Found` | A requested group, user, or payer ID does not exist. |
| `409 Conflict` | The user already belongs to the group, or an expense is attempted for an empty group with an existing payer. |
| `422 Unprocessable Entity` | A field is invalid, an amount is zero or outside the accepted format or range, or the payer is outside a nonempty group. |

An existing group with no members or expenses returns an empty array for the corresponding list. Its balance response contains empty `balances` and `suggested_payments` arrays when it has no members.

## Try the Goa Trip example

With the server running, paste this into a second PowerShell terminal. The script creates a new group each time and uses the IDs returned by the API.

```powershell
$api = 'http://127.0.0.1:8001'

function New-ApiResource {
    param([string]$Path, [hashtable]$Data)

    Invoke-RestMethod -Uri "$api$Path" `
        -Method Post -ContentType 'application/json' `
        -Body ($Data | ConvertTo-Json -Compress) -ErrorAction Stop
}

$mohit = New-ApiResource '/users' @{ name = 'Mohit' }
$rahul = New-ApiResource '/users' @{ name = 'Rahul' }
$ankit = New-ApiResource '/users' @{ name = 'Ankit' }
$group = New-ApiResource '/groups' @{ name = 'Goa Trip' }
$groupId = $group.id

foreach ($person in @($mohit, $rahul, $ankit)) {
    New-ApiResource "/groups/$groupId/members" @{ user_id = $person.id } |
        Out-Null
}

$dinner = New-ApiResource '/expenses' @{
    group_id    = $groupId
    paid_by     = $mohit.id
    amount      = '1200.00'
    description = 'Dinner'
}

New-ApiResource '/expenses' @{
    group_id    = $groupId
    paid_by     = $rahul.id
    amount      = '300.00'
    description = 'Lunch'
} | Out-Null

"Goa Trip group ID: $groupId"
$dinner.shares | Format-Table user_id, amount

$history = Invoke-RestMethod "$api/groups/$groupId/expenses"
"History: $($history.description -join ', ')"

$search = Invoke-RestMethod "$api/groups/$groupId/expenses?search=dIn"
"Search [dIn]: $($search.description -join ', ')"

$result = Invoke-RestMethod "$api/groups/$groupId/balances"
$result.balances | Format-Table user_id, name, net_balance
$result.suggested_payments | Format-Table from_user_id, to_user_id, amount
```

Dinner has three shares of `400.00`. History shows `Lunch, Dinner`, and searching for `dIn` returns Dinner. After both expenses, Mohit’s net balance is `700.00`, Rahul’s is `-200.00`, and Ankit’s is `-500.00`. The suggested payments are Rahul → Mohit for `200.00` and Ankit → Mohit for `500.00`.

## Architecture

- `app/main.py` starts FastAPI, initializes the schema, and registers the route modules.
- `app/users.py` and `app/groups.py` handle users and group membership.
- `app/expenses.py` validates expense input and saves the expense and its shares in a single transaction.
- `app/history.py` reads a group’s expense history and applies the optional description search.
- `app/balances.py` calculates net balances and suggested payments.
- `app/models.py` defines the five SQLAlchemy tables. `app/database.py` configures SQLite and supplies one SQLAlchemy session per request.
- Pydantic models describe request and response data. FastAPI uses them to validate input and generate the API documentation.

## Database schema

| Table | Columns | Keys and constraints |
|---|---|---|
| `users` | `id`, `name` | `id` is the primary key. Users with the same name have distinct IDs. |
| `groups` | `id`, `name` | `id` is the primary key. |
| `group_members` | `group_id`, `user_id` | The pair is the primary key. Foreign keys reference `groups.id` and `users.id`. A user can belong to several groups and can join each group once. |
| `expenses` | `id`, `group_id`, `paid_by`, `amount_paise`, `description`, `created_at` | `id` is the primary key. `(group_id, paid_by)` references a membership in the same group. `(group_id, id)` is unique and is the target for the share table’s group-and-expense reference. The total is a positive integer. |
| `expense_shares` | `expense_id`, `user_id`, `group_id`, `share_paise` | `(expense_id, user_id)` is the primary key. Two-column foreign keys connect the share to an expense and a membership in the same group. The share is a nonnegative integer. |

SQLite enforces foreign keys on every application connection. The `group_id` on a share lets the database check that the expense and the participant belong to the same group. Saving each share at expense creation preserves the participant list and amounts even when someone joins later.

## Assumptions and design decisions

- All expenses use INR. Amounts are stored as integer paise to keep money arithmetic exact. The API accepts positive decimal strings with up to two decimal places.
- The payer belongs to the group and is included in the split. Whole paise are divided evenly first. Leftover paise go one at a time to members in ascending user ID order. For example, `100.00` split three ways is `33.34`, `33.33`, and `33.33`.
- A member’s net balance is the amount they paid minus their saved shares in that group. Positive balances should receive money, negative balances should pay, and zero balances are even. The group’s net balances sum to zero.
- Suggested payments match debtors and creditors in ascending user ID order. Each payment is the smaller of the debtor’s remaining debt and the creditor’s remaining credit. This clears at least one side per step and produces a consistent result for the same input. The balance endpoint is read-only.
- SQLite keeps local setup to one file. Creating missing tables at startup is convenient for this version. A larger deployment would benefit from versioned migrations and a database designed for more concurrent writers.

## Product enhancement — expense search

When a trip has many expenses, a member may remember part of a description but have trouble finding the bill. The `search` parameter lets them find it from the existing history endpoint. For example, `GET /groups/1/expenses?search=dIn` finds `Dinner` in group `1`.

The API trims the search term and compares descriptions using Unicode case folding. It matches literal text, so characters such as `%` and `_` keep their usual meaning. A missing or blank search returns the full history in the same order. The query scans descriptions within the selected group, which keeps the implementation straightforward for small histories. Larger groups could benefit from pagination and indexed search.

## Run the tests

From the repository root:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pytest -q tests
```

The seven tests cover user and group workflows, expense creation, rounding, validation, saved shares after a late join, independent group balances, suggested payments, and search. The API tests use temporary SQLite files with the same connection settings as the application.

## Possible improvements

- Add authentication and enforce group membership when viewing or changing group data.
- Record completed settlements so future balances reflect payments people have already made.
- Add pagination for long expense histories and versioned database migrations as the schema evolves.