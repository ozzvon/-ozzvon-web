# Cuenta y autenticación Ozzvon

Este servicio Flask registra cuentas, inicia y cierra sesiones, devuelve los
datos de la cuenta y permite restablecer contraseñas. Guarda los usuarios y el
estado de licencia en la base maestra SQLite; crea una base de datos separada
por negocio. Las bases se guardan en `backend/data/`, fuera de los archivos
estáticos. Las contraseñas se almacenan como hashes bcrypt.

## Ejecutar localmente

Desde esta carpeta, instala dependencias e inicia el servidor:

```powershell
python -m pip install -r requirements.txt
python app.py
```

## Desplegar en un VPS Ubuntu/Debian

Los ejemplos usan `www.ejemplo.com`; sustituye el dominio, usuario y rutas por
los tuyos. Apunta los registros DNS `A` del dominio (y `www`, si lo usarás) a
la IP del VPS. En el VPS, crea estos directorios y sube los archivos con
WinSCP/SFTP:

- El contenido de `WEB/web/` de este proyecto a `/var/www/ozzvon/web/`.
- El contenido de `WEB/backend/` a `/var/www/ozzvon/backend/`.

Prepara Python, Nginx y una ubicación de datos que no se sirva como web:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx
sudo install -d -m 700 -o www-data -g www-data /var/lib/ozzvon /var/lib/ozzvon/tenants
sudo python3 -m venv /var/www/ozzvon/venv
sudo /var/www/ozzvon/venv/bin/pip install -r /var/www/ozzvon/backend/requirements.txt
```

El archivo de la base maestra **se crea automáticamente al iniciar la app**;
no crees las tablas a mano. Al arrancar, `backend/app.py` crea o migra
`usuarios` y `password_resets`. Al registrar un negocio, crea su SQLite aparte
dentro de `tenants/`.

Crea un secreto del servidor y el archivo de variables privadas:

```bash
sudo install -d -m 700 /etc/ozzvon
openssl rand -hex 32
sudo nano /etc/ozzvon/backend.env
sudo chown root:www-data /etc/ozzvon/backend.env
sudo chmod 640 /etc/ozzvon/backend.env
```

Pega el resultado de `openssl rand -hex 32` como valor de `SECRET_KEY` en
`nano`, junto con esta configuración:

```dotenv
SECRET_KEY=PEGA_AQUI_EL_SECRETO_GENERADO
MASTER_DB_PATH=/var/lib/ozzvon/master.db
TENANT_DATABASE_DIR=/var/lib/ozzvon/tenants
SESSION_COOKIE_SECURE=1
CORS_ORIGINS=https://www.ejemplo.com
PUBLIC_BASE_URL=https://www.ejemplo.com
```

Usa el dominio real en `CORS_ORIGINS` y `PUBLIC_BASE_URL`. Para aceptar tanto
el dominio raíz como `www`, sepáralos con coma, por ejemplo
`CORS_ORIGINS=https://ejemplo.com,https://www.ejemplo.com`. Para configurar
Google, añade `GOOGLE_CLIENT_ID=...` a ese archivo. Para habilitar la
recuperación por correo, añade `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
`SMTP_PASSWORD` y `SMTP_FROM`. No escribas los secretos en HTML o JavaScript.

Crea `/etc/systemd/system/ozzvon.service`:

```ini
[Unit]
Description=Ozzvon account API
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/ozzvon/backend
EnvironmentFile=/etc/ozzvon/backend.env
ExecStart=/var/www/ozzvon/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 app:app
Restart=on-failure
UMask=0077
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/ozzvon

[Install]
WantedBy=multi-user.target
```

Arráncalo y confirma que Gunicorn quedó activo:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ozzvon
sudo systemctl status ozzvon --no-pager
```

Crea `/etc/nginx/sites-available/ozzvon`:

```nginx
server {
    listen 80;
    server_name ejemplo.com www.ejemplo.com;
    root /var/www/ozzvon/web;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

Activa la configuración y obtén el certificado TLS:

```bash
sudo ln -s /etc/nginx/sites-available/ozzvon /etc/nginx/sites-enabled/ozzvon
sudo nginx -t
sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ejemplo.com -d www.ejemplo.com
```

Cuando Nginx publique el sitio por HTTPS, prueba el API. Un `401` en `/api/cuenta`
sin iniciar sesión confirma que la ruta API llegó a Flask:

```bash
curl -i https://www.ejemplo.com/api/cuenta
```

Revisa fallos con `sudo journalctl -u ozzvon -n 100 --no-pager` y
`sudo tail -n 100 /var/log/nginx/error.log`.

## Consultar y respaldar la base maestra

El archivo está en `/var/lib/ozzvon/master.db` con esta configuración. Instala
el cliente SQLite si lo necesitas y consulta o cambia una licencia:

```bash
sudo apt install -y sqlite3
sudo sqlite3 /var/lib/ozzvon/master.db \
  "SELECT id, nombre_negocio, email, licencia_estado, fecha_creacion FROM usuarios;"
