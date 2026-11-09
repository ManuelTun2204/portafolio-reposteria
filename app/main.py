"""Portafolio de reposteria: tienda publica + panel de administracion.

Reglas de diseno:
- El cliente ve galeria, detalle, carrito y checkout.
- El administrador ve ademas el menu de productos y las recetas. Esas dos
  secciones NO se renderizan para un visitante (no se ocultan con CSS: no se
  envian), y ademas cada ruta /admin comprueba la sesion en el servidor.
- Los precios y el stock se recalculan SIEMPRE en el servidor. El navegador
  nunca decide cuanto se cobra.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db

BASE_DIR = Path(__file__).resolve().parent
UPLOADS = BASE_DIR / "static" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-esta-clave-en-produccion")
EXTENSIONES_OK = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FOTO_BYTES = 6 * 1024 * 1024

# Pago sin pasarela: transferencia o deposito, con anticipo opcional.
# Si CLABE viene vacia, la tienda no inventa datos bancarios: solo pide
# acordar el pago por WhatsApp (que es lo que hace hoy).
def _porcentaje(valor: str) -> float:
    """Convierte '50' en 50.0 y cualquier basura en 0. Un anticipo mal escrito
    no debe tumbar el arranque del sitio."""
    try:
        numero = float((valor or "").strip().replace("%", ""))
    except ValueError:
        return 0.0
    return max(0.0, min(100.0, numero))


ANTICIPO_PORCENTAJE = _porcentaje(os.getenv("ANTICIPO_PORCENTAJE", "0"))

db.inicializar()

app = FastAPI(title="Portafolio de Reposteria", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _render(request: Request, nombre: str, contexto: dict | None = None, status_code: int = 200):
    """Renderiza con la firma nueva de Starlette (request primero).

    Se centraliza aqui para no repetir la firma en cada ruta y para que un
    cambio futuro de Starlette se arregle en un solo sitio.
    """
    contexto = dict(contexto or {})
    contexto.setdefault("request", request)
    return templates.TemplateResponse(request, nombre, contexto, status_code=status_code)


def dinero(valor: float) -> str:
    return f"${valor:,.2f}"


templates.env.filters["dinero"] = dinero


# --------------------------------------------------------------------------
# Contexto comun
# --------------------------------------------------------------------------
def _pago_config() -> dict:
    """Datos de cobro que salen del entorno, nunca de la base ni del navegador."""
    return {
        "banco": os.getenv("BANCO", "").strip(),
        "clabe": os.getenv("CLABE", "").strip(),
        "titular": os.getenv("TITULAR", "").strip(),
        "direccion_taller": os.getenv("DIRECCION_TALLER", "").strip(),
        "anticipo_pct": ANTICIPO_PORCENTAJE,
    }


def _ctx(request: Request, **extra) -> dict:
    carrito = request.session.get("carrito", {})
    return {
        "request": request,
        "marca": os.getenv("MARCA", "Dulce Atelier"),
        "whatsapp": os.getenv("WHATSAPP", ""),
        "anio": datetime.now().year,
        "categorias": db.CATEGORIAS,
        "carrito_n": sum(int(v) for v in carrito.values()) if carrito else 0,
        "es_admin": bool(request.session.get("admin")),
        "password_default": ADMIN_PASSWORD == "admin123",
        "secret_default": SECRET_KEY == "cambiar-esta-clave-en-produccion",
        "direccion_taller": os.getenv("DIRECCION_TALLER", "").strip(),
        **extra,
    }


def _es_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _guard(request: Request) -> RedirectResponse | None:
    if not _es_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _fotos_de(con, producto_id: int):
    return con.execute(
        "SELECT * FROM fotos WHERE producto_id = ? ORDER BY orden, id", (producto_id,)
    ).fetchall()


def _receta_de(con, producto_id: int):
    return con.execute(
        "SELECT * FROM recetas WHERE producto_id = ?", (producto_id,)
    ).fetchone()


def _zonas(con):
    """Zonas de envio activas, en el orden que definio el administrador."""
    return con.execute(
        "SELECT * FROM zonas_envio WHERE activo = 1 ORDER BY orden, precio, id"
    ).fetchall()


def _con_foto(con, filas):
    """Copia cada fila y le pega el nombre del archivo de su foto principal.

    Las plantillas no consultan la base: reciben todo resuelto. El catalogo es
    pequeno (decenas de filas) y SQLite es local, asi que la consulta extra no
    cuesta nada perceptible.
    """
    salida = []
    for fila in filas:
        datos = dict(fila)
        foto = con.execute(
            "SELECT archivo FROM fotos WHERE producto_id = ? ORDER BY orden, id LIMIT 1",
            (fila["id"],),
        ).fetchone()
        datos["foto"] = foto["archivo"] if foto else ""
        salida.append(datos)
    return salida


def _carrito_detallado(request: Request):
    """Carrito resuelto contra la base. Nunca confia en precios del navegador."""
    carrito = request.session.get("carrito", {})
    if not carrito:
        return [], 0.0
    con = db.conectar()
    filas = []
    total = 0.0
    for pid_txt, cantidad in list(carrito.items()):
        fila = con.execute(
            "SELECT * FROM productos WHERE id = ? AND activo = 1", (int(pid_txt),)
        ).fetchone()
        if not fila:
            carrito.pop(pid_txt, None)
            continue
        if int(fila["stock"]) <= 0:
            # Se agoto despues de agregarlo: se retira del carrito en vez de
            # dejar que el cliente aparte algo que ya no existe.
            carrito.pop(pid_txt, None)
            continue
        cantidad = max(1, min(int(cantidad), int(fila["stock"])))
        subtotal = float(fila["precio"]) * cantidad
        total += subtotal
        producto = dict(fila)
        foto = con.execute(
            "SELECT archivo FROM fotos WHERE producto_id = ? ORDER BY orden, id LIMIT 1",
            (fila["id"],),
        ).fetchone()
        producto["foto"] = foto["archivo"] if foto else ""
        filas.append({"producto": producto, "cantidad": cantidad, "subtotal": subtotal})
    request.session["carrito"] = carrito
    con.close()
    return filas, total


# --------------------------------------------------------------------------
# Tienda publica
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    con = db.conectar()
    destacados = con.execute(
        "SELECT * FROM productos WHERE activo = 1 AND destacado = 1 ORDER BY id DESC LIMIT 6"
    ).fetchall()
    if not destacados:
        destacados = con.execute(
            "SELECT * FROM productos WHERE activo = 1 ORDER BY id DESC LIMIT 6"
        ).fetchall()
    recientes = con.execute(
        "SELECT * FROM productos WHERE activo = 1 ORDER BY id DESC LIMIT 4"
    ).fetchall()
    conteo = {
        fila["categoria"]: fila["c"]
        for fila in con.execute(
            "SELECT categoria, COUNT(*) AS c FROM productos WHERE activo = 1 GROUP BY categoria"
        ).fetchall()
    }
    destacados = _con_foto(con, destacados)
    recientes = _con_foto(con, recientes)
    con.close()
    return _render(request, 
        "index.html", _ctx(request, destacados=destacados, recientes=recientes, conteo=conteo)
    )


@app.get("/galeria", response_class=HTMLResponse)
def galeria(request: Request, categoria: str = ""):
    con = db.conectar()
    if categoria in db.CATEGORIAS:
        productos = con.execute(
            "SELECT * FROM productos WHERE activo = 1 AND categoria = ? ORDER BY id DESC",
            (categoria,),
        ).fetchall()
    else:
        categoria = ""
        productos = con.execute(
            "SELECT * FROM productos WHERE activo = 1 ORDER BY categoria, id DESC"
        ).fetchall()
    productos = _con_foto(con, productos)
    con.close()
    return _render(request, 
        "galeria.html", _ctx(request, productos=productos, categoria=categoria)
    )


@app.get("/producto/{slug}", response_class=HTMLResponse)
def producto(request: Request, slug: str):
    con = db.conectar()
    p = con.execute("SELECT * FROM productos WHERE slug = ? AND activo = 1", (slug,)).fetchone()
    if not p:
        con.close()
        return _render(request, 
            "no_encontrado.html", _ctx(request), status_code=404
        )
    fotos = _fotos_de(con, p["id"])
    receta = _receta_de(con, p["id"]) if _es_admin(request) else None
    relacionados = con.execute(
        "SELECT * FROM productos WHERE activo = 1 AND categoria = ? AND id <> ? ORDER BY id DESC LIMIT 3",
        (p["categoria"], p["id"]),
    ).fetchall()
    relacionados = _con_foto(con, relacionados)
    con.close()
    return _render(request, 
        "producto.html",
        _ctx(request, p=p, fotos=fotos, receta=receta, relacionados=relacionados),
    )


@app.post("/carrito/agregar")
def carrito_agregar(request: Request, producto_id: int = Form(...), cantidad: int = Form(1)):
    con = db.conectar()
    p = con.execute(
        "SELECT id, stock FROM productos WHERE id = ? AND activo = 1", (producto_id,)
    ).fetchone()
    con.close()
    if p and int(p["stock"]) > 0:
        carrito = request.session.get("carrito", {})
        clave = str(producto_id)
        nuevo = int(carrito.get(clave, 0)) + max(1, cantidad)
        carrito[clave] = min(nuevo, int(p["stock"]))
        request.session["carrito"] = carrito
    return RedirectResponse("/carrito", status_code=303)


@app.post("/carrito/quitar")
def carrito_quitar(request: Request, producto_id: int = Form(...)):
    carrito = request.session.get("carrito", {})
    carrito.pop(str(producto_id), None)
    request.session["carrito"] = carrito
    return RedirectResponse("/carrito", status_code=303)


@app.post("/carrito/actualizar")
def carrito_actualizar(request: Request, producto_id: int = Form(...), cantidad: int = Form(1)):
    con = db.conectar()
    p = con.execute("SELECT stock FROM productos WHERE id = ?", (producto_id,)).fetchone()
    con.close()
    carrito = request.session.get("carrito", {})
    if p and int(p["stock"]) > 0:
        carrito[str(producto_id)] = max(1, min(cantidad, int(p["stock"])))
    request.session["carrito"] = carrito
    return RedirectResponse("/carrito", status_code=303)


@app.get("/carrito", response_class=HTMLResponse)
def ver_carrito(request: Request):
    filas, total = _carrito_detallado(request)
    return _render(request, "carrito.html", _ctx(request, filas=filas, total=total))


@app.get("/checkout", response_class=HTMLResponse)
def checkout(request: Request):
    filas, subtotal = _carrito_detallado(request)
    if not filas:
        return RedirectResponse("/carrito", status_code=303)
    con = db.conectar()
    zonas = _zonas(con)
    con.close()
    return _render(request, 
        "checkout.html",
        _ctx(request, filas=filas, subtotal=subtotal, zonas=zonas,
             config=_pago_config(), error="", datos={}),
    )


@app.post("/checkout")
def crear_pedido(
    request: Request,
    cliente: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    entrega_tipo: str = Form("recoger"),
    zona_id: str = Form(""),
    direccion: str = Form(""),
    notas: str = Form(""),
):
    """Aparta el pedido. El envio y el total se calculan aqui, nunca en el navegador."""
    filas, subtotal = _carrito_detallado(request)
    if not filas:
        return RedirectResponse("/carrito", status_code=303)

    con = db.conectar()
    zonas = _zonas(con)

    zona = None
    error = ""
    if entrega_tipo == "domicilio":
        if not zonas:
            error = ("Todavía no hay zonas de envío configuradas. "
                     "Elige recoger en sitio o escríbenos por WhatsApp.")
        else:
            try:
                zona = next((z for z in zonas if int(z["id"]) == int(zona_id)), None)
            except (TypeError, ValueError):
                zona = None
            if zona is None:
                error = "Elige la zona de entrega."
            elif len(direccion.strip()) < 10:
                error = "Escribe la dirección completa: calle, número y colonia."
    elif entrega_tipo != "recoger":
        error = "Elige una forma de entrega."

    if error:
        con.close()
        return _render(request, 
            "checkout.html",
            _ctx(request, filas=filas, subtotal=subtotal, zonas=zonas,
                 config=_pago_config(), error=error,
                 datos={"cliente": cliente, "telefono": telefono, "email": email,
                        "entrega_tipo": entrega_tipo, "zona_id": zona_id,
                        "direccion": direccion, "notas": notas}),
            status_code=400,
        )

    a_domicilio = zona is not None
    envio = float(zona["precio"]) if a_domicilio else 0.0
    envio_convenir = 1 if a_domicilio and int(zona["a_convenir"]) else 0
    total = subtotal + envio
    anticipo = round(total * ANTICIPO_PORCENTAJE / 100, 2) if ANTICIPO_PORCENTAJE else 0.0

    entrega_txt = (
        f"Entrega a domicilio · {zona['nombre']}" if a_domicilio else "Recoger en el taller"
    )
    items = [
        {
            "producto_id": fila["producto"]["id"],
            "nombre": fila["producto"]["nombre"],
            "presentacion": fila["producto"]["presentacion"],
            "precio": float(fila["producto"]["precio"]),
            "cantidad": fila["cantidad"],
            "subtotal": fila["subtotal"],
        }
        for fila in filas
    ]
    folio = f"REP-{datetime.now():%y%m%d}-{secrets.token_hex(2).upper()}"

    con.execute(
        """INSERT INTO pedidos
           (folio, cliente, telefono, email, entrega, entrega_tipo, zona_nombre,
            direccion, subtotal, envio, envio_convenir, total, anticipo, notas,
            items, estado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'nuevo')""",
        (folio, cliente.strip(), telefono.strip(), email.strip(), entrega_txt,
         "domicilio" if a_domicilio else "recoger",
         zona["nombre"] if a_domicilio else "", direccion.strip() if a_domicilio else "",
         subtotal, envio, envio_convenir, total, anticipo, notas.strip(),
         json.dumps(items, ensure_ascii=False)),
    )
    con.commit()
    con.close()

    request.session["carrito"] = {}
    return RedirectResponse(f"/gracias/{folio}", status_code=303)


@app.get("/gracias/{folio}", response_class=HTMLResponse)
def gracias(request: Request, folio: str):
    con = db.conectar()
    pedido = con.execute("SELECT * FROM pedidos WHERE folio = ?", (folio,)).fetchone()
    con.close()
    if not pedido:
        return _render(request, "no_encontrado.html", _ctx(request), status_code=404)
    return _render(request, 
        "gracias.html",
        _ctx(request, pedido=pedido, items=json.loads(pedido["items"]),
             config=_pago_config()),
    )


# --------------------------------------------------------------------------
# Administracion
# --------------------------------------------------------------------------
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request):
    return _render(request, "admin/login.html", _ctx(request, error=""))


@app.post("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request, password: str = Form(...)):
    # comparar en bytes: compare_digest sobre str falla con acentos/no-ASCII
    if secrets.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")):
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    return _render(request, 
        "admin/login.html", _ctx(request, error="Contrasena incorrecta."), status_code=401
    )


@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.pop("admin", None)
    return RedirectResponse("/", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    total_productos = con.execute("SELECT COUNT(*) c FROM productos").fetchone()["c"]
    activos = con.execute("SELECT COUNT(*) c FROM productos WHERE activo = 1").fetchone()["c"]
    sin_stock = con.execute("SELECT COUNT(*) c FROM productos WHERE stock = 0").fetchone()["c"]
    pedidos_nuevos = con.execute("SELECT COUNT(*) c FROM pedidos WHERE estado = 'nuevo'").fetchone()["c"]
    recetas = con.execute("SELECT COUNT(*) c FROM recetas").fetchone()["c"]
    ultimos = con.execute("SELECT * FROM pedidos ORDER BY id DESC LIMIT 5").fetchall()
    con.close()
    return _render(request, 
        "admin/panel.html",
        _ctx(request, total_productos=total_productos, activos=activos, sin_stock=sin_stock,
             pedidos_nuevos=pedidos_nuevos, recetas=recetas, ultimos=ultimos),
    )


@app.get("/admin/productos", response_class=HTMLResponse)
def admin_productos(request: Request, categoria: str = ""):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    if categoria in db.CATEGORIAS:
        filas = con.execute(
            "SELECT * FROM productos WHERE categoria = ? ORDER BY id DESC", (categoria,)
        ).fetchall()
    else:
        categoria = ""
        filas = con.execute("SELECT * FROM productos ORDER BY categoria, id DESC").fetchall()
    filas = _con_foto(con, filas)
    con.close()
    return _render(request, 
        "admin/productos.html", _ctx(request, productos=filas, categoria=categoria)
    )


@app.get("/admin/productos/nuevo", response_class=HTMLResponse)
def admin_producto_nuevo(request: Request):
    redir = _guard(request)
    if redir:
        return redir
    return _render(request, 
        "admin/producto_form.html",
        _ctx(request, p=None, fotos=[], receta=None, error=""),
    )


@app.post("/admin/productos/nuevo")
def admin_producto_crear(
    request: Request,
    nombre: str = Form(...),
    categoria: str = Form(...),
    descripcion_corta: str = Form(""),
    descripcion: str = Form(""),
    precio: float = Form(0),
    presentacion: str = Form(""),
    es_por_unidad: str = Form(""),
    stock: int = Form(0),
    tiempo_entrega: str = Form(""),
    activo: str = Form(""),
    destacado: str = Form(""),
):
    redir = _guard(request)
    if redir:
        return redir
    if categoria not in db.CATEGORIAS:
        categoria = "pasteles"
    con = db.conectar()
    slug = db.slug_unico(con, nombre)
    con.execute(
        """INSERT INTO productos
           (nombre, slug, categoria, descripcion_corta, descripcion, precio,
            presentacion, es_por_unidad, stock, tiempo_entrega, activo, destacado)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (nombre.strip(), slug, categoria, descripcion_corta, descripcion, precio,
         presentacion, 1 if es_por_unidad else 0, stock, tiempo_entrega,
         1 if activo else 0, 1 if destacado else 0),
    )
    pid = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    con.commit()
    con.close()
    return RedirectResponse(f"/admin/productos/{pid}/editar", status_code=303)


