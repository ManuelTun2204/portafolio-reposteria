# Tienda en línea del portafolio de repostería — memoria de trabajo (2026-11-09)

## Qué se hizo

- Se reemplazó el demo Streamlit por una tienda real: **FastAPI + Jinja2 + SQLite +
  CSS propio**, un solo servicio en el puerto **8515**. El demo anterior se movió a
  `legacy/` (no se borró).
- Tienda pública: portada con destacados, galería por secciones (pasteles, postres,
  promociones, novedades), detalle de producto con presentación, venta por pieza o
  pieza completa, precio, stock y tiempo de entrega, carrito y apartado de pedido.
- Panel de administración: productos (alta, edición, borrado, visibilidad, destacado),
  fotos (subida múltiple y borrado), recetas por producto, stock, precios y pedidos
  con cambio de estado.
- Recetas y menú de productos **solo para el administrador**: no se envían al
  visitante y las rutas `/admin` validan la sesión en el servidor.
- Precio y stock se recalculan en el servidor; el navegador nunca decide el cobro.
  Si un producto se agota después de agregarlo, se retira del carrito.
- Pedidos con folio `REP-AAMMDD-XXXX`; no se cobra en línea (se confirma por WhatsApp).
- Se crearon `Dockerfile`, `docker-compose.yml` (puerto 8515, `restart: "no"`,
  volúmenes para `data/` y `uploads/`), `.env.example`, `.gitignore` y `README.md`.
- `project-panel`: se agregó `portafolio-reposteria` a `_DASHBOARD_URLS` (con la URL
  `http://localhost:8515`), se eliminó el diccionario duplicado dentro de
  `_scan_project` y se agregó el repo a `repos.txt`. El botón **Levantar** ya aparece.

## Verificación real

- 30 comprobaciones automatizadas en verde: portada, galería, detalle, receta oculta
  al público y visible al administrador, carrito con total correcto, checkout,
  folio, login, panel, productos, recetas, pedidos, alta de producto, subida de foto,
  guardado de receta, borrado y limpieza de datos de prueba.
- `docker compose config` válido y contenedor construido y arriba en 8515 con
  `GET /` = 200.
- El panel en 8100 muestra el botón `levantarProyecto('portafolio-reposteria',
  'http://localhost:8515')`.

## Decisiones

- SQLite en lugar de Postgres: un solo archivo, sin servidor y sin gastar RAM en la
  i5-8265U. Si hace falta multiusuario real, se migra a `infra` sin cambiar el SQL.
- Los datos (`data/` y `uploads/`) están en `.gitignore`: cada PC tiene su base.
- La contraseña inicial es `admin123`; el panel avisa en rojo mientras no se cambie
  `ADMIN_PASSWORD` y `SECRET_KEY` en `.env`.

## Pendiente / siguiente

- Cargar contenido real (el catálogo sembrado es de ejemplo).
- Reordenar fotos desde el panel (hoy la primera es la portada).
- Límite de intentos en el login y paginación/buscador cuando el catálogo crezca.
- Pasarela de pago, solo si el negocio la pide.
