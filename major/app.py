import os
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, session, redirect, url_for
from werkzeug.utils import secure_filename
from sklearn.cluster import KMeans
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_analytics_master_key')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
DB_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'smart_commerce.db'))
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_ist_time():
    ist_time = datetime.utcnow() + timedelta(hours=5, minutes=30)
    return ist_time.strftime("%Y-%m-%d %H:%M:%S")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'vendor', 'customer'))
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER,
                name TEXT NOT NULL,
                domain_category TEXT,
                selling_price REAL NOT NULL,
                cost_price REAL NOT NULL, 
                stock INTEGER DEFAULT 10,
                image_url TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                total_amount REAL,
                created_at DATETIME
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                product_id INTEGER,
                qty INTEGER,
                price_sold REAL,
                cost_at_sale REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recently_viewed (
                view_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER,
                viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                cart_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_id INTEGER,
                qty INTEGER DEFAULT 1,
                UNIQUE(user_id, product_id)
            )
        """)
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO users (username, password, role) VALUES ('admin', 'admin123', 'admin')")
        conn.commit()
    seed_data()


def seed_data():
    """Adds a demo vendor and starter products the first time the app runs."""
    with get_db() as conn:
        c = conn.cursor()
        if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
            return
        c.execute("SELECT user_id FROM users WHERE username = 'vendor1'")
        row = c.fetchone()
        if row:
            vid = row[0]
        else:
            c.execute("INSERT INTO users (username, password, role) VALUES ('vendor1', 'vendor123', 'vendor')")
            vid = c.lastrowid
        products = [
            # name, category, selling, cost, stock, image
            ("Wireless Mouse", "Electronics", 799, 450, 40, "wireless_mouse"),
            ("Bluetooth Headphones", "Electronics", 2499, 1600, 25, "headphones"),
            ("Smart Watch", "Electronics", 3999, 2700, 15, "smartwatch"),
            ("Power Bank 10000mAh", "Electronics", 1299, 800, 50, "powerbank"),
            ("Men's Cotton T-Shirt", "Fashion", 599, 280, 60, "tshirt"),
            ("Running Shoes", "Fashion", 2199, 1300, 30, "shoes"),
            ("Denim Jacket", "Fashion", 2799, 1700, 20, "jacket"),
            ("Backpack 30L", "Fashion", 1499, 850, 35, "backpack"),
            ("Stainless Steel Water Bottle", "Home & Kitchen", 449, 220, 80, "bottle"),
            ("Non-Stick Frying Pan", "Home & Kitchen", 999, 580, 28, "pan"),
            ("LED Desk Lamp", "Home & Kitchen", 899, 500, 32, "lamp"),
            ("Python Programming Book", "Books", 549, 300, 45, "book"),
            ("Data Science Handbook", "Books", 699, 400, 38, "book2"),
            ("Yoga Mat", "Sports", 699, 350, 42, "yogamat"),
            ("Badminton Racket Set", "Sports", 1199, 700, 22, "racket"),
        ]
        for name, cat, sp, cp, stock, img in products:
            c.execute("INSERT INTO products (vendor_id, name, domain_category, selling_price, cost_price, stock, image_url) VALUES (?,?,?,?,?,?,?)",
                      (vid, name, cat, sp, cp, stock, f"/static/products/{img}.svg"))
        conn.commit()

# ==========================================
# MACHINE LEARNING ENGINE
# ==========================================
def get_customer_segment(user_id):
    try:
        conn = get_db()
        query = "SELECT customer_id, SUM(total_amount) as total_spent, COUNT(order_id) as freq FROM orders GROUP BY customer_id"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if len(df) < 3: 
            return "New/Standard Buyer" 
            
        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        df['raw_cluster'] = kmeans.fit_predict(df[['total_spent', 'freq']])
        
        # Calculate cluster worth and rank them logically
        cluster_means = df.groupby('raw_cluster')['total_spent'].mean().sort_values(ascending=False)
        tier_mapping = {cluster_id: f"Segment Tier {rank}" for rank, cluster_id in enumerate(cluster_means.index, 1)}
        df['logical_tier'] = df['raw_cluster'].map(tier_mapping)
        
        user_tier = df[df['customer_id'] == user_id]['logical_tier'].values
        if len(user_tier) > 0:
            return user_tier[0]
            
        return "New/Standard Buyer"
    except Exception:
        return "New/Standard Buyer"

def get_hybrid_recommendations(user_id, search_query=None):
    conn = get_db()
    history_query = f"SELECT p.domain_category FROM recently_viewed r JOIN products p ON r.product_id = p.product_id WHERE r.user_id = {user_id} ORDER BY r.viewed_at DESC LIMIT 5"
    history = pd.read_sql_query(history_query, conn)
    
    fav_domains = history['domain_category'].tolist() if not history.empty else []
    base_query = "SELECT * FROM products WHERE stock > 0"
    params = []

    if search_query:
        base_query += " AND name LIKE ?"
        params.append(f'%{search_query}%')
    elif fav_domains:
        placeholders = ','.join(['?'] * len(fav_domains))
        base_query += f" AND domain_category IN ({placeholders})"
        params.extend(fav_domains)

    recommendations = conn.execute(base_query, params).fetchall()
    conn.close()
    return [dict(ix) for ix in recommendations] if recommendations else []

def get_segment_recommendations(user_id):
    try:
        conn = get_db()
        query = "SELECT customer_id, SUM(total_amount) as total_spent, COUNT(order_id) as freq FROM orders GROUP BY customer_id"
        df = pd.read_sql_query(query, conn)
        
        if len(df) < 3 or user_id not in df['customer_id'].values:
            conn.close()
            return []

        kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
        df['cluster'] = kmeans.fit_predict(df[['total_spent', 'freq']])
        
        user_cluster = df[df['customer_id'] == user_id]['cluster'].values[0]
        similar_users = df[(df['cluster'] == user_cluster) & (df['customer_id'] != user_id)]['customer_id'].tolist()
        
        if not similar_users:
            conn.close()
            return []

        placeholders = ','.join(['?'] * len(similar_users))
        rec_query = f"""
            SELECT p.*, COUNT(oi.product_id) as purchase_count
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE o.customer_id IN ({placeholders}) AND p.stock > 0
            GROUP BY p.product_id ORDER BY purchase_count DESC LIMIT 4
        """
        segment_recs = conn.execute(rec_query, similar_users).fetchall()
        conn.close()
        return [dict(ix) for ix in segment_recs]
    except Exception:
        return []

# ==========================================
# ROUTES
# ==========================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        if conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone():
            conn.close()
            return "Username exists. Please try another."
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'customer')", (username, password))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            if user['role'] == 'admin': return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'vendor': return redirect(url_for('vendor_dashboard'))
            else: return redirect(url_for('home'))
        return "Invalid Credentials!"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin': 
        return "Access Denied.", 403
    conn = get_db()
    sales = conn.execute("SELECT SUM(qty * price_sold) as rev, SUM(qty * cost_at_sale) as cost FROM order_items").fetchone()
    rev = sales['rev'] or 0
    cost = sales['cost'] or 0
    
    users = conn.execute("SELECT * FROM users").fetchall()
    users_with_status = []
    
    for u in users:
        u_dict = dict(u)
        if u_dict['role'] == 'customer':
            u_dict['ai_status'] = get_customer_segment(u_dict['user_id'])
        else:
            u_dict['ai_status'] = 'N/A'
        users_with_status.append(u_dict)
    
    best_prods = conn.execute("""
        SELECT p.name, SUM(oi.qty) as vol, SUM(oi.qty * (oi.price_sold - oi.cost_at_sale)) as prof 
        FROM order_items oi JOIN products p ON oi.product_id = p.product_id 
        GROUP BY p.product_id ORDER BY vol DESC LIMIT 5
    """).fetchall()
    
    all_orders = conn.execute("""
        SELECT o.order_id, u.username as customer_name, o.total_amount, o.created_at 
        FROM orders o JOIN users u ON o.customer_id = u.user_id ORDER BY o.created_at DESC
    """).fetchall()
    conn.close()
    
    return render_template('admin.html', revenue=rev, profit=(rev - cost), users=users_with_status, 
                           labels=[r['name'] for r in best_prods], sales=[r['vol'] for r in best_prods], 
                           profits=[r['prof'] for r in best_prods], orders=all_orders)

@app.route('/admin/add_vendor', methods=['POST'])
def add_vendor():
    if session.get('role') == 'admin':
        conn = get_db()
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'vendor')", 
                     (request.form['username'], request.form['password']))
        conn.commit()
        conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/vendor', methods=['GET', 'POST'])
def vendor_dashboard():
    if session.get('role') != 'vendor': return "Access Denied.", 403
    vendor_id = session.get('user_id')
    conn = get_db()
    
    if request.method == 'POST':
        image_url = '/static/placeholder.svg' 
        if 'image_file' in request.files:
            file = request.files['image_file']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_url = f"/static/uploads/{filename}"
                
        conn.execute("""
            INSERT INTO products (vendor_id, name, domain_category, selling_price, cost_price, stock, image_url) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (vendor_id, request.form['name'], request.form['domain_category'], request.form['selling_price'], 
              request.form['cost_price'], request.form['stock'], image_url))
        conn.commit()
        
    products = conn.execute("SELECT * FROM products WHERE vendor_id = ?", (vendor_id,)).fetchall()
    sales = conn.execute("""
        SELECT o.order_id, p.name as product_name, oi.qty, oi.price_sold, o.created_at
        FROM order_items oi JOIN products p ON oi.product_id = p.product_id 
        JOIN orders o ON oi.order_id = o.order_id WHERE p.vendor_id = ? ORDER BY o.created_at DESC
    """, (vendor_id,)).fetchall()
    conn.close()
    
    return render_template('vendor.html', products=products, sales=sales)