@app.get("/admin/productos/{pid}/editar", response_class=HTMLResponse)
def admin_producto_editar(request: Request, pid: int):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    p = con.execute("SELECT * FROM productos WHERE id = ?", (pid,)).fetchone()
    if not p:
        con.close()
        return _render(request, "no_encontrado.html", _ctx(request), status_code=404)
    fotos = _fotos_de(con, pid)
    receta = _receta_de(con, pid)
    con.close()
    return _render(request, 
        "admin/producto_form.html",
        _ctx(request, p=p, fotos=fotos, receta=receta, error=""),
    )


@app.post("/admin/productos/{pid}/editar")
def admin_producto_guardar(
    request: Request,
    pid: int,
    nombre: str = Form(...),
    categoria: str = Form(...),
    descripcion_corta: str = Form(""),
    descripcion: str = Form(""),
    precio: float = Form(0),
    presentacion: str = Form(""),
    es_por_unidad: str = Form(""),
    stock: int = Form(0),
    tiempo_entrega: str = Form(""),
    activo: str = Form(""),
    destacado: str = Form(""),
):
    redir = _guard(request)
    if redir:
        return redir
    if categoria not in db.CATEGORIAS:
        categoria = "pasteles"
    con = db.conectar()
    slug = db.slug_unico(con, nombre, pid)
    con.execute(
        """UPDATE productos SET nombre=?, slug=?, categoria=?, descripcion_corta=?,
           descripcion=?, precio=?, presentacion=?, es_por_unidad=?, stock=?,
           tiempo_entrega=?, activo=?, destacado=? WHERE id=?""",
        (nombre.strip(), slug, categoria, descripcion_corta, descripcion, precio,
         presentacion, 1 if es_por_unidad else 0, stock, tiempo_entrega,
         1 if activo else 0, 1 if destacado else 0, pid),
    )
    con.commit()
    con.close()
    return RedirectResponse(f"/admin/productos/{pid}/editar", status_code=303)