sudo sqlite3 /var/lib/ozzvon/master.db \
  "UPDATE usuarios SET licencia_estado='suspendida' WHERE email='cliente@ejemplo.com';"
```

Estados válidos: `activa`, `suspendida` y `baja`. Para respaldar, detén el
servicio un momento, copia **todo** `/var/lib/ozzvon/` a un almacenamiento
seguro y vuelve a iniciar `ozzvon`. Ese directorio contiene la cuenta maestra
y todas las bases de los negocios. No lo pongas dentro del directorio web.

Esta configuración hace que la web muestre el estado de licencia administrado
en el VPS. Todavía se requiere conectar el software POS a la validación remota
si también quieres bloquear su uso al suspender o dar de baja una cuenta.

Por defecto, el servicio escucha en `127.0.0.1:5000`. Configura
`MASTER_DB_PATH` y `TENANT_DATABASE_DIR` para elegir las rutas de las bases de
datos. Define un `SECRET_KEY` largo, aleatorio y estable en el servidor para
conservar las sesiones entre reinicios. Define `CORS_ORIGINS` como el origen
exacto de la web si frontend y API se publican en dominios distintos. El valor
por defecto `*` es solo para pruebas; la web está configurada para API bajo el
mismo origen.

El cookie de sesión es `HttpOnly`, `SameSite=Lax` y, por defecto, `Secure`.
Para desarrollo local por HTTP, configura `SESSION_COOKIE_SECURE=0`; no lo
hagas en producción. Usa HTTPS y un servidor WSGI detrás de un proxy inverso.
No uses el servidor de desarrollo de Flask como servicio público.

## Cuenta y licencias

Rutas principales:

- `POST /api/registro`: crea una cuenta y una base de datos de POS; inicia
  sesión al registrarla.
- `POST /api/auth/login` y `POST /api/auth/logout`: inicia y cierra sesión.
- `GET /api/cuenta`: devuelve nombre del negocio, correo, fecha de registro y
  licencia para la sesión actual.
- `POST /api/auth/forgot-password` y `POST /api/auth/reset-password`: envía un
  enlace de un solo uso con vencimiento de una hora y cambia la contraseña.
- `GET /api/auth/config` y `POST /api/auth/google`: configuran y verifican el
  inicio/registro opcional con Google.

La contraseña debe tener entre 8 y 72 bytes UTF-8 (límite de bcrypt). El
restablecimiento solo se habilita cuando SMTP está configurado; sin servicio de
correo el endpoint responde `503`, no simula el envío.

El servidor es la autoridad del estado de licencia. Una cuenta nueva comienza
como `activa`; para suspenderla o darla de baja, administra la base maestra en
el servidor:

```sql
UPDATE usuarios SET licencia_estado = 'suspendida' WHERE email = 'cliente@ejemplo.com';
UPDATE usuarios SET licencia_estado = 'baja' WHERE email = 'cliente@ejemplo.com';
UPDATE usuarios SET licencia_estado = 'activa' WHERE email = 'cliente@ejemplo.com';
```

Los únicos estados permitidos son `activa`, `suspendida` y `baja`. El portal
consulta el estado actualizado desde el servidor cada vez que se abre la
cuenta. Esto muestra el estado en la web; no bloquea por sí solo los programas
de escritorio. Para aplicar la licencia en esos programas, sus APIs de
activación también deben consultar `licencia_estado` en esta base maestra.

## Restablecimiento por correo

Configura estas variables de entorno en el VPS (no las pongas en JavaScript,
HTML, el repositorio ni las envíes al cliente):

```dotenv
SMTP_HOST=smtp.ejemplo.com
SMTP_PORT=587
SMTP_USERNAME=usuario-smtp
SMTP_PASSWORD=secreto-smtp
SMTP_FROM=Ozzvon <no-reply@ejemplo.com>
PUBLIC_BASE_URL=https://www.ozzvon.com
```

El puerto 587 usa STARTTLS; el puerto 465 usa TLS implícito. El enlace apunta a
`PUBLIC_BASE_URL/#restablecer=...`, usa un token aleatorio y guarda solo el
hash SHA-256 del token en la base maestra. El servicio solo enviará enlaces si
`PUBLIC_BASE_URL` utiliza HTTPS.

## Registro e inicio con Google

Es posible mediante Google Identity Services. En Google Cloud Console, crea un
cliente OAuth de tipo **Aplicación web**, agrega el origen HTTPS de la página
como origen de JavaScript autorizado y configura su ID en el servidor:

```dotenv
GOOGLE_CLIENT_ID=tu-cliente-web.apps.googleusercontent.com
```

El secreto de cliente de Google no se necesita para este flujo y no debe
exponerse. El servidor verifica la firma y audiencia del ID token y exige un
correo verificado. Si no se define `GOOGLE_CLIENT_ID`, los botones de Google se
ocultan. Una cuenta existente con contraseña no se vincula automáticamente;
esto evita tomar control de cuentas mediante vinculación implícita.

## Pruebas

```powershell
python -m unittest discover -s tests
```