@app.route('/vendor/update', methods=['POST'])
def update_product():
    if session.get('role') != 'vendor': return "Access Denied.", 403
    vendor_id = session.get('user_id')
    product_id = request.form['product_id']
    new_price = request.form['selling_price']
    new_stock = request.form['stock']
    
    conn = get_db()
    conn.execute("UPDATE products SET selling_price = ?, stock = ? WHERE product_id = ? AND vendor_id = ?", 
                 (new_price, new_stock, product_id, vendor_id))
    conn.commit()
    conn.close()
    return redirect(url_for('vendor_dashboard'))

@app.route('/')
def home():
    user_id = session.get('user_id')
    if not user_id or session.get('role') != 'customer': 
        return redirect(url_for('login'))
        
    search = request.args.get('q', '')
    conn = get_db()
    segment = get_customer_segment(user_id)
    history_recs = get_hybrid_recommendations(user_id, search)
    segment_recs = get_segment_recommendations(user_id)
    
    products = conn.execute("SELECT * FROM products WHERE stock > 0").fetchall() if not search else []
    recent = conn.execute("""
        SELECT p.* FROM recently_viewed r JOIN products p ON r.product_id = p.product_id 
        WHERE r.user_id = ? ORDER BY r.viewed_at DESC LIMIT 4
    """, (user_id,)).fetchall()
    conn.close()
    
    return render_template('index.html', search=search, segment=segment, history_recs=history_recs, 
                           segment_recs=segment_recs, products=products, recent=recent)