@app.post("/admin/productos/{pid}/borrar")
def admin_producto_borrar(request: Request, pid: int):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    for foto in _fotos_de(con, pid):
        _borrar_archivo(foto["archivo"])
    con.execute("DELETE FROM productos WHERE id = ?", (pid,))
    con.commit()
    con.close()
    return RedirectResponse("/admin/productos", status_code=303)


@app.post("/admin/productos/{pid}/fotos")
async def admin_subir_fotos(
    request: Request,
    pid: int,
    fotos: list[UploadFile] = File(default=[]),
    alt: str = Form(""),
):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    existe = con.execute("SELECT id FROM productos WHERE id = ?", (pid,)).fetchone()
    if not existe:
        con.close()
        return RedirectResponse("/admin/productos", status_code=303)

    orden = con.execute(
        "SELECT COALESCE(MAX(orden), 0) AS m FROM fotos WHERE producto_id = ?", (pid,)
    ).fetchone()["m"]

    for subida in fotos or []:
        if not subida or not subida.filename:
            continue
        ext = Path(subida.filename).suffix.lower()
        if ext not in EXTENSIONES_OK:
            continue
        contenido = await subida.read()
        if not contenido or len(contenido) > MAX_FOTO_BYTES:
            continue
        nombre_archivo = f"{uuid.uuid4().hex}{ext}"
        (UPLOADS / nombre_archivo).write_bytes(contenido)
        orden += 1
        con.execute(
            "INSERT INTO fotos (producto_id, archivo, alt, orden) VALUES (?,?,?,?)",
            (pid, nombre_archivo, alt or "", orden),
        )
    con.commit()
    con.close()
    return RedirectResponse(f"/admin/productos/{pid}/editar", status_code=303)


