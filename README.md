# ExpenseFlow — Professional Business Expense Management System

A full-stack Flask application using **HTML, CSS, JavaScript, Python and SQLite**, upgraded from the supplied ExpenseFlow project.

## Features
- User registration/login with hashed passwords
- Admin/User role-based access control
- Professional responsive dashboard
- Income and expense CRUD
- Combined transactions ledger
- Search/filter for financial records
- Monthly and category analytics with Chart.js
- Budgets
- Recurring expense scheduling records
- Custom categories
- Receipt upload with authorization checks
- Notifications
- Profile and password change
- Admin dashboard, user management, system transactions, reports and audit logs
- CSV export
- Friendly 403/404/500 pages
- Smooth micro-interactions and reduced-motion support

## Run on Windows
Open PowerShell **inside `business_expense_management_pro`**:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open: `http://127.0.0.1:5000`

## Admin demo account
For local development, if no admin exists on a fresh database, the app creates:

- Email: `admin@expenseflow.local`
- Password: `Admin@12345`

**Change this before any public deployment.** Set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `SECRET_KEY` as environment variables.

PowerShell example:

```powershell
$env:SECRET_KEY="replace-with-a-long-random-secret"
$env:ADMIN_EMAIL="your-admin@example.com"
$env:ADMIN_PASSWORD="Use-a-strong-password-here"
python app.py
```

## Database
SQLite is created automatically as `database.db` beside `app.py`. The schema uses foreign keys and separate tables for users, categories, income, expenses, budgets, recurring expenses, notifications and audit logs.

**Existing-project compatibility:** the application includes a safe startup migration for older ExpenseFlow databases. Missing columns used by the current version (such as user roles, active status, receipt/status fields, income category/payment method and budget/recurring fields) are added automatically without deleting existing records.

## Production notes
- Use PostgreSQL for a multi-user production deployment.
- Use a production WSGI server such as Gunicorn on Linux hosting.
- Set a strong `SECRET_KEY`.
- Set a strong unique admin password.
- Put HTTPS in front of the application.
- Keep the `uploads` directory protected by the web server and application authorization.
- Do not commit `database.db`, `.env`, passwords or uploaded receipts to source control.

## Quick start
You can also double-click `run.bat` on Windows. It creates a virtual environment if needed, installs the requirements and starts ExpenseFlow.
