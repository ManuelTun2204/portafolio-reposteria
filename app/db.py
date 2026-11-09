"""Base de datos del portafolio de reposteria.

SQLite a proposito: un solo archivo, sin servidor, sin contrasenas y sin
consumir RAM extra en esta PC. Si algun dia hace falta multiusuario real, se
migra a Postgres de `infra` sin cambiar las consultas (son SQL plano).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "portafolio.db")))

# Categorias fijas: la galeria se arma con estas cuatro secciones.
CATEGORIAS = {
    "pasteles": "Pasteles",
    "postres": "Postres",
    "promociones": "Promociones",
    "novedades": "Novedades",
}

ESTADOS_PEDIDO = [
    "nuevo",
    "anticipo recibido",
    "confirmado",
    "en preparacion",
    "entregado",
    "cancelado",
]

# Zonas de envio de ejemplo. Los precios son de muestra: el administrador las
# edita en /admin/zonas con sus colonias y sus tarifas reales. `a_convenir` se
# usa para lugares fuera de cobertura: el cliente ve "por confirmar" en vez de
# un precio que no es el suyo.
ZONAS_DEMO = [
    ("Zona 1 · Centro y colonias cercanas", 30.0, 0),
    ("Zona 2 · Resto de la ciudad", 50.0, 0),
    ("Foránea · se confirma por WhatsApp", 0.0, 1),
]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre            TEXT    NOT NULL,
    slug              TEXT    NOT NULL UNIQUE,
    categoria         TEXT    NOT NULL,
    descripcion_corta TEXT    NOT NULL DEFAULT '',
    descripcion       TEXT    NOT NULL DEFAULT '',
    precio            REAL    NOT NULL DEFAULT 0,
    presentacion      TEXT    NOT NULL DEFAULT '',
    es_por_unidad     INTEGER NOT NULL DEFAULT 0,
    stock             INTEGER NOT NULL DEFAULT 0,
    tiempo_entrega    TEXT    NOT NULL DEFAULT '',
    activo            INTEGER NOT NULL DEFAULT 1,
    destacado         INTEGER NOT NULL DEFAULT 0,
    creado            TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS fotos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    archivo     TEXT    NOT NULL,
    alt         TEXT    NOT NULL DEFAULT '',
    orden       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS recetas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id   INTEGER NOT NULL UNIQUE REFERENCES productos(id) ON DELETE CASCADE,
    titulo        TEXT    NOT NULL DEFAULT '',
    rinde         TEXT    NOT NULL DEFAULT '',
    ingredientes  TEXT    NOT NULL DEFAULT '',
    procedimiento TEXT    NOT NULL DEFAULT '',
    notas         TEXT    NOT NULL DEFAULT '',
    actualizado   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS pedidos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    folio          TEXT    NOT NULL UNIQUE,
    cliente        TEXT    NOT NULL,
    telefono       TEXT    NOT NULL DEFAULT '',
    email          TEXT    NOT NULL DEFAULT '',
    entrega        TEXT    NOT NULL DEFAULT '',
    entrega_tipo   TEXT    NOT NULL DEFAULT '',
    zona_nombre    TEXT    NOT NULL DEFAULT '',
    direccion      TEXT    NOT NULL DEFAULT '',
    subtotal       REAL    NOT NULL DEFAULT 0,
    envio          REAL    NOT NULL DEFAULT 0,
    envio_convenir INTEGER NOT NULL DEFAULT 0,
    total          REAL    NOT NULL DEFAULT 0,
    anticipo       REAL    NOT NULL DEFAULT 0,
    notas          TEXT    NOT NULL DEFAULT '',
    items          TEXT    NOT NULL,
    estado         TEXT    NOT NULL DEFAULT 'nuevo',
    creado         TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS zonas_envio (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT    NOT NULL,
    precio     REAL    NOT NULL DEFAULT 0,
    a_convenir INTEGER NOT NULL DEFAULT 0,
    activo     INTEGER NOT NULL DEFAULT 1,
    orden      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_productos_categoria ON productos(categoria);
CREATE INDEX IF NOT EXISTS idx_fotos_producto ON fotos(producto_id);
CREATE INDEX IF NOT EXISTS idx_zonas_orden ON zonas_envio(orden);
"""

# Columnas que se agregaron despues de la primera version. `ALTER TABLE` en
# SQLite solo sabe agregar, asi que se aplican una por una y solo si faltan.
COLUMNAS_NUEVAS_PEDIDOS = {
    "entrega_tipo": "TEXT NOT NULL DEFAULT ''",
    "zona_nombre": "TEXT NOT NULL DEFAULT ''",
    "direccion": "TEXT NOT NULL DEFAULT ''",
    "subtotal": "REAL NOT NULL DEFAULT 0",
    "envio": "REAL NOT NULL DEFAULT 0",
    "envio_convenir": "INTEGER NOT NULL DEFAULT 0",
    "anticipo": "REAL NOT NULL DEFAULT 0",
}


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar() -> None:
    """Crea el esquema, migra bases viejas y siembra el catalogo demo."""
    con = conectar()
    con.executescript(ESQUEMA)
    _migrar(con)
    vacia = con.execute("SELECT COUNT(*) AS c FROM productos").fetchone()["c"] == 0
    if vacia:
        _sembrar(con)
    if con.execute("SELECT COUNT(*) AS c FROM zonas_envio").fetchone()["c"] == 0:
        _sembrar_zonas(con)
    con.commit()
    con.close()