@app.post("/admin/fotos/{fid}/borrar")
def admin_borrar_foto(request: Request, fid: int):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    foto = con.execute("SELECT * FROM fotos WHERE id = ?", (fid,)).fetchone()
    if foto:
        _borrar_archivo(foto["archivo"])
        con.execute("DELETE FROM fotos WHERE id = ?", (fid,))
        con.commit()
        pid = foto["producto_id"]
    else:
        pid = None
    con.close()
    return RedirectResponse(
        f"/admin/productos/{pid}/editar" if pid else "/admin/productos", status_code=303
    )


@app.post("/admin/productos/{pid}/receta")
def admin_guardar_receta(
    request: Request,
    pid: int,
    titulo: str = Form(""),
    rinde: str = Form(""),
    ingredientes: str = Form(""),
    procedimiento: str = Form(""),
    notas: str = Form(""),
):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    con.execute(
        """INSERT INTO recetas (producto_id, titulo, rinde, ingredientes, procedimiento, notas, actualizado)
           VALUES (?,?,?,?,?,?, datetime('now','localtime'))
           ON CONFLICT(producto_id) DO UPDATE SET
             titulo=excluded.titulo, rinde=excluded.rinde, ingredientes=excluded.ingredientes,
             procedimiento=excluded.procedimiento, notas=excluded.notas, actualizado=excluded.actualizado""",
        (pid, titulo, rinde, ingredientes, procedimiento, notas),
    )
    con.commit()
    con.close()
    return RedirectResponse(f"/admin/productos/{pid}/editar", status_code=303)