@app.route('/view/<int:product_id>')
def view_product(product_id):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    conn = get_db()
    conn.execute("INSERT INTO recently_viewed (user_id, product_id) VALUES (?, ?)", (user_id, product_id))
    existing = conn.execute("SELECT * FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id)).fetchone()
    if existing:
        conn.execute("UPDATE cart_items SET qty = qty + 1 WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    else:
        conn.execute("INSERT INTO cart_items (user_id, product_id) VALUES (?, ?)", (user_id, product_id))
        
    conn.commit()
    conn.close()
    return redirect(url_for('home'))

@app.route('/cart')
def cart():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    conn = get_db()
    items = conn.execute("""
        SELECT c.qty, p.product_id, p.name, p.selling_price, p.image_url, (c.qty * p.selling_price) as subtotal 
        FROM cart_items c JOIN products p ON c.product_id = p.product_id WHERE c.user_id = ?
    """, (user_id,)).fetchall()
    conn.close()
    return render_template('cart.html', items=items)

@app.route('/checkout', methods=['POST'])
def checkout():
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    selected_products = request.form.getlist('selected_products')
    if not selected_products:
        return redirect(url_for('cart'))
        
    conn = get_db()
    cursor = conn.cursor()
    placeholders = ','.join(['?'] * len(selected_products))
    query = f"""
        SELECT c.qty, p.product_id, p.selling_price, p.cost_price, p.stock 
        FROM cart_items c JOIN products p ON c.product_id = p.product_id 
        WHERE c.user_id = ? AND p.product_id IN ({placeholders})
    """
    params = [user_id] + selected_products
    cart_items = cursor.execute(query, params).fetchall()
    
    ist_time = get_ist_time()
    cursor.execute("INSERT INTO orders (customer_id, total_amount, created_at) VALUES (?, 0, ?)", (user_id, ist_time))
    order_id = cursor.lastrowid
    
    total = 0
    for item in cart_items:
        if item['stock'] >= item['qty']:
            cursor.execute("INSERT INTO order_items (order_id, product_id, qty, price_sold, cost_at_sale) VALUES (?, ?, ?, ?, ?)", 
                           (order_id, item['product_id'], item['qty'], item['selling_price'], item['cost_price']))
            cursor.execute("UPDATE products SET stock = stock - ? WHERE product_id = ?", (item['qty'], item['product_id']))
            cursor.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, item['product_id']))
            total += (item['selling_price'] * item['qty'])
            
    cursor.execute("UPDATE orders SET total_amount = ? WHERE order_id = ?", (total, order_id))
    conn.commit()
    
    order = cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    receipt_items = cursor.execute("""
        SELECT p.name, oi.qty, oi.price_sold, (oi.qty * oi.price_sold) as subtotal 
        FROM order_items oi JOIN products p ON oi.product_id = p.product_id WHERE oi.order_id = ?
    """, (order_id,)).fetchall()
    conn.close()
    return render_template('bill.html', order=order, items=receipt_items)

