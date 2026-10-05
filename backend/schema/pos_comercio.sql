CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    telefono TEXT,
    saldo_deudor REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    precio_compra REAL NOT NULL,
    precio_venta REAL NOT NULL,
    stock INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cajas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_apertura TEXT NOT NULL,
    fondo_inicial REAL NOT NULL DEFAULT 0,
    fecha_cierre TEXT,
    efectivo_final REAL,
    estado TEXT NOT NULL DEFAULT 'abierta',
    usuario_id INTEGER
);

CREATE TABLE IF NOT EXISTS movimientos_caja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caja_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    monto REAL NOT NULL,
    concepto TEXT NOT NULL DEFAULT '',
    fecha TEXT NOT NULL,
    usuario_id INTEGER,
    FOREIGN KEY (caja_id) REFERENCES cajas(id)
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    permisos TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    usuario TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol_id INTEGER NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (rol_id) REFERENCES roles(id)
);

CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    total REAL NOT NULL,
    subtotal REAL,
    iva REAL,
    tasa_iva REAL,
    metodo_pago TEXT NOT NULL DEFAULT 'Efectivo',
    cliente_id INTEGER,
    usuario_id INTEGER,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS detalle_ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    precio_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (venta_id) REFERENCES ventas(id)
);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER NOT NULL,
    cliente_id INTEGER,
    rfc TEXT NOT NULL,
    razon_social TEXT NOT NULL,
    uso_cfdi TEXT NOT NULL DEFAULT 'G03',
    serie TEXT NOT NULL DEFAULT 'A',
    folio INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    uuid TEXT,
    fecha TEXT NOT NULL,
    FOREIGN KEY (venta_id) REFERENCES ventas(id),
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS ticket_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    diseno TEXT NOT NULL,
    predeterminada INTEGER NOT NULL DEFAULT 0,
    actualizada TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    contacto TEXT NOT NULL DEFAULT '',
    telefono TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    creado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    total REAL NOT NULL,
    notas TEXT NOT NULL DEFAULT '',
    usuario_id INTEGER,
    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS detalle_compras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    compra_id INTEGER NOT NULL,
    producto_id INTEGER NOT NULL,
    codigo TEXT NOT NULL,
    producto TEXT NOT NULL,
    cantidad INTEGER NOT NULL,
    costo_unitario REAL NOT NULL,
    subtotal REAL NOT NULL,
    FOREIGN KEY (compra_id) REFERENCES compras(id)
);

CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_detalle_ventas_venta_id ON detalle_ventas(venta_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_caja_caja_id ON movimientos_caja(caja_id);
CREATE INDEX IF NOT EXISTS idx_compras_fecha ON compras(fecha);

INSERT OR IGNORE INTO roles (nombre, permisos) VALUES
    (
        'Administrador',
        '["dashboard.view","sales.create","inventory.view","inventory.manage","clients.view","clients.manage","reports.view","cash.view","cash.manage","users.manage","settings.manage","billing.view"]'
    ),
    (
        'Cajero',
        '["dashboard.view","sales.create","inventory.view","clients.view","cash.view"]'
    ),
    (
        'Encargado',
        '["dashboard.view","sales.create","inventory.view","inventory.manage","clients.view","clients.manage","reports.view","cash.view","cash.manage"]'
    );

INSERT OR IGNORE INTO ajustes (clave, valor) VALUES
    ('business_name', 'OZZVON POS'),
    ('business_icon', 'cart'),
    ('business_logo', ''),
    ('business_rfc', ''),
    ('business_phone', ''),
    ('business_address', ''),
    ('ticket_footer', 'Gracias por su compra'),
    ('currency', 'MXN'),
    ('vat_rate', '16');

INSERT OR IGNORE INTO ticket_templates (nombre, diseno, predeterminada, actualizada)
VALUES (
    'Clásica',
    '[{"type":"business","text":"{{business_name}}","x":24,"y":24,"w":252,"h":30,"size":20,"align":"center","bold":true},{"type":"meta","text":"{{business_rfc}}\\n{{business_phone}}","x":24,"y":62,"w":252,"h":42,"size":11,"align":"center","bold":false},{"type":"divider","text":"------------------------------","x":24,"y":116,"w":252,"h":24,"size":11,"align":"center","bold":false},{"type":"items","text":"{{items}}","x":24,"y":148,"w":252,"h":120,"size":12,"align":"left","bold":false},{"type":"total","text":"TOTAL  {{total}}","x":24,"y":282,"w":252,"h":32,"size":16,"align":"right","bold":true},{"type":"footer","text":"{{ticket_footer}}","x":24,"y":334,"w":252,"h":42,"size":11,"align":"center","bold":false}]',
    1,
    CURRENT_TIMESTAMP
);