@app.get("/admin/recetas", response_class=HTMLResponse)
def admin_recetas(request: Request):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    filas = con.execute(
        """SELECT p.id, p.nombre, p.categoria, r.titulo, r.actualizado,
                  (r.id IS NOT NULL) AS tiene
           FROM productos p LEFT JOIN recetas r ON r.producto_id = p.id
           ORDER BY p.categoria, p.nombre"""
    ).fetchall()
    con.close()
    return _render(request, "admin/recetas.html", _ctx(request, filas=filas))


@app.get("/admin/pedidos", response_class=HTMLResponse)
def admin_pedidos(request: Request):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    pedidos = con.execute("SELECT * FROM pedidos ORDER BY id DESC").fetchall()
    con.close()
    detalle = {p["id"]: json.loads(p["items"]) for p in pedidos}
    return _render(request, 
        "admin/pedidos.html",
        _ctx(request, pedidos=pedidos, detalle=detalle, estados=db.ESTADOS_PEDIDO),
    )


@app.post("/admin/pedidos/{oid}/estado")
def admin_cambiar_estado(request: Request, oid: int, estado: str = Form(...)):
    redir = _guard(request)
    if redir:
        return redir
    if estado not in db.ESTADOS_PEDIDO:
        return RedirectResponse("/admin/pedidos", status_code=303)
    con = db.conectar()
    con.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (estado, oid))
    con.commit()
    con.close()
    return RedirectResponse("/admin/pedidos", status_code=303)


