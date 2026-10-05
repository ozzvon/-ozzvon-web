CREATE TABLE IF NOT EXISTS menus (
    id TEXT PRIMARY KEY,
    emoji TEXT NOT NULL DEFAULT 'dish',
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    menu_id TEXT NOT NULL REFERENCES menus(id) ON DELETE CASCADE,
    emoji TEXT NOT NULL DEFAULT 'dish',
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    emoji TEXT NOT NULL DEFAULT 'dish',
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_sizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at INTEGER NOT NULL,
    completed_at INTEGER,
    order_type TEXT NOT NULL CHECK (order_type IN ('mesa', 'llevar', 'domicilio')),
    table_number INTEGER,
    customer_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('pendiente', 'envio', 'concluido', 'cancelado')),
    total REAL NOT NULL CHECK (total >= 0),
    payment_method TEXT,
    amount_received REAL,
    change_amount REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'pos',
    source_message_id TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    source_product_id TEXT,
    product_name TEXT NOT NULL,
    size_name TEXT NOT NULL,
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);

INSERT OR IGNORE INTO menus (id, emoji, name)
VALUES ('menu-default', '🍽️', 'Menú principal');

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('name', ''),
    ('tables', '12'),
    ('accent', 'ember'),
    ('mode', 'auto'),
    ('active_menu', 'menu-default');
