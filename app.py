import os, sqlite3, csv, io, json, secrets
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.environ.get('EXPENSEFLOW_DB', os.path.join(BASE_DIR, 'database.db'))
UPLOAD_DIR = os.environ.get('EXPENSEFLOW_UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png','jpg','jpeg','webp','pdf'}


def db():
    c = sqlite3.connect(DATABASE)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys = ON')
    return c


def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def init_db():
    c = db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'user', active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS categories(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'expense', user_id INTEGER,
      UNIQUE(name, kind, user_id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS income(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      source TEXT NOT NULL, category TEXT, amount REAL NOT NULL CHECK(amount>0),
      income_date TEXT NOT NULL, payment_method TEXT, description TEXT,
      created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS expenses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      title TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL CHECK(amount>0),
      expense_date TEXT NOT NULL, description TEXT, payment_method TEXT,
      receipt TEXT, created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS budgets(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      name TEXT NOT NULL, category TEXT, amount REAL NOT NULL CHECK(amount>0),
      month TEXT NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(user_id,name,month), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS recurring_expenses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      title TEXT NOT NULL, category TEXT NOT NULL, amount REAL NOT NULL CHECK(amount>0),
      frequency TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT,
      payment_method TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      title TEXT NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS activity_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
      action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL);
    ''')
    # Safe schema migration for databases created by older ExpenseFlow versions.
    # SQLite CREATE TABLE IF NOT EXISTS does not add missing columns to an existing table,
    # so we explicitly add every column used by the current application.
    migrations = {
        'users': {
            'role': "TEXT NOT NULL DEFAULT 'user'",
            'active': 'INTEGER NOT NULL DEFAULT 1',
        },
        'categories': {
            'kind': "TEXT NOT NULL DEFAULT 'expense'",
            'user_id': 'INTEGER',
        },
        'income': {
            'category': "TEXT DEFAULT ''",
            'payment_method': "TEXT DEFAULT ''",
        },
        'expenses': {
            'receipt': "TEXT DEFAULT ''",
            'status': "TEXT NOT NULL DEFAULT 'approved'",
        },
        'budgets': {
            'category': "TEXT DEFAULT ''",
        },
        'recurring_expenses': {
            'end_date': "TEXT DEFAULT ''",
            'payment_method': "TEXT DEFAULT ''",
            'active': 'INTEGER NOT NULL DEFAULT 1',
        },
        'notifications': {
            'is_read': 'INTEGER NOT NULL DEFAULT 0',
        },
        'activity_logs': {
            'user_id': 'INTEGER',
            'details': "TEXT DEFAULT ''",
        },
    }
    for table, wanted in migrations.items():
        existing = {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
        for column, definition in wanted.items():
            if column not in existing:
                c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')

    defaults = [('Office','expense'),('Travel','expense'),('Food','expense'),('Utilities','expense'),('Salary','expense'),('Marketing','expense'),('Equipment','expense'),('Software','expense'),('Rent','expense'),('Other','expense'),('Salary','income'),('Sales','income'),('Investment','income'),('Other','income')]
    for n,k in defaults:
        try: c.execute('INSERT INTO categories(name,kind,user_id) VALUES(?,?,NULL)',(n,k))
        except sqlite3.IntegrityError: pass
    admin_email = os.environ.get('ADMIN_EMAIL','admin@expenseflow.local').strip().lower()
    admin_pass = os.environ.get('ADMIN_PASSWORD','Admin@12345')
    if not c.execute('SELECT id FROM users WHERE role="admin" LIMIT 1').fetchone():
        existing_admin_email = c.execute('SELECT id FROM users WHERE email=?',(admin_email,)).fetchone()
        if existing_admin_email:
            # Keep an existing local database usable when the old default email
            # already exists, instead of crashing on the UNIQUE email constraint.
            c.execute('UPDATE users SET role="admin", active=1 WHERE id=?',(existing_admin_email['id'],))
        else:
            c.execute('INSERT INTO users(name,email,password,role,active,created_at) VALUES(?,?,?,?,1,?)',('System Admin',admin_email,generate_password_hash(admin_pass),'admin',now()))
    c.commit(); c.close()


def log(action, details='', user_id=None):
    c=db(); c.execute('INSERT INTO activity_logs(user_id,action,details,created_at) VALUES(?,?,?,?)',(user_id or session.get('user_id'),action,details,now())); c.commit(); c.close()


def notify(user_id,title,message):
    c=db(); c.execute('INSERT INTO notifications(user_id,title,message,created_at) VALUES(?,?,?,?)',(user_id,title,message,now())); c.commit(); c.close()


def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get('user_id'): flash('Please sign in first.','warning'); return redirect(url_for('home'))
        c=db(); u=c.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone(); c.close()
        if not u or not u['active']: session.clear(); flash('Your account is inactive.','danger'); return redirect(url_for('home'))
        return f(*a,**kw)
    return w


def admin_required(f):
    @wraps(f)
    @login_required
    def w(*a,**kw):
        if session.get('role')!='admin': abort(403)
        return f(*a,**kw)
    return w


def current_user():
    if not session.get('user_id'): return None
    c=db(); u=c.execute('SELECT id,name,email,role,active,created_at FROM users WHERE id=?',(session['user_id'],)).fetchone(); c.close(); return u


def allowed_file(name): return '.' in name and name.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS


def categories_for(uid, kind='expense'):
    """Return global + user categories with case-insensitive de-duplication."""
    c = db()
    rows = c.execute(
        '''SELECT id, name, kind, user_id
           FROM categories
           WHERE kind=? AND (user_id IS NULL OR user_id=?)
           ORDER BY LOWER(name), user_id IS NOT NULL, id''',
        (kind, uid),
    ).fetchall()
    c.close()
    seen = set()
    result = []
    for row in rows:
        key = row['name'].strip().casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(row)
    return result

@app.context_processor
def inject():
    unread=0
    if session.get('user_id'):
        c=db(); unread=c.execute('SELECT COUNT(*) n FROM notifications WHERE user_id=? AND is_read=0',(session['user_id'],)).fetchone()['n']; c.close()
    return {'current_user':current_user(),'unread_notifications':unread,'year':datetime.now().year}

@app.route('/')
def home(): return redirect(url_for('dashboard')) if session.get('user_id') else render_template('auth.html')

@app.post('/register')
def register():
    name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); pw=request.form.get('password',''); cp=request.form.get('confirm_password','')
    if len(name)<2 or '@' not in email or len(pw)<8: flash('Enter a valid name, email and password (8+ characters).','danger'); return redirect(url_for('home')+'#register')
    if pw!=cp: flash('Passwords do not match.','danger'); return redirect(url_for('home')+'#register')
    c=db()
    try:
        cur=c.execute('INSERT INTO users(name,email,password,role,active,created_at) VALUES(?,?,?,?,1,?)',(name,email,generate_password_hash(pw),'user',now()))
        uid=cur.lastrowid; c.commit()
    except sqlite3.IntegrityError: c.close(); flash('Email already registered.','danger'); return redirect(url_for('home')+'#register')
    c.close(); log('User registered',email,uid); flash('Account created. You can sign in now.','success'); return redirect(url_for('home')+'#login')

@app.post('/login')
def login():
    email=request.form.get('email','').strip().lower(); pw=request.form.get('password',''); c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); c.close()
    if u and u['active'] and check_password_hash(u['password'],pw):
        session.clear(); session.update(user_id=u['id'],user_name=u['name'],role=u['role']); log('Login',email,u['id']); return redirect(url_for('admin_dashboard' if u['role']=='admin' else 'dashboard'))
    flash('Invalid credentials or inactive account.','danger'); return redirect(url_for('home')+'#login')

@app.get('/logout')
def logout(): log('Logout'); session.clear(); flash('You have been logged out.','success'); return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    uid=session['user_id']; c=db()
    totals=c.execute('SELECT COALESCE((SELECT SUM(amount) FROM income WHERE user_id=?),0) income, COALESCE((SELECT SUM(amount) FROM expenses WHERE user_id=?),0) expense',(uid,uid)).fetchone()
    counts=c.execute('SELECT (SELECT COUNT(*) FROM income WHERE user_id=?) income_count,(SELECT COUNT(*) FROM expenses WHERE user_id=?) expense_count',(uid,uid)).fetchone()
    recent=c.execute('SELECT id,title,category,amount,expense_date FROM expenses WHERE user_id=? ORDER BY expense_date DESC,id DESC LIMIT 6',(uid,)).fetchall()
    cats=[dict(r) for r in c.execute('SELECT category,SUM(amount) total FROM expenses WHERE user_id=? GROUP BY category ORDER BY total DESC LIMIT 8',(uid,)).fetchall()]
    monthly=[dict(r) for r in c.execute("SELECT substr(expense_date,1,7) month,SUM(amount) total FROM expenses WHERE user_id=? GROUP BY month ORDER BY month DESC LIMIT 6",(uid,)).fetchall()[::-1]]
    month=date.today().strftime('%Y-%m'); b=c.execute('SELECT COALESCE(SUM(amount),0) amount FROM budgets WHERE user_id=? AND month=?',(uid,month)).fetchone()['amount']; used=c.execute('SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE user_id=? AND substr(expense_date,1,7)=?',(uid,month)).fetchone()['total']; c.close()
    return render_template('dashboard.html',income=totals['income'],expense=totals['expense'],balance=totals['income']-totals['expense'],income_count=counts['income_count'],expense_count=counts['expense_count'],recent=recent,cats=cats,monthly=monthly,budget=b,used=used)

@app.route('/income')
@login_required
def income():
    uid=session['user_id']; q=request.args.get('search','').strip(); start=request.args.get('start_date',''); end=request.args.get('end_date',''); c=db(); sql='SELECT * FROM income WHERE user_id=?'; p=[uid]
    if q: sql+=' AND (source LIKE ? OR category LIKE ? OR description LIKE ?)'; v=f'%{q}%'; p += [v,v,v]
    if start: sql+=' AND income_date>=?'; p.append(start)
    if end: sql+=' AND income_date<=?'; p.append(end)
    rows=c.execute(sql+' ORDER BY income_date DESC,id DESC',p).fetchall(); c.close(); return render_template('income.html',rows=rows,search=q,start=start,end=end)

@app.route('/income/add',methods=['GET','POST'])
@login_required
def add_income():
    if request.method=='POST':
        source=request.form.get('source','').strip(); amount=request.form.get('amount',''); dt=request.form.get('income_date',''); category=request.form.get('category','').strip(); payment=request.form.get('payment_method',''); desc=request.form.get('description','').strip()
        try: amount=float(amount); assert amount>0
        except: flash('Enter a valid positive amount.','danger'); return redirect(url_for('add_income'))
        if not source or not dt: flash('Source and date are required.','danger'); return redirect(url_for('add_income'))
        c=db(); c.execute('INSERT INTO income(user_id,source,category,amount,income_date,payment_method,description,created_at) VALUES(?,?,?,?,?,?,?,?)',(session['user_id'],source,category,amount,dt,payment,desc,now())); c.commit(); c.close(); log('Income added',source); notify(session['user_id'],'Income recorded',f'₹{amount:,.2f} income was added.'); flash('Income added successfully.','success'); return redirect(url_for('income'))
    return render_template('add_income.html',categories=categories_for(session['user_id'],'income'),today=date.today().isoformat())

@app.route('/income/edit/<int:item_id>',methods=['GET','POST'])
@login_required
def edit_income(item_id):
    c=db(); row=c.execute('SELECT * FROM income WHERE id=? AND user_id=?',(item_id,session['user_id'])).fetchone(); c.close()
    if not row: abort(404)
    if request.method=='POST':
        source=request.form.get('source','').strip(); cat=request.form.get('category','').strip(); dt=request.form.get('income_date',''); payment=request.form.get('payment_method',''); desc=request.form.get('description','').strip()
        try: amount=float(request.form.get('amount','')); assert amount>0
        except: flash('Enter a valid amount.','danger'); return redirect(url_for('edit_income',item_id=item_id))
        if not source or not dt: flash('Source and date are required.','danger'); return redirect(url_for('edit_income',item_id=item_id))
        c=db(); c.execute('UPDATE income SET source=?,category=?,amount=?,income_date=?,payment_method=?,description=? WHERE id=? AND user_id=?',(source,cat,amount,dt,payment,desc,item_id,session['user_id'])); c.commit(); c.close(); log('Income edited',source); flash('Income updated.','success'); return redirect(url_for('income'))
    return render_template('edit_income.html',income=row,categories=categories_for(session['user_id'],'income'))

@app.post('/income/delete/<int:item_id>')
@login_required
def delete_income(item_id):
    c=db(); row=c.execute('SELECT * FROM income WHERE id=? AND user_id=?',(item_id,session['user_id'])).fetchone();
    if row: c.execute('DELETE FROM income WHERE id=?',(item_id,)); c.commit(); log('Income deleted',row['source']); flash('Income deleted.','success')
    c.close(); return redirect(url_for('income'))

@app.route('/expenses')
@login_required
def expenses():
    uid=session['user_id']; q=request.args.get('search','').strip(); cat=request.args.get('category',''); start=request.args.get('start_date',''); end=request.args.get('end_date',''); c=db(); sql='SELECT * FROM expenses WHERE user_id=?'; p=[uid]
    if q: sql+=' AND (title LIKE ? OR category LIKE ? OR description LIKE ?)'; v=f'%{q}%'; p += [v,v,v]
    if cat: sql+=' AND category=?'; p.append(cat)
    if start: sql+=' AND expense_date>=?'; p.append(start)
    if end: sql+=' AND expense_date<=?'; p.append(end)
    rows=c.execute(sql+' ORDER BY expense_date DESC,id DESC',p).fetchall(); c.close(); return render_template('expenses.html',rows=rows,categories=categories_for(uid),search=q,cat=cat,start=start,end=end)

@app.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    uid = session['user_id']

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        amount_raw = request.form.get('amount', '').strip()
        expense_date = request.form.get('expense_date', '').strip()
        payment_method = request.form.get('payment_method', '').strip()
        description = request.form.get('description', '').strip()
        file = request.files.get('receipt')

        if not title or not category or not expense_date:
            flash('Title, category and date are required.', 'danger')
            return redirect(url_for('add_expense'))

        try:
            amount = float(amount_raw)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            flash('Enter a valid positive amount.', 'danger')
            return redirect(url_for('add_expense'))

        # Only allow categories available to this user.
        valid_categories = {r['name'] for r in categories_for(uid, 'expense')}
        if category not in valid_categories:
            flash('Please select a valid expense category.', 'danger')
            return redirect(url_for('add_expense'))

        receipt = None
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('Receipt must be PDF, PNG, JPG, JPEG or WEBP.', 'danger')
                return redirect(url_for('add_expense'))
            safe_name = secure_filename(file.filename)
            if not safe_name:
                flash('Invalid receipt filename.', 'danger')
                return redirect(url_for('add_expense'))
            receipt = f"{uid}_{secrets.token_hex(8)}_{safe_name}"
            file.save(os.path.join(UPLOAD_DIR, receipt))

        c = db()
        c.execute(
            '''INSERT INTO expenses
               (user_id, title, category, amount, expense_date, description,
                payment_method, receipt, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (uid, title, category, amount, expense_date, description,
             payment_method, receipt, now(), 'approved'),
        )
        c.commit()
        c.close()

        log('Expense added', title, uid)
        notify(uid, 'Expense recorded', f'₹{amount:,.2f} spent on {title}.')
        flash('Expense added successfully.', 'success')
        return redirect(url_for('expenses'))

    return render_template(
        'add_expense.html',
        categories=categories_for(uid, 'expense'),
        today=date.today().isoformat(),
    )


@app.route('/expenses/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(item_id):
    uid = session['user_id']
    c = db()
    row = c.execute(
        'SELECT * FROM expenses WHERE id=? AND user_id=?',
        (item_id, uid),
    ).fetchone()
    c.close()

    if not row:
        abort(404)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '').strip()
        amount_raw = request.form.get('amount', '').strip()
        expense_date = request.form.get('expense_date', '').strip()
        payment_method = request.form.get('payment_method', '').strip()
        description = request.form.get('description', '').strip()
        file = request.files.get('receipt')

        if not title or not category or not expense_date:
            flash('Title, category and date are required.', 'danger')
            return redirect(url_for('edit_expense', item_id=item_id))

        try:
            amount = float(amount_raw)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            flash('Enter a valid positive amount.', 'danger')
            return redirect(url_for('edit_expense', item_id=item_id))

        valid_categories = {r['name'] for r in categories_for(uid, 'expense')}
        if category not in valid_categories:
            flash('Please select a valid expense category.', 'danger')
            return redirect(url_for('edit_expense', item_id=item_id))

        receipt = row['receipt']
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('Receipt must be PDF, PNG, JPG, JPEG or WEBP.', 'danger')
                return redirect(url_for('edit_expense', item_id=item_id))

            safe_name = secure_filename(file.filename)
            if not safe_name:
                flash('Invalid receipt filename.', 'danger')
                return redirect(url_for('edit_expense', item_id=item_id))

            new_receipt = f"{uid}_{secrets.token_hex(8)}_{safe_name}"
            file.save(os.path.join(UPLOAD_DIR, new_receipt))

            if receipt:
                old_path = os.path.join(UPLOAD_DIR, receipt)
                try:
                    os.remove(old_path)
                except OSError:
                    pass

            receipt = new_receipt

        c = db()
        c.execute(
            '''UPDATE expenses
               SET title=?, category=?, amount=?, expense_date=?,
                   payment_method=?, description=?, receipt=?
               WHERE id=? AND user_id=?''',
            (title, category, amount, expense_date, payment_method,
             description, receipt, item_id, uid),
        )
        c.commit()
        c.close()

        log('Expense edited', title, uid)
        notify(uid, 'Expense updated', f'Expense "{title}" was updated.')
        flash('Expense updated successfully.', 'success')
        return redirect(url_for('expenses'))

    return render_template(
        'edit_expense.html',
        expense=row,
        categories=categories_for(uid, 'expense'),
    )


@app.post('/expenses/delete/<int:item_id>')
@login_required
def delete_expense(item_id):
    c=db(); row=c.execute('SELECT * FROM expenses WHERE id=? AND user_id=?',(item_id,session['user_id'])).fetchone();
    if row:
        if row['receipt']:
            try: os.remove(os.path.join(UPLOAD_DIR,row['receipt']))
            except OSError: pass
        c.execute('DELETE FROM expenses WHERE id=?',(item_id,)); c.commit(); log('Expense deleted',row['title']); flash('Expense deleted.','success')
    c.close(); return redirect(url_for('expenses'))

@app.get('/receipt/<path:filename>')
@login_required
def receipt(filename):
    c=db(); ok=c.execute('SELECT id FROM expenses WHERE user_id=? AND receipt=?',(session['user_id'],filename)).fetchone(); c.close()
    if not ok and session.get('role')!='admin': abort(403)
    return send_from_directory(UPLOAD_DIR,filename,as_attachment=False)

@app.route('/budgets',methods=['GET','POST'])
@login_required
def budgets():
    uid=session['user_id']; c=db()
    if request.method=='POST':
        name=request.form.get('name','').strip(); cat=request.form.get('category','').strip() or None; month=request.form.get('month','');
        try: amount=float(request.form.get('amount','')); assert amount>0
        except: c.close(); flash('Enter a valid budget amount.','danger'); return redirect(url_for('budgets'))
        try: c.execute('INSERT INTO budgets(user_id,name,category,amount,month,created_at) VALUES(?,?,?,?,?,?)',(uid,name,cat,amount,month,now())); c.commit(); log('Budget created',name); flash('Budget created.','success')
        except sqlite3.IntegrityError: flash('A budget with this name already exists for that month.','danger')
    rows=c.execute('SELECT * FROM budgets WHERE user_id=? ORDER BY month DESC,id DESC',(uid,)).fetchall(); c.close(); return render_template('budgets.html',rows=rows,categories=categories_for(uid),current_month=date.today().strftime('%Y-%m'))

@app.post('/budgets/delete/<int:item_id>')
@login_required
def delete_budget(item_id):
    c=db(); c.execute('DELETE FROM budgets WHERE id=? AND user_id=?',(item_id,session['user_id'])); c.commit(); c.close(); flash('Budget deleted.','success'); return redirect(url_for('budgets'))

@app.route('/recurring',methods=['GET','POST'])
@login_required
def recurring():
    uid=session['user_id']; c=db()
    if request.method=='POST':
        title=request.form.get('title','').strip(); cat=request.form.get('category','').strip(); freq=request.form.get('frequency','Monthly'); start=request.form.get('start_date',''); end=request.form.get('end_date') or None; payment=request.form.get('payment_method','')
        try: amount=float(request.form.get('amount','')); assert amount>0
        except: c.close(); flash('Enter a valid amount.','danger'); return redirect(url_for('recurring'))
        c.execute('INSERT INTO recurring_expenses(user_id,title,category,amount,frequency,start_date,end_date,payment_method,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(uid,title,cat,amount,freq,start,end,payment,now())); c.commit(); log('Recurring expense created',title); flash('Recurring expense added.','success')
    rows=c.execute('SELECT * FROM recurring_expenses WHERE user_id=? ORDER BY active DESC,id DESC',(uid,)).fetchall(); c.close(); return render_template('recurring.html',rows=rows,categories=categories_for(uid),today=date.today().isoformat())

@app.post('/recurring/toggle/<int:item_id>')
@login_required
def recurring_toggle(item_id):
    c=db(); c.execute('UPDATE recurring_expenses SET active=1-active WHERE id=? AND user_id=?',(item_id,session['user_id'])); c.commit(); c.close(); return redirect(url_for('recurring'))

@app.post('/recurring/delete/<int:item_id>')
@login_required
def recurring_delete(item_id):
    c=db(); c.execute('DELETE FROM recurring_expenses WHERE id=? AND user_id=?',(item_id,session['user_id'])); c.commit(); c.close(); flash('Recurring expense deleted.','success'); return redirect(url_for('recurring'))

@app.route('/categories',methods=['GET','POST'])
@login_required
def categories():
    uid=session['user_id']; c=db()
    if request.method=='POST':
        name=request.form.get('name','').strip(); kind=request.form.get('kind','expense')
        if name and kind in ('expense','income'):
            existing = c.execute(
                'SELECT 1 FROM categories WHERE kind=? AND LOWER(name)=LOWER(?) AND (user_id IS NULL OR user_id=?) LIMIT 1',
                (kind, name, uid),
            ).fetchone()
            if existing:
                flash('Category already exists.', 'danger')
            else:
                c.execute(
                    'INSERT INTO categories(name,kind,user_id) VALUES(?,?,?)',
                    (name, kind, uid),
                )
                c.commit()
                flash('Category added.', 'success')
    rows=c.execute('SELECT * FROM categories WHERE user_id=? ORDER BY kind,name',(uid,)).fetchall(); c.close(); return render_template('categories.html',rows=rows)

@app.post('/categories/delete/<int:item_id>')
@login_required
def category_delete(item_id):
    c=db(); c.execute('DELETE FROM categories WHERE id=? AND user_id=?',(item_id,session['user_id'])); c.commit(); c.close(); flash('Category deleted.','success'); return redirect(url_for('categories'))

@app.get('/transactions')
@login_required
def transactions():
    uid=session['user_id']; c=db(); rows=c.execute('''SELECT expense_date dt,title label,category,amount,'Expense' type,payment_method FROM expenses WHERE user_id=? UNION ALL SELECT income_date dt,source label,category,amount,'Income' type,payment_method FROM income WHERE user_id=? ORDER BY dt DESC''',(uid,uid)).fetchall(); c.close(); return render_template('transactions.html',rows=rows)

@app.get('/report')
@login_required
def legacy_report():
    return redirect(url_for('reports'))

@app.get('/expenses/export')
@login_required
def legacy_expense_export():
    return redirect(url_for('export', kind='expenses'))

@app.get('/reports')
@login_required
def reports():
    uid=session['user_id']; c=db(); monthly=[dict(r) for r in c.execute("SELECT substr(expense_date,1,7) month,SUM(amount) expense FROM expenses WHERE user_id=? GROUP BY month ORDER BY month",(uid,)).fetchall()]; cats=[dict(r) for r in c.execute('SELECT category,SUM(amount) total FROM expenses WHERE user_id=? GROUP BY category ORDER BY total DESC',(uid,)).fetchall()]; inc=[dict(r) for r in c.execute("SELECT substr(income_date,1,7) month,SUM(amount) total FROM income WHERE user_id=? GROUP BY month ORDER BY month",(uid,)).fetchall()]; c.close(); return render_template('reports.html',monthly=monthly,cats=cats,inc=inc)

@app.get('/export/<kind>')
@login_required
def export(kind):
    uid=session['user_id']; c=db(); out=io.StringIO(); w=csv.writer(out)
    if kind=='expenses': rows=c.execute('SELECT title,category,amount,expense_date,payment_method,description FROM expenses WHERE user_id=? ORDER BY expense_date DESC',(uid,)).fetchall(); w.writerow(['Title','Category','Amount','Date','Payment Method','Description'])
    elif kind=='income': rows=c.execute('SELECT source,category,amount,income_date,payment_method,description FROM income WHERE user_id=? ORDER BY income_date DESC',(uid,)).fetchall(); w.writerow(['Source','Category','Amount','Date','Payment Method','Description'])
    else: rows=[]
    for r in rows: w.writerow(list(r))
    c.close(); return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename={kind}.csv'})

@app.get('/notifications')
@login_required
def notifications():
    c=db(); rows=c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC',(session['user_id'],)).fetchall(); c.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(session['user_id'],)); c.commit(); c.close(); return render_template('notifications.html',rows=rows)

@app.post('/notifications/clear')
@login_required
def clear_notifications():
    c=db(); c.execute('DELETE FROM notifications WHERE user_id=?',(session['user_id'],)); c.commit(); c.close(); return redirect(url_for('notifications'))

@app.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    uid=session['user_id']; c=db(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if request.method=='POST':
        name=request.form.get('name','').strip(); old=request.form.get('old_password',''); new=request.form.get('new_password','')
        if name: c.execute('UPDATE users SET name=? WHERE id=?',(name,uid)); session['user_name']=name
        if new:
            if not old or not check_password_hash(u['password'],old) or len(new)<8: c.close(); flash('Current password is incorrect or new password is too short.','danger'); return redirect(url_for('profile'))
            c.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(new),uid))
        c.commit(); c.close(); log('Profile updated'); flash('Profile updated successfully.','success'); return redirect(url_for('profile'))
    c.close(); return render_template('profile.html',user=u)

@app.get('/admin')
@admin_required
def admin_dashboard():
    c=db(); stats=c.execute('SELECT COUNT(*) users, SUM(active) active FROM users').fetchone(); fin=c.execute('SELECT COALESCE((SELECT SUM(amount) FROM income),0) income,COALESCE((SELECT SUM(amount) FROM expenses),0) expense').fetchone(); cats=[dict(r) for r in c.execute('SELECT category,SUM(amount) total FROM expenses GROUP BY category ORDER BY total DESC LIMIT 8').fetchall()]; recent=c.execute('SELECT l.*,u.name FROM activity_logs l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 10').fetchall(); c.close(); return render_template('admin_dashboard.html',stats=stats,fin=fin,cats=cats,recent=recent)

@app.get('/admin/users')
@admin_required
def admin_users():
    q=request.args.get('search','').strip(); c=db(); sql='SELECT id,name,email,role,active,created_at FROM users'; p=[]
    if q: sql+=' WHERE name LIKE ? OR email LIKE ?'; v=f'%{q}%'; p=[v,v]
    rows=c.execute(sql+' ORDER BY id DESC',p).fetchall(); c.close(); return render_template('admin_users.html',rows=rows,search=q)

@app.post('/admin/users/toggle/<int:user_id>')
@admin_required
def admin_toggle_user(user_id):
    if user_id==session['user_id']: flash('You cannot deactivate your own admin account.','danger'); return redirect(url_for('admin_users'))
    c=db(); c.execute('UPDATE users SET active=1-active WHERE id=? AND role<>"admin"',(user_id,)); c.commit(); c.close(); log('User status changed',str(user_id)); flash('User status updated.','success'); return redirect(url_for('admin_users'))

@app.post('/admin/users/delete/<int:user_id>')
@admin_required
def admin_delete_user(user_id):
    if user_id==session['user_id']: flash('You cannot delete yourself.','danger'); return redirect(url_for('admin_users'))
    c=db(); c.execute('DELETE FROM users WHERE id=? AND role<>"admin"',(user_id,)); c.commit(); c.close(); log('User deleted',str(user_id)); flash('User deleted.','success'); return redirect(url_for('admin_users'))

@app.get('/admin/transactions')
@admin_required
def admin_transactions():
    c=db(); rows=c.execute('''SELECT e.id,u.name,e.title label,e.category,e.amount,e.expense_date dt,e.status,'Expense' type FROM expenses e JOIN users u ON u.id=e.user_id UNION ALL SELECT i.id,u.name,i.source label,i.category,i.amount,i.income_date dt,'approved' status,'Income' type FROM income i JOIN users u ON u.id=i.user_id ORDER BY dt DESC''').fetchall(); c.close(); return render_template('admin_transactions.html',rows=rows)

@app.get('/admin/logs')
@admin_required
def admin_logs():
    c=db(); rows=c.execute('SELECT l.*,u.name FROM activity_logs l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 200').fetchall(); c.close(); return render_template('admin_logs.html',rows=rows)

@app.post('/admin/expenses/<int:item_id>/status/<status>')
@admin_required
def admin_expense_status(item_id, status):
    if status not in ('approved', 'rejected', 'pending'):
        abort(400)
    c = db()
    row = c.execute('SELECT user_id, title FROM expenses WHERE id=?', (item_id,)).fetchone()
    if not row:
        c.close()
        abort(404)
    c.execute('UPDATE expenses SET status=? WHERE id=?', (status, item_id))
    c.commit()
    c.close()
    notify(row['user_id'], 'Expense status updated', f'"{row["title"]}" is now {status}.')
    log('Expense status changed', f'{item_id}: {status}')
    flash(f'Expense marked {status}.', 'success')
    return redirect(url_for('admin_transactions'))

@app.get('/admin/reports')
@admin_required
def admin_reports():
    c=db(); monthly=[dict(r) for r in c.execute("SELECT substr(expense_date,1,7) month,SUM(amount) total FROM expenses GROUP BY month ORDER BY month").fetchall()]; users=c.execute('SELECT u.name,COALESCE((SELECT SUM(amount) FROM expenses e WHERE e.user_id=u.id),0) expense FROM users u WHERE u.role="user" ORDER BY expense DESC').fetchall(); c.close(); return render_template('admin_reports.html',monthly=monthly,users=users)

@app.errorhandler(403)
def forbidden(e): return render_template('error.html',code=403,message='You do not have permission to access this page.'),403
@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='The page you requested was not found.'),404
@app.errorhandler(500)
def server_error(e): return render_template('error.html',code=500,message='Something went wrong. Please try again.'),500

init_db()
if __name__=='__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG','0')=='1')