# --------------------------------------------------------------------------
# Zonas de envio
# --------------------------------------------------------------------------
@app.get("/admin/zonas", response_class=HTMLResponse)
def admin_zonas(request: Request):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    zonas = con.execute("SELECT * FROM zonas_envio ORDER BY orden, precio, id").fetchall()
    con.close()
    return _render(request, 
        "admin/zonas.html",
        _ctx(request, zonas=zonas, config=_pago_config(), error=""),
    )


@app.post("/admin/zonas/nueva")
def admin_zona_crear(
    request: Request,
    nombre: str = Form(...),
    precio: float = Form(0),
    a_convenir: str = Form(""),
    activo: str = Form(""),
):
    redir = _guard(request)
    if redir:
        return redir
    nombre = nombre.strip()
    if not nombre:
        return RedirectResponse("/admin/zonas", status_code=303)
    con = db.conectar()
    orden = con.execute(
        "SELECT COALESCE(MAX(orden), 0) + 1 AS o FROM zonas_envio"
    ).fetchone()["o"]
    con.execute(
        """INSERT INTO zonas_envio (nombre, precio, a_convenir, activo, orden)
           VALUES (?,?,?,?,?)""",
        (nombre, max(0.0, precio), 1 if a_convenir else 0, 1 if activo else 0, orden),
    )
    con.commit()
    con.close()
    return RedirectResponse("/admin/zonas", status_code=303)


