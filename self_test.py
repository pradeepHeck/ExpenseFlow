"""ExpenseFlow local smoke test.
Run with: venv\\Scripts\\python.exe self_test.py
It uses a temporary SQLite database and does not modify database.db.
"""
import os, tempfile

root = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="expenseflow_test_")
os.environ["EXPENSEFLOW_DB"] = os.path.join(tmp, "test.db")
os.environ["EXPENSEFLOW_UPLOAD_DIR"] = os.path.join(tmp, "uploads")
os.environ["SECRET_KEY"] = "expenseflow-smoke-test-key"

from app import app, init_db

init_db()
app.config.update(TESTING=True)
client = app.test_client()


def check(label, response, expected=(200, 302)):
    if response.status_code not in expected:
        raise AssertionError(f"{label}: expected {expected}, got {response.status_code}")
    print(f"PASS  {label}: {response.status_code}")

# Public page
check("home", client.get("/"), (200, 302))

# Register + user login
email = "smoketest@example.com"
check("register", client.post("/register", data={
    "name": "Smoke Test User", "email": email,
    "password": "Test@12345", "confirm_password": "Test@12345"
}), (302,))
check("login user", client.post("/login", data={
    "email": email, "password": "Test@12345"
}), (302,))

# User pages
for path in [
    "/dashboard", "/income", "/income/add", "/expenses", "/expenses/add",
    "/transactions", "/budgets", "/recurring", "/categories", "/reports",
    "/notifications", "/profile", "/report", "/expenses/export",
    "/export/income", "/export/expenses",
]:
    check(path, client.get(path), (200, 302))

# Create income
check("add income", client.post("/income/add", data={
    "source": "Smoke Salary", "category": "Salary", "amount": "10000",
    "income_date": "2026-09-03", "payment_method": "Bank",
    "description": "Smoke test"
}), (302,))

# Create expense
check("add expense", client.post("/expenses/add", data={
    "title": "Smoke Office Expense", "category": "Office", "amount": "1500",
    "expense_date": "2026-09-03", "payment_method": "UPI",
    "description": "Smoke test"
}), (302,))

# Admin login in a fresh client
admin = app.test_client()
check("login admin", admin.post("/login", data={
    "email": "admin@expenseflow.local", "password": "Admin@12345"
}), (302,))
for path in ["/admin", "/admin/users", "/admin/transactions", "/admin/logs", "/admin/reports"]:
    check("admin " + path, admin.get(path), (200, 302))

print("\nALL SMOKE TESTS PASSED")
print("Temporary test data:", tmp)