def _migrar(con: sqlite3.Connection) -> None:
    """Agrega las columnas nuevas a una base creada con la version anterior."""
    existentes = {fila["name"] for fila in con.execute("PRAGMA table_info(pedidos)")}
    for nombre, definicion in COLUMNAS_NUEVAS_PEDIDOS.items():
        if nombre not in existentes:
            con.execute(f"ALTER TABLE pedidos ADD COLUMN {nombre} {definicion}")
    # Pedidos viejos: el total era el subtotal porque no habia envio.
    con.execute("UPDATE pedidos SET subtotal = total WHERE subtotal = 0 AND total > 0")
    con.commit()


def _sembrar_zonas(con: sqlite3.Connection) -> None:
    """Zonas de envio de ejemplo. Se editan o se borran desde /admin/zonas."""
    for orden, (nombre, precio, a_convenir) in enumerate(ZONAS_DEMO, start=1):
        con.execute(
            "INSERT INTO zonas_envio (nombre, precio, a_convenir, activo, orden) VALUES (?,?,?,1,?)",
            (nombre, precio, a_convenir, orden),
        )
    con.commit()


def _sembrar(con: sqlite3.Connection) -> None:
    """Catalogo inicial. Es contenido de ejemplo, NO inventario real:

    existe para que la tienda no arranque vacia y para poder probar el flujo
    completo (galeria -> detalle -> carrito -> pedido) desde el primer minuto.
    Se puede borrar o editar desde el panel de administracion.
    """
    demo = [
        ("Pastel de chocolate belga", "pasteles", "Bizcocho humedo con ganache 70% y sal de mar.",
         "Tres capas de bizcocho de cacao con ganache de chocolate belga 70%, relleno de "
         "crema de avellana y un toque de sal de mar. Se decora con virutas de chocolate.",
         650.0, "Pastel entero de 20 cm (12 porciones)", 0, 6, "48 h", 1, 1),
        ("Cheesecake de frutos rojos", "pasteles", "Horneado, base de galleta y coulis natural.",
         "Cheesecake horneado estilo New York sobre base de galleta mantequillada, "
         "coronado con coulis de frutos rojos de temporada. Se entrega refrigerado.",
         480.0, "Pastel entero de 18 cm (10 porciones)", 0, 4, "36 h", 1, 1),
        ("Macarons surtidos", "postres", "Caja de 12 piezas, sabores de temporada.",
         "Doce macarons franceses con almendra molida y relleno de ganache. "
         "Sabores: frambuesa, pistache, vainilla, limon y chocolate.",
         320.0, "Caja de 12 piezas", 0, 10, "24 h", 1, 0),
        ("Concha rellena de cajeta", "postres", "Pan dulce tradicional con relleno artesanal.",
         "Concha de mantequilla recien horneada, rellena de cajeta quemada artesanal. "
         "Se vende por pieza.",
         35.0, "Pieza individual", 1, 40, "Mismo dia", 1, 0),
        ("Combo cumpleanos", "promociones", "Pastel + 12 cupcakes + velas y platos.",
         "Pastel de 18 cm del sabor que elijas, doce cupcakes decorados a juego, "
         "velas, platos y servilletas. Pensado para 10 a 12 personas.",
         890.0, "Combo para 12 personas", 0, 3, "72 h", 1, 1),
        ("Galletas de temporada", "novedades", "Nueva receta de temporada, por pieza.",
         "Galleta de avena y nuez con trozos de chocolate semiamargo. "
         "Receta nueva de esta temporada, horneada el mismo dia.",
         28.0, "Pieza individual", 1, 60, "Mismo dia", 1, 1),
    ]

    for (nombre, categoria, corta, descripcion, precio, presentacion,
         por_unidad, stock, entrega, activo, destacado) in demo:
        slug = _slug(nombre)
        con.execute(
            """INSERT INTO productos
               (nombre, slug, categoria, descripcion_corta, descripcion, precio,
                presentacion, es_por_unidad, stock, tiempo_entrega, activo, destacado)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nombre, slug, categoria, corta, descripcion, precio, presentacion,
             por_unidad, stock, entrega, activo, destacado),
        )
        pid = con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        if categoria == "pasteles":
            con.execute(
                """INSERT INTO recetas (producto_id, titulo, rinde, ingredientes, procedimiento, notas)
                   VALUES (?,?,?,?,?,?)""",
                (pid, f"Receta base: {nombre}", "12 porciones",
                 "200 g harina\n200 g azucar\n80 g cacao\n3 huevos\n200 ml leche\n"
                 "150 g mantequilla\n1 cda polvo para hornear\npizca de sal",
                 "1. Batir mantequilla con azucar.\n2. Agregar huevos uno a uno.\n"
                 "3. Alternar harina cernida con leche.\n4. Hornear 35 min a 180 C.\n"
                 "5. Enfriar y rellenar.",
                 "Receta interna: no se muestra al cliente."),
            )
    con.commit()


def _slug(texto: str) -> str:
    import re
    import unicodedata

    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()
    return base or "producto"


def slug_unico(con: sqlite3.Connection, nombre: str, producto_id: int | None = None) -> str:
    """Genera un slug libre. Evita que dos productos choquen en la URL."""
    base = _slug(nombre)
    candidato = base
    n = 2
    while True:
        fila = con.execute(
            "SELECT id FROM productos WHERE slug = ?", (candidato,)
        ).fetchone()
        if not fila or (producto_id is not None and fila["id"] == producto_id):
            return candidato
        candidato = f"{base}-{n}"
        n += 1