@app.route('/direct_checkout/<int:product_id>', methods=['POST'])
def direct_checkout(product_id):
    user_id = session.get('user_id')
    if not user_id: return redirect(url_for('login'))
    
    conn = get_db()
    cursor = conn.cursor()
    product = cursor.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
    
    if not product or product['stock'] < 1:
        conn.close()
        return redirect(url_for('home'))
        
    ist_time = get_ist_time()
    cursor.execute("INSERT INTO orders (customer_id, total_amount, created_at) VALUES (?, ?, ?)", 
                   (user_id, product['selling_price'], ist_time))
    order_id = cursor.lastrowid
    cursor.execute("INSERT INTO order_items (order_id, product_id, qty, price_sold, cost_at_sale) VALUES (?, ?, 1, ?, ?)", 
                   (order_id, product_id, product['selling_price'], product['cost_price']))
    cursor.execute("UPDATE products SET stock = stock - 1 WHERE product_id = ?", (product_id,))
    cursor.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (user_id, product_id))
    
    # NEW ADDITION: Logs the direct purchase to trigger the Content-Based Engine immediately
    cursor.execute("INSERT INTO recently_viewed (user_id, product_id) VALUES (?, ?)", (user_id, product_id))
    
    conn.commit()
    
    order = cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    receipt_items = cursor.execute("""
        SELECT p.name, oi.qty, oi.price_sold, (oi.qty * oi.price_sold) as subtotal 
        FROM order_items oi JOIN products p ON oi.product_id = p.product_id WHERE oi.order_id = ?
    """, (order_id,)).fetchall()
    conn.close()
    return render_template('bill.html', order=order, items=receipt_items)

init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG') == '1')
 
