# Portafolio de repostería

Tienda en línea con panel de administración para un negocio de repostería.

- **Cliente:** portada, galería por secciones (pasteles, postres, promociones y
  novedades), detalle de producto con presentación, precio, stock y tiempo de
  entrega, carrito y apartado de pedido.
- **Administrador:** productos, recetas (solo visibles con sesión iniciada),
  fotos, stock, precios y pedidos.

## Stack

FastAPI + Jinja2 + SQLite + CSS propio. Un solo servicio, sin dependencias de
nube ni de JavaScript de terceros.

## Levantar en local (Windows)

```powershell
cd C:\projects\portafolio-reposteria
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # y edita los valores
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8515
```

Abre <http://localhost:8515>. El panel está en <http://localhost:8515/admin>.
La contraseña inicial es `admin123` y se cambia con `ADMIN_PASSWORD` en `.env`.

## Levantar con Docker

```powershell
cd C:\projects\portafolio-reposteria
Copy-Item .env.example .env
docker compose up -d --build
```

El contenedor se llama `portafolio_reposteria`, escucha en el puerto **8515** y
usa `restart: "no"`: no se levanta solo al abrir Docker.

## Datos

- `data/portafolio.db` — base SQLite (se crea sola y siembra un catálogo de
  ejemplo la primera vez).
- `app/static/uploads/` — fotos subidas desde el panel.
- Ambas rutas están en `.gitignore`: los datos de esta PC no viajan por git.
- El catálogo inicial es **contenido de ejemplo**, no inventario real. Se puede
  editar o borrar desde el panel.

## Reglas de negocio

- El precio y el stock se recalculan siempre en el servidor; el navegador nunca
  decide el cobro.
- No se cobra en línea: el pedido se aparta y se confirma por WhatsApp.
- Las recetas y el menú de productos no se envían al visitante; además cada ruta
  `/admin` valida la sesión en el servidor.

## Pendientes

- Migrar la base a Postgres de `infra` si se necesita multiusuario real.
- Pasarela de pago, si el negocio la pide.
- Contenido real (fotos y productos) en lugar del catálogo de ejemplo.