@app.post("/admin/zonas/{zid}/guardar")
def admin_zona_guardar(
    request: Request,
    zid: int,
    nombre: str = Form(...),
    precio: float = Form(0),
    a_convenir: str = Form(""),
    activo: str = Form(""),
    orden: int = Form(0),
):
    redir = _guard(request)
    if redir:
        return redir
    nombre = nombre.strip()
    if not nombre:
        return RedirectResponse("/admin/zonas", status_code=303)
    con = db.conectar()
    con.execute(
        """UPDATE zonas_envio SET nombre=?, precio=?, a_convenir=?, activo=?, orden=?
           WHERE id=?""",
        (nombre, max(0.0, precio), 1 if a_convenir else 0, 1 if activo else 0, orden, zid),
    )
    con.commit()
    con.close()
    return RedirectResponse("/admin/zonas", status_code=303)


@app.post("/admin/zonas/{zid}/borrar")
def admin_zona_borrar(request: Request, zid: int):
    redir = _guard(request)
    if redir:
        return redir
    con = db.conectar()
    con.execute("DELETE FROM zonas_envio WHERE id = ?", (zid,))
    con.commit()
    con.close()
    return RedirectResponse("/admin/zonas", status_code=303)


def _borrar_archivo(nombre: str) -> None:
    """Borra la foto del disco sin salir de la carpeta de subidas."""
    ruta = (UPLOADS / nombre).resolve()
    if UPLOADS.resolve() in ruta.parents and ruta.exists():
        try:
            ruta.unlink()
        except OSError:
            pass
