import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import re
import shutil
import hashlib
import secrets
import requests
import urllib3
from bs4 import BeautifulSoup
from fpdf import FPDF
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO

try:
    from streamlit_js_eval import streamlit_js_eval
except Exception:
    streamlit_js_eval = None

# =============================================================
# PEDIDOS POINTER - ERP/POS LOCAL V7
# Streamlit + SQLite
# Incluye: precio único, tasa BCV automática/manual desde BCV, fotos por SKU,
# contrapedido sin stock, descuentos por usuario, créditos a días, abonos, reportes,
# comisiones, alertas y estados de cuenta.
# =============================================================

APP_NAME = "Sistema de pedidos pointer V21 Responsive"
DB_NAME = "color_insumos_local_v5.db"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IMG_DIR = STATIC_DIR / "fotos"
COMPROBANTES_DIR = STATIC_DIR / "comprobantes"
IMPORT_DIRS = [BASE_DIR / "importar_fotos", BASE_DIR / "importar_fotos2"]

for d in [STATIC_DIR, IMG_DIR, COMPROBANTES_DIR] + IMPORT_DIRS:
    d.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title=APP_NAME, layout="wide", page_icon="🧾")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -----------------------------
# ESTILOS
# -----------------------------
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.metric-card {background:#fff;border:1px solid #e9ecef;border-radius:16px;padding:16px;box-shadow:0 2px 10px rgba(0,0,0,.04)}
.small-muted {font-size:.85rem;color:#6c757d;}
.badge {display:inline-block;padding:3px 8px;border-radius:999px;font-size:.78rem;font-weight:700;}
.badge-ok {background:#e9f7ef;color:#198754;}
.badge-warn {background:#fff3cd;color:#856404;}
.badge-danger {background:#f8d7da;color:#842029;}
.badge-info {background:#e7f1ff;color:#0d6efd;}
.product-row {border-bottom:1px solid #eee;padding:8px 0;}
.catalog-img img {object-fit:cover;border-radius:8px;}
.total-box {background:#f8f9fa;border:1px solid #e9ecef;border-radius:16px;padding:18px;}
.stButton button {border-radius:10px;}
.mobile-product-card {border:1px solid #e5e7eb;border-radius:18px;padding:14px;margin:10px 0;box-shadow:0 2px 10px rgba(0,0,0,.04);background:#fff;}
.mobile-product-title {font-size:1.05rem;font-weight:800;color:#1f77b4;line-height:1.2;margin:6px 0 2px 0;}
.mobile-price {font-size:1.55rem;font-weight:900;margin:6px 0 0 0;}
.mobile-ves {color:#6b7280;font-size:.9rem;font-weight:700;}
.mobile-total-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;}
@media (max-width: 768px) {
  .block-container {padding-left:.7rem;padding-right:.7rem;padding-top:.6rem;}
  .mobile-total-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
  .desktop-help {display:none;}
  div[data-testid="stHorizontalBlock"] {gap: .35rem;}
  .stButton button {min-height:42px;}
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# BASE DE DATOS
# -----------------------------
@st.cache_resource
def get_conn():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def q(sql, params=(), fetch=False, many=False):
    conn = get_conn()
    cur = conn.cursor()
    if many:
        cur.executemany(sql, params)
    else:
        cur.execute(sql, params)
    conn.commit()
    if fetch:
        return cur.fetchall()
    return cur

def column_exists(table, column):
    rows = q(f"PRAGMA table_info({table})", fetch=True)
    return any(r[1] == column for r in rows)

def add_col(table, column, definition):
    if not column_exists(table, column):
        q(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 180000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    # Compatibilidad: si por accidente queda una clave en texto plano antigua.
    if not stored.startswith("pbkdf2_sha256$"):
        return password == stored
    try:
        _, salt, hex_digest = stored.split("$", 2)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 180000).hex()
        return secrets.compare_digest(digest, hex_digest)
    except Exception:
        return False

def init_db():
    q("""
    CREATE TABLE IF NOT EXISTS usuarios (
        username TEXT PRIMARY KEY,
        password_hash TEXT,
        nombre TEXT,
        rol TEXT DEFAULT 'cliente',
        telefono TEXT,
        rif TEXT,
        direccion TEXT,
        ciudad TEXT,
        activo INTEGER DEFAULT 1,
        aplica_zelle_30 INTEGER DEFAULT 1,
        aplica_bcv_10_100 INTEGER DEFAULT 1,
        credito_habilitado INTEGER DEFAULT 0,
        limite_credito_usd REAL DEFAULT 0,
        dias_credito INTEGER DEFAULT 10,
        notas TEXT,
        vendedor_username TEXT,
        comision_pct REAL DEFAULT 0,
        creado_en TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS productos (
        sku TEXT PRIMARY KEY,
        descripcion TEXT,
        precio REAL DEFAULT 0,
        categoria TEXT DEFAULT 'General',
        stock_actual REAL DEFAULT 0,
        stock_minimo REAL DEFAULT 0,
        foto_path TEXT,
        activo INTEGER DEFAULT 1,
        creado_en TEXT,
        actualizado_en TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS carritos (
        username TEXT PRIMARY KEY,
        data TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        cliente_nombre TEXT,
        fecha TEXT,
        items TEXT,
        metodo_pago TEXT,
        tipo_pago TEXT DEFAULT 'contado',
        subtotal_usd REAL DEFAULT 0,
        descuento_usd REAL DEFAULT 0,
        total_usd REAL DEFAULT 0,
        tasa_bcv REAL DEFAULT 0,
        total_ves REAL DEFAULT 0,
        status TEXT DEFAULT 'Pendiente',
        credito_id INTEGER,
        notas TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS creditos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_id INTEGER,
        username TEXT,
        cliente_nombre TEXT,
        fecha_inicio TEXT,
        fecha_vencimiento TEXT,
        monto_usd REAL DEFAULT 0,
        monto_ves REAL DEFAULT 0,
        tasa_bcv REAL DEFAULT 0,
        saldo_usd REAL DEFAULT 0,
        status TEXT DEFAULT 'Pendiente',
        notas TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS abonos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        credito_id INTEGER,
        username TEXT,
        fecha TEXT,
        monto_usd REAL DEFAULT 0,
        monto_ves REAL DEFAULT 0,
        metodo TEXT,
        referencia TEXT,
        comprobante_path TEXT,
        status TEXT DEFAULT 'Pendiente de validar',
        validado_por TEXT,
        fecha_validacion TEXT,
        notas TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS movimientos_inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT,
        fecha TEXT,
        tipo TEXT,
        cantidad REAL,
        stock_resultante REAL,
        usuario TEXT,
        motivo TEXT,
        referencia TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS configuracion (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )
    """)
    q("""
    CREATE TABLE IF NOT EXISTS auditoria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        usuario TEXT,
        accion TEXT,
        entidad TEXT,
        entidad_id TEXT,
        detalle TEXT
    )
    """)

    # Migraciones suaves para bases anteriores.
    for table, cols in {
        "usuarios": [
            ("password_hash", "TEXT"), ("activo", "INTEGER DEFAULT 1"), ("aplica_zelle_30", "INTEGER DEFAULT 1"),
            ("aplica_bcv_10_100", "INTEGER DEFAULT 1"), ("credito_habilitado", "INTEGER DEFAULT 0"),
            ("limite_credito_usd", "REAL DEFAULT 0"), ("dias_credito", "INTEGER DEFAULT 10"), ("notas", "TEXT"), ("vendedor_username", "TEXT"), ("comision_pct", "REAL DEFAULT 0"),
        ],
        "productos": [("stock_actual", "REAL DEFAULT 0"), ("stock_minimo", "REAL DEFAULT 0"), ("activo", "INTEGER DEFAULT 1")],
        "pedidos": [("tipo_pago", "TEXT DEFAULT 'contado'"), ("credito_id", "INTEGER"), ("notas", "TEXT"), ("tasa_bcv", "REAL DEFAULT 0"), ("total_ves", "REAL DEFAULT 0")],
    }.items():
        rows = q("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,), fetch=True)
        if rows:
            for col, definition in cols:
                add_col(table, col, definition)

    admin = q("SELECT username FROM usuarios WHERE username=?", ("colorinsumos@gmail.com",), fetch=True)
    if not admin:
        q("""
        INSERT INTO usuarios (username,password_hash,nombre,rol,telefono,activo,aplica_zelle_30,aplica_bcv_10_100,credito_habilitado,creado_en)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """, ("colorinsumos@gmail.com", hash_password("20880157"), "Admin Pedidos Pointer", "admin", "04127757053", 1, 1, 1, 1, now()))
    set_config_default("tasa_bcv", "0")
    set_config_default("tasa_eur", "0")
    set_config_default("tasa_p2p", "0")
    set_config_default("desc_sug", "0")
    set_config_default("fecha_tasa_bcv", "Sin actualizar")
    set_config_default("fuente_tasa_bcv", "Manual")
    set_config_default("descuento_divisas_pct", "30")
    set_config_default("descuento_bcv_100_pct", "10")
    set_config_default("nombre_empresa", "Sistema de pedidos pointer V21 Responsive")
    set_config_default("telefono_empresa", "04127757053")
    set_config_default("instagram_empresa", "@color.insumos")

def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def now_file():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def log_event(accion, entidad=None, entidad_id=None, detalle=""):
    """Registra acciones administrativas importantes sin interrumpir el flujo si falla."""
    try:
        usuario = "sistema"
        if "user" in st.session_state and st.session_state.user:
            usuario = st.session_state.user.get("username", "sistema")
        q(
            "INSERT INTO auditoria (fecha, usuario, accion, entidad, entidad_id, detalle) VALUES (?,?,?,?,?,?)",
            (now(), usuario, str(accion or ""), str(entidad or ""), str(entidad_id or ""), str(detalle or "")),
        )
    except Exception:
        # La auditoría no debe bloquear operaciones como cambiar estados o validar abonos.
        pass


def cerrar_credito_y_finalizar_pedido(pedido_id, actor_username, metodo="Cierre administrativo", referencia="", notas=""):
    """Cierra cualquier crédito asociado a un pedido, registra abono validado si hay saldo y finaliza el pedido."""
    pedido_id = int(pedido_id)
    rows = q("SELECT * FROM creditos WHERE pedido_id=? ORDER BY id DESC LIMIT 1", (pedido_id,), fetch=True)
    if not rows:
        q("UPDATE pedidos SET status='Finalizado' WHERE id=?", (pedido_id,))
        log_event("Finalizar pedido sin crédito", "pedidos", pedido_id, "No tenía crédito asociado")
        return False, "Pedido finalizado. No tenía crédito asociado."

    cr = rows[0]
    credito_id = int(cr["id"])
    saldo = float(cr["saldo_usd"] or 0)
    cliente_username = cr["username"]

    if saldo > 0.009:
        tasa = get_tasa_bcv()
        q("""INSERT INTO abonos (credito_id,username,fecha,monto_usd,monto_ves,metodo,referencia,comprobante_path,status,validado_por,fecha_validacion,notas)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          (credito_id, cliente_username, now(), saldo, saldo*tasa, metodo, referencia, None, "Validado", actor_username, now(), notas or "Cierre automático al finalizar pedido."))

    q("UPDATE creditos SET saldo_usd=0, status='Pagado', notas=COALESCE(notas,'') || ? WHERE id=?",
      (f"\n[{now()}] Crédito cerrado automáticamente por {actor_username}. Método: {metodo}. Ref: {referencia}. {notas}", credito_id))
    q("UPDATE pedidos SET status='Finalizado' WHERE id=?", (pedido_id,))
    log_event("Cerrar crédito y finalizar pedido", "pedidos", pedido_id, f"Credito={credito_id}; saldo_cerrado={saldo}; metodo={metodo}; ref={referencia}")
    return True, f"Crédito #{credito_id} cerrado como Pagado y pedido #{pedido_id} marcado como Finalizado."

def marcar_credito_pagado_y_finalizar_pedido(credito_id, actor_username, detalle="Cambio manual de estado de crédito a Pagado"):
    """Marca crédito como pagado, saldo 0, y finaliza automáticamente su pedido asociado."""
    credito_id = int(credito_id)
    rows = q("SELECT * FROM creditos WHERE id=?", (credito_id,), fetch=True)
    if not rows:
        return False, "Crédito no encontrado."
    cr = rows[0]
    pedido_id = int(cr["pedido_id"]) if cr["pedido_id"] is not None else None
    saldo = float(cr["saldo_usd"] or 0)
    if saldo > 0.009:
        tasa = get_tasa_bcv()
        q("""INSERT INTO abonos (credito_id,username,fecha,monto_usd,monto_ves,metodo,referencia,comprobante_path,status,validado_por,fecha_validacion,notas)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          (credito_id, cr["username"], now(), saldo, saldo*tasa, "Cierre administrativo", "CIERRE-MANUAL", None, "Validado", actor_username, now(), detalle))
    q("UPDATE creditos SET saldo_usd=0, status='Pagado', notas=COALESCE(notas,'') || ? WHERE id=?",
      (f"\n[{now()}] Marcado como Pagado por {actor_username}. {detalle}", credito_id))
    if pedido_id:
        q("UPDATE pedidos SET status='Finalizado' WHERE id=?", (pedido_id,))
        log_event("Crédito pagado finaliza pedido", "creditos", credito_id, f"Pedido={pedido_id}; saldo_cerrado={saldo}")
        return True, f"Crédito #{credito_id} pagado y pedido #{pedido_id} finalizado."
    log_event("Crédito pagado sin pedido", "creditos", credito_id, f"saldo_cerrado={saldo}")
    return True, f"Crédito #{credito_id} pagado. No tenía pedido asociado."


def set_config_default(clave, valor):
    exists = q("SELECT clave FROM configuracion WHERE clave=?", (clave,), fetch=True)
    if not exists:
        q("INSERT INTO configuracion (clave,valor) VALUES (?,?)", (clave, str(valor)))

def get_config(clave, default=""):
    row = q("SELECT valor FROM configuracion WHERE clave=?", (clave,), fetch=True)
    return row[0]["valor"] if row else default

def set_config(clave, valor):
    q("INSERT OR REPLACE INTO configuracion (clave,valor) VALUES (?,?)", (clave, str(valor)))

# -----------------------------
# UTILIDADES
# -----------------------------
def money_usd(x):
    try: return f"${float(x):,.2f}"
    except: return "$0.00"

def money_ves(x):
    try: return f"Bs. {float(x):,.2f}"
    except: return "Bs. 0.00"

def parse_float(v, default=0.0):
    try:
        if v is None: return default
        return float(str(v).replace("$", "").replace("Bs", "").replace(".", "").replace(",", ".") if str(v).count(",") == 1 and str(v).count(".") > 1 else str(v).replace(",", "."))
    except Exception:
        try: return float(v)
        except: return default

def auto_categoria(desc):
    d = (desc or "").lower()
    if any(k in d for k in ["lapiz", "lápiz", "boligrafo", "marcador", "resaltador", "pluma"]): return "Escritura"
    if any(k in d for k in ["papel", "cartulina", "resma", "rollo", "vinil", "sublimacion", "sublimación"]): return "Papelería e impresión"
    if any(k in d for k in ["pega", "silicon", "cinta", "adhesivo"]): return "Adhesivos"
    if any(k in d for k in ["plancha", "plotter", "impresora", "cameo", "maquina", "máquina"]): return "Equipos"
    if any(k in d for k in ["tijera", "cutter", "exacto", "regla"]): return "Corte y medición"
    return "General"

def get_tasa_bcv():
    return parse_float(get_config("tasa_bcv", "0"), 0)

def _extraer_tasa_desde_html_bcv(html: str):
    """Extrae únicamente el dólar BCV desde el HTML oficial del BCV."""
    if not html:
        return None

    # 1) Método principal: estructura oficial conocida: div id="dolar" > strong
    try:
        soup = BeautifulSoup(html, "html.parser")
        box = soup.find("div", {"id": "dolar"})
        if box:
            strong = box.find("strong")
            if strong:
                val = parse_float(strong.get_text(strip=True), None)
                if val and val > 1:
                    return val
    except Exception:
        pass

    # 2) Respaldos por regex por si el HTML cambia levemente.
    patrones = [
        r'id=["\']dolar["\'][\s\S]{0,3000}?<strong[^>]*>\s*([0-9\.,]+)\s*</strong>',
        r'Dólar[\s\S]{0,3000}?<strong[^>]*>\s*([0-9\.,]+)\s*</strong>',
        r'dolar[\s\S]{0,3000}?<strong[^>]*>\s*([0-9\.,]+)\s*</strong>',
    ]
    for patron in patrones:
        m = re.search(patron, html, flags=re.IGNORECASE)
        if m:
            val = parse_float(m.group(1), None)
            if val and val > 1:
                return val
    return None


def obtener_dolar_bcv_oficial():
    """
    Obtiene SOLO el dólar BCV desde bcv.org.ve.
    Devuelve: (tasa, fuente, error)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    urls = [
        ("https://www.bcv.org.ve/", "BCV oficial - página principal"),
        ("https://www.bcv.org.ve/seccionportal/tipo-de-cambio-oficial-del-bcv", "BCV oficial - tipo de cambio"),
        # En algunas redes el HTTPS del BCV falla; dejamos HTTP como último intento.
        ("http://www.bcv.org.ve/", "BCV oficial - página principal HTTP"),
    ]

    errores = []
    for url, fuente in urls:
        try:
            r = requests.get(url, headers=headers, verify=False, timeout=15)
            if not r.ok:
                errores.append(f"{fuente}: HTTP {r.status_code}")
                continue

            # El BCV a veces responde con codificación no declarada correctamente.
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding or "utf-8"
            html = r.text

            tasa = _extraer_tasa_desde_html_bcv(html)
            if tasa and tasa > 1:
                return float(tasa), fuente, None
            errores.append(f"{fuente}: no se encontró el div/valor del dólar en el HTML")
        except Exception as e:
            errores.append(f"{fuente}: {type(e).__name__}: {e}")

    return None, None, " | ".join(errores) if errores else "No se pudo conectar con bcv.org.ve"


def obtener_tasas_completas():
    """
    Compatibilidad con versiones anteriores: ahora solo devuelve USD BCV.
    Ya no consulta EUR ni P2P porque el sistema solo necesita dólar BCV.
    """
    tasa, fuente, error = obtener_dolar_bcv_oficial()
    return {
        "USD": tasa,
        "fuente": fuente or "BCV oficial",
        "error": error,
    }


def obtener_tasa_bcv_automatica():
    """Mantiene compatibilidad: devuelve (tasa_usd, fuente)."""
    tasa, fuente, _error = obtener_dolar_bcv_oficial()
    if tasa and tasa > 1:
        return tasa, fuente
    return None, None

def cargar_carrito(username):
    row = q("SELECT data FROM carritos WHERE username=?", (username,), fetch=True)
    if not row or not row[0]["data"]: return {}
    try: return json.loads(row[0]["data"])
    except Exception: return {}

def guardar_carrito(username, data):
    q("INSERT OR REPLACE INTO carritos (username,data) VALUES (?,?)", (username, json.dumps(data, ensure_ascii=False)))

def limpiar_carrito(username):
    q("DELETE FROM carritos WHERE username=?", (username,))

def usuarios_asignados_a_vendedor(vendedor_username):
    rows = q("SELECT username FROM usuarios WHERE vendedor_username=? AND activo=1", (vendedor_username,), fetch=True)
    return [r["username"] for r in rows]

def usernames_visibles_para_usuario(user_dict):
    """Admin ve todos; vendedor ve sus usuarios asignados y sus propios registros; cliente solo sus registros."""
    if user_dict["rol"] == "admin":
        rows = q("SELECT username FROM usuarios", fetch=True)
        return [r["username"] for r in rows]
    if user_dict["rol"] == "vendedor":
        return [user_dict["username"]] + usuarios_asignados_a_vendedor(user_dict["username"])
    return [user_dict["username"]]

def sql_in_clause(values):
    if not values:
        return "('')", []
    return "(" + ",".join(["?"] * len(values)) + ")", list(values)

def get_vendedores():
    rows = q("SELECT username, nombre FROM usuarios WHERE rol='vendedor' AND activo=1 ORDER BY nombre", fetch=True)
    return [(r["username"], r["nombre"]) for r in rows]

def get_producto(sku):
    rows = q("SELECT * FROM productos WHERE sku=?", (sku,), fetch=True)
    return rows[0] if rows else None


def get_user(username):
    """Devuelve un usuario por username/correo como sqlite3.Row o None."""
    if not username:
        return None
    rows = q("SELECT * FROM usuarios WHERE username=?", (username,), fetch=True)
    return rows[0] if rows else None

def registrar_movimiento(sku, tipo, cantidad, usuario, motivo, referencia=""):
    prod = get_producto(sku)
    stock = prod["stock_actual"] if prod else 0
    q("""INSERT INTO movimientos_inventario (sku,fecha,tipo,cantidad,stock_resultante,usuario,motivo,referencia)
         VALUES (?,?,?,?,?,?,?,?)""", (sku, now(), tipo, cantidad, stock, usuario, motivo, referencia))

def _pdf_escape(text):
    text = str(text or "")
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text

def _pdf_clean(text):
    """Simplifica texto para PDF básico sin dependencias externas."""
    repl = {
        "á":"a","é":"e","í":"i","ó":"o","ú":"u","ñ":"n","Á":"A","É":"E","Í":"I","Ó":"O","Ú":"U","Ñ":"N",
        "–":"-","—":"-","“":"\"","”":"\"","’":"'","•":"-","✅":"","📦":"","🧾":""
    }
    text = str(text or "")
    for a,b in repl.items(): text = text.replace(a,b)
    return text

def _wrap(text, width=86):
    text = _pdf_clean(text)
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines or [""]

def generar_pdf_nota_entrega(pedido_row):
    """Genera una nota de entrega en PDF con estructura similar al recibo clásico."""
    pedido = dict(pedido_row)
    user_row = get_user(pedido.get("username"))
    credito = None
    if pedido.get("credito_id"):
        rows = q("SELECT * FROM creditos WHERE id=?", (pedido.get("credito_id"),), fetch=True)
        credito = dict(rows[0]) if rows else None

    # Si el cliente tiene vendedor asignado, la nota sale con los datos del vendedor
    # para proteger la cadena comercial. Si no tiene vendedor, usa los datos generales.
    vendedor_row = None
    if user_row and "vendedor_username" in user_row.keys() and user_row["vendedor_username"]:
        vendedor_row = get_user(user_row["vendedor_username"])

    if vendedor_row:
        empresa = _pdf_clean(vendedor_row["nombre"] or vendedor_row["username"] or "Vendedor asignado")
        telefono = _pdf_clean(vendedor_row["telefono"] or "")
        rif_emisor = _pdf_clean(vendedor_row["rif"] or "")
        ciudad_emisor = _pdf_clean(vendedor_row["ciudad"] or "")
        direccion_emisor = _pdf_clean(vendedor_row["direccion"] or "")
        subtitulo_emisor = "Nota de entrega"
        contacto_emisor = " | ".join([x for x in [f"Telefono: {telefono}" if telefono else "", f"RIF/CI: {rif_emisor}" if rif_emisor else "", ciudad_emisor] if x])
    else:
        empresa = _pdf_clean(get_config("nombre_empresa", "Sistema de pedidos pointer V21 Responsive"))
        telefono = _pdf_clean(get_config("telefono_empresa", "04127757053"))
        instagram = _pdf_clean(get_config("instagram_empresa", "@color.insumos"))
        direccion_emisor = ""
        subtitulo_emisor = "Sistema de pedidos contra pedido"
        contacto_emisor = f"Contacto: {telefono} | Instagram: {instagram}"

    items = json.loads(pedido.get("items") or "{}")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()

    def cell(txt, w=0, h=6, border=0, ln=1, align="L", fill=False, size=9, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.cell(w, h, _pdf_clean(txt), border=border, ln=ln, align=align, fill=fill)

    def multi(txt, w=190, h=5, border=0, align="L", size=9, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.multi_cell(w, h, _pdf_clean(txt), border=border, align=align)

    # Encabezado
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(190, 9, empresa.upper(), ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(190, 5, _pdf_clean(subtitulo_emisor), ln=True, align="C")
    if contacto_emisor:
        pdf.cell(190, 5, _pdf_clean(contacto_emisor), ln=True, align="C")
    if direccion_emisor:
        pdf.cell(190, 5, _pdf_clean(direccion_emisor), ln=True, align="C")
    pdf.ln(6)

    pdf.set_fill_color(240, 240, 240)
    cell(f" NOTA DE ENTREGA / PEDIDO #{pedido.get('id')} - {pedido.get('fecha')}", 190, 8, border=0, ln=1, fill=True, size=12, bold=True)

    # Datos cliente
    cliente = pedido.get('cliente_nombre') or 'N/A'
    rif = user_row['rif'] if user_row and user_row['rif'] else 'N/A'
    tel = user_row['telefono'] if user_row and user_row['telefono'] else 'N/A'
    ciudad = user_row['ciudad'] if user_row and user_row['ciudad'] else 'N/A'
    direccion = user_row['direccion'] if user_row and user_row['direccion'] else 'No registrada'

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 7, _pdf_clean(f" Cliente: {cliente}"), ln=0)
    pdf.cell(95, 7, _pdf_clean(f" RIF/CI: {rif}"), ln=1)
    pdf.cell(95, 7, _pdf_clean(f" Telefono: {tel}"), ln=0)
    pdf.cell(95, 7, _pdf_clean(f" Ciudad: {ciudad}"), ln=1)
    pdf.cell(95, 7, _pdf_clean(f" Metodo de pago: {pedido.get('metodo_pago') or 'N/A'}"), ln=0)
    pdf.cell(95, 7, _pdf_clean(f" Tipo: {pedido.get('tipo_pago') or 'contado'} | Estado: {pedido.get('status') or 'N/A'}"), ln=1)
    multi(f" Direccion: {direccion}", 190, 6, size=10)

    if credito:
        dias = user_row['dias_credito'] if user_row and 'dias_credito' in user_row.keys() else ''
        multi(f" Credito: #{credito.get('id')} | Dias de credito: {dias} | Vence: {credito.get('fecha_vencimiento')} | Saldo USD: {money_usd(credito.get('saldo_usd'))}", 190, 6, size=9, bold=True)
        multi(" Nota: credito expresado en USD. Si el cliente paga en bolivares, se calcula con la tasa BCV del dia del pago.", 190, 5, size=8)

    if pedido.get("notas"):
        multi(f" Nota del pedido: {pedido.get('notas')}", 190, 5, size=9)

    pdf.ln(3)

    # Tabla
    pdf.set_fill_color(220, 220, 220)
    cell(" Cant", 18, 8, border=1, ln=0, align="C", fill=True, size=9, bold=True)
    cell(" SKU", 38, 8, border=1, ln=0, align="L", fill=True, size=9, bold=True)
    cell(" Descripcion del Articulo", 82, 8, border=1, ln=0, align="L", fill=True, size=9, bold=True)
    cell(" Precio", 26, 8, border=1, ln=0, align="C", fill=True, size=9, bold=True)
    cell(" Subtotal", 26, 8, border=1, ln=1, align="C", fill=True, size=9, bold=True)

    total_items = 0
    pdf.set_font("Helvetica", "", 8)
    for sku, d in items.items():
        cant = int(d.get("c", 0) or 0)
        total_items += cant
        precio = float(d.get("p", 0) or 0)
        subtotal_linea = precio * cant
        desc = _pdf_clean(d.get("desc", ""))
        if len(desc) > 52:
            desc = desc[:49] + "..."
        sku_txt = _pdf_clean(sku)
        if len(sku_txt) > 22:
            sku_txt = sku_txt[:21]
        pdf.cell(18, 7, str(cant), border=1, align="C")
        pdf.cell(38, 7, sku_txt, border=1)
        pdf.cell(82, 7, desc, border=1)
        pdf.cell(26, 7, money_usd(precio), border=1, align="R")
        pdf.cell(26, 7, money_usd(subtotal_linea), border=1, align="R", ln=1)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(130, 7, f"Cantidad total de items: {total_items}", ln=0)
    pdf.cell(34, 7, "Subtotal USD:", border=1, align="R")
    pdf.cell(26, 7, money_usd(pedido.get('subtotal_usd')), border=1, align="R", ln=1)
    pdf.cell(130, 7, "", ln=0)
    pdf.cell(34, 7, "Descuento USD:", border=1, align="R")
    pdf.cell(26, 7, "-" + money_usd(pedido.get('descuento_usd')), border=1, align="R", ln=1)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(130, 8, "", ln=0)
    pdf.cell(34, 8, "TOTAL USD:", border=1, align="R", fill=True)
    pdf.cell(26, 8, money_usd(pedido.get('total_usd')), border=1, align="R", fill=True, ln=1)

    if str(pedido.get('tipo_pago')).lower() != "credito":
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(190, 7, _pdf_clean(f"Total referencia VES: {money_ves(pedido.get('total_ves'))} | Tasa BCV usada: {pedido.get('tasa_bcv')}"), ln=1, align="R")
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(190, 7, "Credito en USD. No se fija total VES en esta nota.", ln=1, align="R")

    pdf.ln(12)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 7, "Recibido por: ____________________________", ln=0)
    pdf.cell(95, 7, "Fecha: ____/____/________", ln=1)

    out = pdf.output(dest="S")
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    return bytes(out)


def generar_pdf_estado_cuenta_cliente(username: str):
    user_rows = q("SELECT * FROM usuarios WHERE username=?", (username,), fetch=True)
    if not user_rows:
        return b""
    cli = user_rows[0]
    creditos = pd.read_sql_query("SELECT * FROM creditos WHERE username=? ORDER BY id DESC", get_conn(), params=(username,))
    abonos = pd.read_sql_query("SELECT * FROM abonos WHERE username=? ORDER BY id DESC", get_conn(), params=(username,))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 8, _pdf_clean(get_config("nombre_empresa", "Sistema de pedidos pointer V21 Responsive")), ln=1, align="C")
    pdf.set_font("Arial", "", 9)
    pdf.cell(190, 5, _pdf_clean(f"Contacto: {get_config('telefono_empresa','')} | Instagram: {get_config('instagram_empresa','')}"), ln=1, align="C")
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(190, 8, _pdf_clean("ESTADO DE CUENTA"), ln=1)
    pdf.set_font("Arial", "", 9)
    pdf.cell(95, 6, _pdf_clean(f"Cliente: {cli['nombre'] or cli['username']}"), ln=0)
    pdf.cell(95, 6, _pdf_clean(f"RIF/CI: {cli['rif'] or 'N/A'}"), ln=1)
    pdf.cell(95, 6, _pdf_clean(f"Telefono: {cli['telefono'] or 'N/A'}"), ln=0)
    pdf.cell(95, 6, _pdf_clean(f"Fecha: {now()}"), ln=1)
    pdf.multi_cell(190, 6, _pdf_clean(f"Direccion: {cli['direccion'] or 'No registrada'}"))
    pdf.ln(3)

    saldo_total = float(creditos["saldo_usd"].sum()) if not creditos.empty else 0
    pdf.set_font("Arial", "B", 11)
    pdf.cell(190, 7, _pdf_clean(f"SALDO TOTAL PENDIENTE: {money_usd(saldo_total)}"), ln=1)
    pdf.ln(2)

    pdf.set_font("Arial", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    headers = [("Cred.",18),("Pedido",18),("Inicio",26),("Vence",26),("Monto",28),("Saldo",28),("Estado",46)]
    for h,w in headers:
        pdf.cell(w, 7, _pdf_clean(h), 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    if creditos.empty:
        pdf.cell(190, 7, "Sin creditos registrados", 1, 1)
    else:
        for _, cr in creditos.iterrows():
            vals = [f"#{int(cr['id'])}", f"#{int(cr['pedido_id'])}", cr['fecha_inicio'], cr['fecha_vencimiento'], money_usd(cr['monto_usd']), money_usd(cr['saldo_usd']), cr['status']]
            for val, (_,w) in zip(vals, headers):
                pdf.cell(w, 7, _pdf_clean(str(val)), 1, 0, "C")
            pdf.ln()

    pdf.ln(6)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(190, 7, "ABONOS REGISTRADOS", ln=1)
    pdf.set_font("Arial", "B", 8)
    headers2 = [("ID",15),("Credito",22),("Fecha",35),("Monto",28),("Metodo",35),("Estado",55)]
    for h,w in headers2:
        pdf.cell(w, 7, _pdf_clean(h), 1, 0, "C", True)
    pdf.ln()
    pdf.set_font("Arial", "", 8)
    if abonos.empty:
        pdf.cell(190, 7, "Sin abonos registrados", 1, 1)
    else:
        for _, ab in abonos.iterrows():
            vals = [f"#{int(ab['id'])}", f"#{int(ab['credito_id'])}", ab['fecha'], money_usd(ab['monto_usd']), ab['metodo'], ab['status']]
            for val, (_,w) in zip(vals, headers2):
                pdf.cell(w, 7, _pdf_clean(str(val)), 1, 0, "C")
            pdf.ln()
    out = pdf.output(dest="S")
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    return bytes(out)


def crear_excel_reportes():
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for nombre, sql in {
            "Pedidos": "SELECT * FROM pedidos ORDER BY id DESC",
            "Creditos": "SELECT * FROM creditos ORDER BY id DESC",
            "Abonos": "SELECT * FROM abonos ORDER BY id DESC",
            "Usuarios": "SELECT username,nombre,rol,telefono,rif,ciudad,activo,vendedor_username,comision_pct FROM usuarios ORDER BY rol,nombre",
            "Productos": "SELECT sku,descripcion,categoria,precio,activo,foto_path FROM productos ORDER BY descripcion",
        }.items():
            pd.read_sql_query(sql, get_conn()).to_excel(writer, sheet_name=nombre, index=False)
    return output.getvalue()


def calcular_comisiones_vendedores():
    vendedores = pd.read_sql_query("SELECT username,nombre,comision_pct FROM usuarios WHERE rol='vendedor' AND activo=1 ORDER BY nombre", get_conn())
    rows = []
    for _, v in vendedores.iterrows():
        clientes = [r["username"] for r in q("SELECT username FROM usuarios WHERE vendedor_username=?", (v["username"],), fetch=True)]
        if not clientes:
            rows.append({"Vendedor": v["nombre"], "Clientes": 0, "Base cobrada USD": 0.0, "% Comisión": float(v["comision_pct"] or 0), "Comisión USD": 0.0})
            continue
        clause, params = sql_in_clause(clientes)
        contado = q(f"SELECT COALESCE(SUM(total_usd),0) AS s FROM pedidos WHERE username IN {clause} AND LOWER(COALESCE(tipo_pago,''))='contado' AND status NOT IN ('Anulado')", params, fetch=True)[0]["s"]
        abonos = q(f"SELECT COALESCE(SUM(monto_usd),0) AS s FROM abonos WHERE username IN {clause} AND status='Validado'", params, fetch=True)[0]["s"]
        base = float(contado or 0) + float(abonos or 0)
        pct = float(v["comision_pct"] or 0)
        rows.append({"Vendedor": v["nombre"], "Clientes": len(clientes), "Base cobrada USD": round(base,2), "% Comisión": pct, "Comisión USD": round(base*pct/100,2)})
    return pd.DataFrame(rows)

def get_descuento_divisas_pct():
    """Porcentaje configurable de descuento para pagos en divisas/Zelle."""
    return max(0.0, min(100.0, parse_float(get_config("descuento_divisas_pct", "30"), 30.0)))

def get_descuento_bcv_100_pct():
    """Porcentaje configurable de descuento para pagos BCV desde $100."""
    return max(0.0, min(100.0, parse_float(get_config("descuento_bcv_100_pct", "10"), 10.0)))

def calcular_descuento(user_row, metodo_pago, subtotal):
    pct_divisas = get_descuento_divisas_pct()
    pct_bcv = get_descuento_bcv_100_pct()
    if metodo_pago == "Divisas / Zelle" and int(user_row["aplica_zelle_30"] or 0) == 1 and pct_divisas > 0:
        return subtotal * (pct_divisas / 100), f"{pct_divisas:g}% Divisas/Zelle"
    if metodo_pago == "Bolívares (BCV)" and subtotal >= 100 and int(user_row["aplica_bcv_10_100"] or 0) == 1 and pct_bcv > 0:
        return subtotal * (pct_bcv / 100), f"{pct_bcv:g}% BCV desde $100"
    return 0.0, "Sin descuento"

def viewport_width():
    """Devuelve el ancho del navegador cuando streamlit-js-eval está disponible."""
    if streamlit_js_eval is None:
        return None
    try:
        width = streamlit_js_eval(js_expressions="window.innerWidth", key="viewport_width")
        return int(width) if width else None
    except Exception:
        return None

def is_mobile_view():
    """Modo móvil automático con opción de forzarlo desde sesión para pruebas."""
    if st.session_state.get("force_mobile_view", False):
        return True
    w = viewport_width()
    return bool(w and w <= 768)

def totales_carrito_para_usuario(user_row, carrito):
    """Devuelve resumen del carrito con las dos reglas comerciales posibles."""
    tasa = get_tasa_bcv()
    cantidad = sum(int(d.get("c", 0) or 0) for d in carrito.values())
    subtotal = sum(float(d.get("p", 0) or 0) * int(d.get("c", 0) or 0) for d in carrito.values())
    desc_zelle, regla_zelle = calcular_descuento(user_row, "Divisas / Zelle", subtotal)
    desc_bcv, regla_bcv = calcular_descuento(user_row, "Bolívares (BCV)", subtotal)
    total_zelle = max(0, subtotal - desc_zelle)
    total_bcv_usd = max(0, subtotal - desc_bcv)
    return {
        "cantidad": cantidad,
        "subtotal": subtotal,
        "tasa": tasa,
        "desc_zelle": desc_zelle,
        "regla_zelle": regla_zelle,
        "total_zelle": total_zelle,
        "desc_bcv": desc_bcv,
        "regla_bcv": regla_bcv,
        "total_bcv_usd": total_bcv_usd,
        "total_bcv_ves": total_bcv_usd * tasa,
    }

def mostrar_totalizador_carrito(user_row, carrito, titulo="Resumen del carrito"):
    """Cuadro compacto para que el cliente vea cuánto lleva acumulado mientras compra."""
    if not carrito:
        return
    t = totales_carrito_para_usuario(user_row, carrito)
    st.markdown(f"""
    <div style="background:#ffffff;border:1px solid #d1fae5;border-radius:12px;padding:12px 14px;margin:8px 0 14px 0;box-shadow:0 2px 8px rgba(0,0,0,.05);">
        <div style="font-weight:700;font-size:1rem;margin-bottom:8px;color:#065f46;">🧾 {titulo}</div>
        <div class="mobile-total-grid">
            <div><div style="color:#6b7280;font-size:.78rem;">Items</div><div style="font-weight:800;font-size:1.1rem;color:#16a34a;">{t['cantidad']}</div></div>
            <div><div style="color:#6b7280;font-size:.78rem;">Subtotal</div><div style="font-weight:800;font-size:1.1rem;color:#16a34a;">{money_usd(t['subtotal'])}</div></div>
            <div><div style="color:#6b7280;font-size:.78rem;">Divisas/Zelle</div><div style="font-weight:800;font-size:1.1rem;color:#16a34a;">{money_usd(t['total_zelle'])}</div><div style="color:#059669;font-size:.74rem;font-weight:700;">Desc: {money_usd(t['desc_zelle'])}</div></div>
            <div><div style="color:#6b7280;font-size:.78rem;">BCV</div><div style="font-weight:800;font-size:1.1rem;color:#16a34a;">{money_usd(t['total_bcv_usd'])}</div><div style="color:#059669;font-size:.74rem;font-weight:700;">{money_ves(t['total_bcv_ves'])}</div></div>
        </div>
        <div style="margin-top:8px;color:#6b7280;font-size:.78rem;">Reglas: Divisas/Zelle: {t['regla_zelle']} · BCV: {t['regla_bcv']} · Tasa BCV: {t['tasa']:,.2f}</div>
    </div>
    """, unsafe_allow_html=True)

def sincronizar_fotos_por_sku():
    exts = [".jpg", ".jpeg", ".png", ".webp"]
    productos = {r["sku"] for r in q("SELECT sku FROM productos", fetch=True)}
    ok, ignoradas = 0, 0
    for folder in IMPORT_DIRS:
        folder.mkdir(exist_ok=True)
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in exts:
                sku = f.stem.strip()
                if sku in productos:
                    safe = re.sub(r'[^A-Za-z0-9_\-.]', '_', sku)
                    destino = IMG_DIR / f"{safe}{f.suffix.lower()}"
                    shutil.copy2(f, destino)
                    q("UPDATE productos SET foto_path=?, actualizado_en=? WHERE sku=?", (str(destino), now(), sku))
                    ok += 1
                else:
                    ignoradas += 1
    return ok, ignoradas

def save_uploaded_file(uploaded, folder: Path, prefix="file"):
    if uploaded is None: return None
    ext = Path(uploaded.name).suffix.lower()
    safe_name = re.sub(r'[^A-Za-z0-9_\-.]', '_', Path(uploaded.name).stem)
    path = folder / f"{prefix}_{now_file()}_{safe_name}{ext}"
    with open(path, "wb") as out:
        out.write(uploaded.getbuffer())
    return str(path)

# -----------------------------
# AUTENTICACIÓN
# -----------------------------
def login_screen():
    st.title("🔐 Acceso Sistema de pedidos pointer V21 Responsive")
    st.caption("Sistema local de pedidos, créditos y abonos")
    with st.form("login"):
        u = st.text_input("Usuario / correo")
        p = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Entrar", type="primary", use_container_width=True)
    if submit:
        row = get_user(u.strip())
        if row and int(row["activo"] or 0) == 1 and verify_password(p, row["password_hash"]):
            st.session_state.auth = True
            st.session_state.user = {"username": row["username"], "nombre": row["nombre"], "rol": row["rol"]}
            st.rerun()
        else:
            st.error("Credenciales incorrectas o usuario inactivo.")
    

def logout():
    st.session_state.auth = False
    st.session_state.user = None
    st.rerun()

# -----------------------------
# MÓDULOS
# -----------------------------
def dashboard_admin():
    st.title("📊 Dashboard")
    pedidos = pd.read_sql_query("SELECT * FROM pedidos", get_conn())
    creditos = pd.read_sql_query("SELECT * FROM creditos", get_conn())
    productos = pd.read_sql_query("SELECT * FROM productos", get_conn())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pedidos", len(pedidos))
    c2.metric("Ventas USD", money_usd(pedidos["total_usd"].sum() if not pedidos.empty else 0))
    c3.metric("Créditos pendientes", len(creditos[creditos["status"].isin(["Pendiente", "Vencido", "Parcial"])]) if not creditos.empty else 0)
    c4.metric("Saldo por cobrar", money_usd(creditos["saldo_usd"].sum() if not creditos.empty else 0))

    st.subheader("Alertas")
    col_a, col_b = st.columns(2)
    with col_a:
        activos = len(productos[productos["activo"] == 1]) if not productos.empty and "activo" in productos.columns else 0
        st.markdown("**Catálogo contrapedido**")
        st.success(f"Productos activos publicados: {activos}")
        st.caption("El sistema no descuenta stock porque la mercancía se maneja contra pedido.")
    with col_b:
        if not creditos.empty:
            hoy = datetime.now().date()
            creditos["venc_dt"] = pd.to_datetime(creditos["fecha_vencimiento"], format="%d/%m/%Y", errors="coerce").dt.date
            vencidos = creditos[(creditos["saldo_usd"] > 0) & (creditos["venc_dt"] < hoy)]
            st.markdown("**Créditos vencidos**")
            if vencidos.empty: st.success("Sin créditos vencidos.")
            else: st.dataframe(vencidos[["id", "cliente_nombre", "fecha_vencimiento", "saldo_usd", "status"]], use_container_width=True)
        else:
            st.info("No hay créditos registrados.")

    st.subheader("Últimos pedidos")
    ult = pd.read_sql_query("SELECT id, fecha, cliente_nombre, metodo_pago, tipo_pago, total_usd, status FROM pedidos ORDER BY id DESC LIMIT 10", get_conn())
    st.dataframe(ult, use_container_width=True, hide_index=True)

def productos_admin():
    st.title("📦 Productos")
    tab1, tab2 = st.tabs(["Listado", "Crear / Editar"])
    with tab1:
        bus = st.text_input("Buscar por SKU o descripción")
        sql = "SELECT sku, descripcion, categoria, precio, activo, foto_path FROM productos WHERE 1=1"
        params = []
        if bus:
            sql += " AND (sku LIKE ? OR descripcion LIKE ?)"
            params.extend([f"%{bus}%", f"%{bus}%"])
        df = pd.read_sql_query(sql + " ORDER BY descripcion", get_conn(), params=params)
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab2:
        st.subheader("Crear o actualizar producto")
        sku_edit = st.text_input("SKU")
        prod = get_producto(sku_edit.strip()) if sku_edit.strip() else None
        with st.form("form_producto"):
            desc = st.text_input("Descripción", value=prod["descripcion"] if prod else "")
            cat = st.text_input("Categoría", value=prod["categoria"] if prod else "")
            precio = st.number_input("Precio único USD", min_value=0.0, value=float(prod["precio"] if prod else 0), step=0.01)
            activo = st.checkbox("Producto activo", value=bool(prod["activo"] if prod else 1))
            foto = st.file_uploader("Foto del producto", type=["jpg", "jpeg", "png", "webp"])
            guardar = st.form_submit_button("💾 Guardar producto", type="primary")
        if guardar:
            sku = sku_edit.strip()
            if not sku or not desc:
                st.error("SKU y descripción son obligatorios.")
            else:
                foto_path = prod["foto_path"] if prod else None
                if foto:
                    foto_path = save_uploaded_file(foto, IMG_DIR, prefix=sku)
                if not cat: cat = auto_categoria(desc)
                q("""INSERT INTO productos (sku,descripcion,precio,categoria,foto_path,activo,creado_en,actualizado_en)
                     VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(sku) DO UPDATE SET descripcion=excluded.descripcion, precio=excluded.precio,
                     categoria=excluded.categoria, foto_path=excluded.foto_path, activo=excluded.activo, actualizado_en=excluded.actualizado_en""",
                  (sku, desc, precio, cat, foto_path, 1 if activo else 0, now(), now()))
                st.success("Producto guardado.")
                st.rerun()

def importar_admin():
    st.title("📥 Importar datos")
    tab_excel, tab_fotos = st.tabs(["Excel / CSV", "Fotos por SKU"])
    with tab_excel:
        st.info("Columnas recomendadas: SKU, Descripcion, Precio, Categoria. El sistema trabaja contra pedido, sin control de stock.")
        f = st.file_uploader("Subir Excel o CSV", type=["xlsx", "csv"])
        if f:
            try:
                df = pd.read_csv(f) if f.name.lower().endswith(".csv") else pd.read_excel(f)
                st.dataframe(df.head(20), use_container_width=True)
                cols = list(df.columns)
                c1, c2, c3 = st.columns(3)
                col_sku = c1.selectbox("Columna SKU", cols)
                col_desc = c2.selectbox("Columna descripción", cols, index=1 if len(cols)>1 else 0)
                col_precio = c3.selectbox("Columna precio", cols, index=2 if len(cols)>2 else 0)
                col_cat = st.selectbox("Columna categoría opcional", ["Auto"] + cols)
                if st.button("Importar productos", type="primary"):
                    n = 0
                    for _, r in df.iterrows():
                        sku = str(r[col_sku]).strip()
                        desc = str(r[col_desc]).strip()
                        if not sku or sku.lower() == "nan": continue
                        precio = parse_float(r[col_precio])
                        cat = auto_categoria(desc) if col_cat == "Auto" else str(r[col_cat]).strip()
                        q("""INSERT INTO productos (sku,descripcion,precio,categoria,activo,creado_en,actualizado_en)
                             VALUES (?,?,?,?,?,?,?)
                             ON CONFLICT(sku) DO UPDATE SET descripcion=excluded.descripcion, precio=excluded.precio,
                             categoria=excluded.categoria, actualizado_en=excluded.actualizado_en""",
                          (sku, desc, precio, cat, 1, now(), now()))
                        n += 1
                    st.success(f"Productos importados/actualizados: {n}")
                    st.rerun()
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")
    with tab_fotos:
        st.write("Coloca imágenes en `importar_fotos` o `importar_fotos2` con el mismo nombre del SKU. Ejemplo: `ABC123.jpg`.")
        fotos = st.file_uploader("O sube fotos aquí", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
        if fotos:
            for fo in fotos:
                path = IMPORT_DIRS[0] / fo.name
                with open(path, "wb") as out: out.write(fo.getbuffer())
            st.success(f"Fotos copiadas a importar_fotos: {len(fotos)}")
        if st.button("🖼️ Sincronizar fotos con productos", type="primary"):
            ok, ign = sincronizar_fotos_por_sku()
            st.success(f"Fotos vinculadas: {ok}. Ignoradas por SKU inexistente: {ign}.")

def pos_tienda():
    st.title("🛍️ Catálogo / POS")
    user = get_user(st.session_state.user["username"])
    carrito = cargar_carrito(user["username"])
    tasa = get_tasa_bcv()

    df_tienda = pd.read_sql_query("SELECT * FROM productos WHERE activo=1 ORDER BY descripcion", get_conn())
    if df_tienda.empty:
        st.info("No hay productos disponibles.")
        return

    # Filtros y búsqueda al estilo de la versión local V2.
    c1, c2, c3 = st.columns([3, 4, 1])
    categorias = ["Todos"] + sorted([c for c in df_tienda["categoria"].dropna().unique().tolist() if c])
    f_cat = c1.selectbox("Filtrar por Categoría", categorias)
    f_bus = c2.text_input("Buscar producto...")
    c3.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    if c3.button("🔍 Buscar", use_container_width=True):
        st.session_state.pos_pag_actual = 1
        st.rerun()

    # Vista fija: USD + VES, sin selector para simplificar la compra.
    st.caption(f"Tasa BCV: {tasa:,.2f} Bs/USD")
    mostrar_totalizador_carrito(user, carrito, "Total acumulado en carrito")

    df_f = df_tienda.copy()
    if f_cat != "Todos":
        df_f = df_f[df_f["categoria"] == f_cat]
    if f_bus:
        mask_desc = df_f["descripcion"].astype(str).str.contains(f_bus, case=False, na=False)
        mask_sku = df_f["sku"].astype(str).str.contains(f_bus, case=False, na=False)
        df_f = df_f[mask_desc | mask_sku]

    mobile = is_mobile_view()
    items_pag = 6 if mobile else 15
    total_p = max(1, (len(df_f) // items_pag) + (1 if len(df_f) % items_pag > 0 else 0))
    if "pos_pag_actual" not in st.session_state:
        st.session_state.pos_pag_actual = 1
    if st.session_state.pos_pag_actual > total_p:
        st.session_state.pos_pag_actual = total_p

    col_espacio, col_sel = st.columns([6, 2])
    col_espacio.caption(f"{len(df_f)} productos encontrados")
    p_ir = col_sel.number_input("Ir a la página:", min_value=1, max_value=total_p, value=st.session_state.pos_pag_actual)
    if p_ir != st.session_state.pos_pag_actual:
        st.session_state.pos_pag_actual = int(p_ir)
        st.rerun()

    def barra_navegacion(ubicacion):
        col_nav = st.columns([1, 1, 2, 1, 1])
        if col_nav[0].button("⏪", key=f"pos_first_{ubicacion}", use_container_width=True, disabled=st.session_state.pos_pag_actual <= 1):
            st.session_state.pos_pag_actual = 1
            st.rerun()
        if col_nav[1].button("◀️", key=f"pos_prev_{ubicacion}", use_container_width=True, disabled=st.session_state.pos_pag_actual <= 1):
            st.session_state.pos_pag_actual -= 1
            st.rerun()
        col_nav[2].markdown(f"<h3 style='text-align: center; margin: 0;'>Pág. {st.session_state.pos_pag_actual} de {total_p}</h3>", unsafe_allow_html=True)
        if col_nav[3].button("▶️", key=f"pos_next_{ubicacion}", use_container_width=True, disabled=st.session_state.pos_pag_actual >= total_p):
            st.session_state.pos_pag_actual += 1
            st.rerun()
        if col_nav[4].button("⏩", key=f"pos_last_{ubicacion}", use_container_width=True, disabled=st.session_state.pos_pag_actual >= total_p):
            st.session_state.pos_pag_actual = total_p
            st.rerun()

    barra_navegacion("top")
    st.markdown("---")

    p_sel = st.session_state.pos_pag_actual
    for _, row in df_f.iloc[(p_sel-1)*items_pag : p_sel*items_pag].iterrows():
        sku = str(row["sku"])
        precio_usd = float(row["precio"] or 0)
        precio_ves = precio_usd * tasa
        img = row.get("foto_path")
        promo_html = ""
        if int(user["aplica_zelle_30"] or 0) == 1 and get_descuento_divisas_pct() > 0:
            promo = precio_usd * (1 - get_descuento_divisas_pct() / 100)
            promo_html = f'<div style="display:inline-block;margin-top:6px;padding:4px 10px;border-radius:999px;background:#dcfce7;color:#166534;font-size:.78rem;font-weight:800;border:1px solid #86efac;">Promo divisas: {money_usd(promo)}</div>'

        if mobile:
            st.markdown('<div class="mobile-product-card">', unsafe_allow_html=True)
            if img and os.path.exists(str(img)):
                st.image(str(img), use_container_width=True)
            else:
                st.markdown("<div style='height:150px;width:100%;border-radius:14px;background:#f3f4f6;display:flex;align-items:center;justify-content:center;font-size:42px'>📦</div>", unsafe_allow_html=True)
            st.markdown(f'<div class="mobile-product-title">{row["descripcion"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div style="color:#888;font-size:.82rem;margin-bottom:4px;">{sku} | {row["categoria"]} | Contra pedido</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="mobile-price">{money_usd(precio_usd)}</div><div class="mobile-ves">{money_ves(precio_ves)}</div>', unsafe_allow_html=True)
            if promo_html:
                st.markdown(promo_html, unsafe_allow_html=True)
            if sku in carrito:
                st.markdown(f'<div style="color:#28a745;font-weight:800;font-size:.88rem;margin-top:7px;">✅ En carrito: {carrito[sku]["c"]} und.</div>', unsafe_allow_html=True)
            m1, m2, m3 = st.columns([1.2, 1, 1])
            cant_actual = int(carrito.get(sku, {}).get("c", 1))
            nueva_q = m1.number_input("Cant", 1, 99999, cant_actual, label_visibility="collapsed", key=f"pos_q_{sku}")
            if m2.button("💾 Agregar", key=f"pos_s_{sku}", use_container_width=True):
                carrito[sku] = {"desc": row["descripcion"], "p": precio_usd, "c": int(nueva_q), "f": row.get("foto_path")}
                guardar_carrito(user["username"], carrito)
                st.rerun()
            if m3.button("🗑️ Quitar", key=f"pos_d_{sku}", use_container_width=True):
                if sku in carrito:
                    del carrito[sku]
                    guardar_carrito(user["username"], carrito)
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            r1, r2, r3, r4 = st.columns([1.25, 3.7, 1.35, 2.45])

            with r1:
                if img and os.path.exists(str(img)):
                    st.image(str(img), width=105)
                else:
                    st.markdown("<div style='height:90px;width:90px;border-radius:8px;background:#f3f4f6;display:flex;align-items:center;justify-content:center;font-size:34px'>📦</div>", unsafe_allow_html=True)

            with r2:
                st.markdown(f'<p style="font-size:1.08rem;font-weight:700;color:#1f77b4;margin-bottom:2px;line-height:1.2">{row["descripcion"]}</p>', unsafe_allow_html=True)
                st.markdown(f'<span style="color:#888;font-size:0.78rem;display:block;">{sku} | {row["categoria"]} | Contra pedido</span>', unsafe_allow_html=True)
                if sku in carrito:
                    st.markdown(f'<span style="color:#28a745;font-weight:bold;font-size:0.8rem;">✅ En carrito: {carrito[sku]["c"]} und.</span>', unsafe_allow_html=True)
                if promo_html:
                    st.markdown(promo_html, unsafe_allow_html=True)

            with r3:
                st.markdown(f"### {money_usd(precio_usd)}")
                st.caption(money_ves(precio_ves))

            with r4:
                c_input, c_add, c_del = st.columns([1.2, 1, 0.8])
                cant_actual = int(carrito.get(sku, {}).get("c", 1))
                nueva_q = c_input.number_input("Cant", 1, 99999, cant_actual, label_visibility="collapsed", key=f"pos_q_{sku}")
                if c_add.button("💾", key=f"pos_s_{sku}", use_container_width=True):
                    carrito[sku] = {"desc": row["descripcion"], "p": precio_usd, "c": int(nueva_q), "f": row.get("foto_path")}
                    guardar_carrito(user["username"], carrito)
                    st.rerun()
                if c_del.button("🗑️", key=f"pos_d_{sku}", use_container_width=True):
                    if sku in carrito:
                        del carrito[sku]
                        guardar_carrito(user["username"], carrito)
                        st.rerun()
            st.markdown("<hr style='margin:8px 0; border-color:#eee'>", unsafe_allow_html=True)

    barra_navegacion("bottom")

def carrito_view():
    st.title("🛒 Carrito")
    u = get_user(st.session_state.user["username"])
    carrito = cargar_carrito(u["username"])
    if not carrito:
        st.info("Tu carrito está vacío.")
        return

    mobile = is_mobile_view()
    mostrar_totalizador_carrito(u, carrito, "Total actual del pedido")

    if mobile:
        for sku, d in list(carrito.items()):
            st.markdown('<div class="mobile-product-card">', unsafe_allow_html=True)
            foto_path = d.get("f")
            if foto_path and os.path.exists(str(foto_path)):
                st.image(str(foto_path), use_container_width=True)
            else:
                st.markdown("<div style='height:140px;width:100%;border-radius:14px;background:#f3f4f6;display:flex;align-items:center;justify-content:center;font-size:40px'>📦</div>", unsafe_allow_html=True)
            tasa_item = get_tasa_bcv()
            st.markdown(f"**{sku}**")
            st.markdown(f"<small>{d['desc']}</small>", unsafe_allow_html=True)
            st.markdown(f"### {money_usd(float(d['p']) * int(d['c']))}")
            st.caption(f"Unitario: {money_usd(d['p'])} · {money_ves(float(d['p']) * tasa_item)}")
            cqm, cdm = st.columns([1.2, 1])
            newq = cqm.number_input("Cantidad", min_value=1, value=int(d["c"]), key=f"cartq_mobile_{sku}", label_visibility="collapsed")
            if newq != d["c"]:
                carrito[sku]["c"] = int(newq)
                guardar_carrito(u["username"], carrito)
                st.rerun()
            if cdm.button("🗑️ Quitar", key=f"cartdel_mobile_{sku}", use_container_width=True):
                carrito.pop(sku, None)
                guardar_carrito(u["username"], carrito)
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        h0, h1, h2, h3, h4 = st.columns([1.1, 3.5, 1.5, 2.4, 1.2])
        h1.caption("Producto")
        h2.caption("Precio")
        h3.caption("Cantidad")
        h4.caption("Total")
        st.markdown("---")
        for sku, d in list(carrito.items()):
            cr0, cr1, cr2, cr3, cr4 = st.columns([1.1, 3.5, 1.5, 2.4, 1.2])
            with cr0:
                foto_path = d.get("f")
                if foto_path and os.path.exists(str(foto_path)):
                    st.image(str(foto_path), width=85)
                else:
                    st.markdown("<div style='height:75px;width:75px;border-radius:8px;background:#f3f4f6;display:flex;align-items:center;justify-content:center;font-size:28px'>📦</div>", unsafe_allow_html=True)
            with cr1:
                st.markdown(f"**{sku}**")
                st.markdown(f"<small>{d['desc']}</small>", unsafe_allow_html=True)
            tasa_item = get_tasa_bcv()
            cr2.write(money_usd(d["p"]))
            cr2.caption(money_ves(float(d["p"]) * tasa_item))
            ci_q, ci_del = cr3.columns([1.2, 1])
            newq = ci_q.number_input("Cantidad", min_value=1, value=int(d["c"]), key=f"cartq_{sku}", label_visibility="collapsed")
            if newq != d["c"]:
                carrito[sku]["c"] = int(newq)
                guardar_carrito(u["username"], carrito)
                st.rerun()
            if ci_del.button("🗑️", key=f"cartdel_{sku}"):
                carrito.pop(sku, None)
                guardar_carrito(u["username"], carrito)
                st.rerun()
            cr4.write(f"**{money_usd(float(d['p']) * int(d['c']))}**")
            cr4.caption(money_ves(float(d["p"]) * int(d["c"]) * tasa_item))
            st.markdown("<hr style='margin:5px 0; border-color:#f0f0f0'>", unsafe_allow_html=True)
    st.markdown("---")
    subtotal = sum(float(d["p"]) * int(d["c"]) for d in carrito.values())
    tasa = get_tasa_bcv()
    metodo = st.radio("Método de pago", ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
    descuento, regla = calcular_descuento(u, metodo, subtotal)
    total = subtotal - descuento
    total_ves = total * tasa

    c1, c2 = st.columns([1,1])
    with c1:
        st.markdown("### Resumen")
        st.write(f"Subtotal: **{money_usd(subtotal)}**")
        st.write(f"Descuento aplicado: **-{money_usd(descuento)}**")
        st.caption(f"Regla: {regla}")
        st.write(f"Tasa BCV: **{tasa:,.2f}**")
    with c2:
        st.markdown("### Total")
        if metodo == "Bolívares (BCV)":
            st.header(money_ves(total_ves))
            st.caption(f"Equivalente: {money_usd(total)}")
        else:
            st.header(money_usd(total))
            st.caption(f"Referencia BCV: {money_ves(total_ves)}")

    credito_permitido = int(u["credito_habilitado"] or 0) == 1
    tipo_pago = st.radio("Tipo de operación", ["Contado", "Crédito"], horizontal=True, disabled=not credito_permitido)
    if tipo_pago == "Crédito":
        st.info("Este crédito se registra en USD. No se fija total en VES porque si el cliente paga en bolívares se calculará con la tasa BCV del día del pago.")
    if not credito_permitido:
        st.caption("Este usuario no tiene crédito habilitado.")
    else:
        st.info(f"Crédito habilitado: {u['dias_credito']} días | Límite: {money_usd(u['limite_credito_usd'])}")
    notas = st.text_area("Notas del pedido", placeholder="Ejemplo: retirar en tienda, enviar por encomienda...")

    if st.button("🏁 Confirmar pedido", type="primary", use_container_width=True):
        if tipo_pago == "Crédito":
            saldo_actual = q("SELECT COALESCE(SUM(saldo_usd),0) AS s FROM creditos WHERE username=? AND status IN ('Pendiente','Parcial','Vencido')", (u["username"],), fetch=True)[0]["s"]
            if float(saldo_actual) + total > float(u["limite_credito_usd"] or 0):
                st.error(f"El crédito supera el límite. Saldo actual: {money_usd(saldo_actual)}")
                return
        # Crear pedido
        pedido_total_ves = 0 if tipo_pago == "Crédito" else total_ves
        pedido_tasa_bcv = 0 if tipo_pago == "Crédito" else tasa
        cur = q("""INSERT INTO pedidos (username,cliente_nombre,fecha,items,metodo_pago,tipo_pago,subtotal_usd,descuento_usd,total_usd,tasa_bcv,total_ves,status,notas)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (u["username"], u["nombre"], now(), json.dumps(carrito, ensure_ascii=False), metodo, tipo_pago.lower(), subtotal, descuento, total, pedido_tasa_bcv, pedido_total_ves, "Pendiente", notas))
        pedido_id = cur.lastrowid
        if tipo_pago == "Crédito":
            venc = datetime.now() + timedelta(days=int(u["dias_credito"] or 10))
            cur2 = q("""INSERT INTO creditos (pedido_id,username,cliente_nombre,fecha_inicio,fecha_vencimiento,monto_usd,monto_ves,tasa_bcv,saldo_usd,status,notas)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   (pedido_id, u["username"], u["nombre"], datetime.now().strftime("%d/%m/%Y"), venc.strftime("%d/%m/%Y"), total, 0, 0, total, "Pendiente", notas))
            credito_id = cur2.lastrowid
            q("UPDATE pedidos SET credito_id=?, status=? WHERE id=?", (credito_id, "Crédito pendiente", pedido_id))
        limpiar_carrito(u["username"])
        log_event("Crear pedido", "pedidos", pedido_id, f"Cliente={u['username']}; total={total}; tipo={tipo_pago}")
        st.success(f"Pedido #{pedido_id} registrado correctamente.")
        st.balloons()
        st.rerun()

def mis_pedidos():
    st.title("📜 Mis pedidos")
    u = st.session_state.user
    visibles = usernames_visibles_para_usuario(u)
    clause, params = sql_in_clause(visibles)
    if u["rol"] == "admin":
        df = pd.read_sql_query("SELECT * FROM pedidos ORDER BY id DESC", get_conn())
    else:
        df = pd.read_sql_query(f"SELECT * FROM pedidos WHERE username IN {clause} ORDER BY id DESC", get_conn(), params=params)
        if u["rol"] == "vendedor":
            st.info("Estás viendo tus pedidos y los pedidos de tus clientes asignados.")
    if df.empty:
        st.info("No hay pedidos.")
        return

    estados_pedido = ["Pendiente", "Confirmado", "Preparando", "Listo para entregar", "Entregado", "Pago por validar", "Finalizado", "Crédito pendiente", "Anulado"]

    for _, p in df.iterrows():
        pedido_id = int(p["id"])
        credito_id_raw = p.get("credito_id", None)
        credito_id = None
        try:
            if credito_id_raw is not None and not pd.isna(credito_id_raw):
                credito_id = int(credito_id_raw)
        except Exception:
            credito_id = None

        with st.expander(f"Pedido #{pedido_id} | {p['cliente_nombre']} | {p['fecha']} | {money_usd(p['total_usd'])} | {p['status']}"):
            ctop1, ctop2, ctop3 = st.columns([2, 2, 2])
            ctop1.write(f"Cliente: **{p['cliente_nombre']}**")
            ctop2.write(f"Pago: **{p['metodo_pago']}**")
            ctop3.write(f"Tipo: **{p['tipo_pago']}**")

            credito_row = None
            if str(p['tipo_pago']).lower() == "credito":
                crs = q("SELECT * FROM creditos WHERE id=?", (credito_id,), fetch=True) if credito_id else []
                if crs:
                    credito_row = crs[0]
                    st.info(
                        f"Crédito en USD. Vence: {credito_row['fecha_vencimiento']} | "
                        f"Saldo: {money_usd(credito_row['saldo_usd'])} | Estado crédito: {credito_row['status']}. "
                        "Si paga en bolívares, se cobra con tasa BCV del día del pago."
                    )
                else:
                    st.info("Pedido a crédito en USD. Si se paga en bolívares, se cobra con tasa BCV del día del pago.")
            else:
                st.write(f"Total VES: **{money_ves(p['total_ves'])}** | Tasa: **{p['tasa_bcv']}**")

            items = json.loads(p["items"] or "{}")
            rows = [{"SKU": sku, "Descripción": d["desc"], "Cantidad": d["c"], "Precio USD": money_usd(d["p"]), "Total USD": money_usd(d["p"]*d["c"])} for sku,d in items.items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            b1, b2 = st.columns([1, 1])
            pdf_bytes = generar_pdf_nota_entrega(p)
            b1.download_button(
                "📄 Descargar nota de entrega PDF",
                data=pdf_bytes,
                file_name=f"nota_entrega_pedido_{pedido_id}.pdf",
                mime="application/pdf",
                key=f"pdf_pedido_{pedido_id}",
                use_container_width=True,
            )

            if u["rol"] in ["admin", "vendedor"]:
                actual = p["status"] if p["status"] in estados_pedido else "Pendiente"
                nuevo_status = b2.selectbox(
                    "Cambiar estado del pedido",
                    estados_pedido,
                    index=estados_pedido.index(actual),
                    key=f"pedido_status_{pedido_id}",
                )

                es_credito = str(p['tipo_pago']).lower() == "credito" and credito_row is not None
                saldo_credito = float(credito_row["saldo_usd"] or 0) if credito_row else 0.0

                if nuevo_status != p["status"]:
                    # Regla especial: Finalizar un pedido a crédito debe cerrar/conciliar el crédito.
                    if nuevo_status == "Finalizado" and es_credito and str(credito_row.get('status', '')).lower() != "pagado":
                        st.warning("Este pedido tiene crédito asociado. Para marcarlo como Finalizado, el crédito también debe cerrarse como Pagado.")

                        if u["rol"] == "admin":
                            with st.form(f"form_cierre_credito_admin_{pedido_id}"):
                                st.markdown("### Cierre administrativo del crédito")
                                st.write(f"Saldo pendiente a cerrar: **{money_usd(saldo_credito)}**")
                                metodo_cierre = st.selectbox("Método recibido", ["Pago móvil", "Transferencia", "Zelle", "Divisas", "Binance", "Otro"], key=f"met_cierre_{pedido_id}")
                                referencia_cierre = st.text_input("Referencia / soporte del pago", key=f"ref_cierre_{pedido_id}")
                                notas_cierre = st.text_area("Nota interna del cierre", value="Cierre de crédito realizado por administrador al finalizar pedido.", key=f"nota_cierre_{pedido_id}")
                                confirmar_cierre = st.checkbox("Confirmo que el pago fue recibido y deseo cerrar el crédito", key=f"chk_cierre_{pedido_id}")
                                cerrar = st.form_submit_button("✅ Cerrar crédito y finalizar pedido", type="primary")
                            if cerrar:
                                if not confirmar_cierre:
                                    st.error("Debes confirmar que el pago fue recibido.")
                                else:
                                    ok, msg = cerrar_credito_y_finalizar_pedido(pedido_id, u["username"], metodo_cierre, referencia_cierre, notas_cierre)
                                    st.success(msg)
                                    st.rerun()

                        elif u["rol"] == "vendedor":
                            st.info("Como vendedor no puedes cerrar directamente un crédito. Debes conciliar el pago para que administración lo valide.")
                            with st.form(f"form_conciliar_vendedor_{pedido_id}"):
                                st.markdown("### Conciliar pago recibido")
                                st.write(f"Saldo a conciliar: **{money_usd(saldo_credito)}**")
                                metodo = st.selectbox("Método reportado", ["Pago móvil", "Transferencia", "Zelle", "Divisas", "Binance", "Otro"], key=f"met_conc_{pedido_id}")
                                referencia = st.text_input("Referencia obligatoria", key=f"ref_conc_{pedido_id}")
                                comprobante = st.file_uploader("Comprobante del pago", type=["jpg","jpeg","png","webp","pdf"], key=f"comp_conc_{pedido_id}")
                                notas = st.text_area("Detalles del pago recibido", key=f"nota_conc_{pedido_id}")
                                enviar_conciliacion = st.form_submit_button("📩 Enviar a administración para validar", type="primary")
                            if enviar_conciliacion:
                                if not referencia.strip():
                                    st.error("La referencia es obligatoria para conciliar el pago.")
                                else:
                                    tasa = get_tasa_bcv()
                                    path = save_uploaded_file(comprobante, COMPROBANTES_DIR, prefix=f"conciliacion_{credito_id}_{u['username']}") if comprobante else None
                                    q("""INSERT INTO abonos (credito_id,username,fecha,monto_usd,monto_ves,metodo,referencia,comprobante_path,status,notas)
                                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                      (credito_id, p["username"], now(), saldo_credito, saldo_credito*tasa, metodo, referencia.strip(), path, "Pendiente de validar", f"Conciliado por vendedor {u['username']}. {notas}"))
                                    q("UPDATE pedidos SET status='Pago por validar' WHERE id=?", (pedido_id,))
                                    log_event("Conciliar pago vendedor", "pedidos", pedido_id, f"Credito={credito_id}; monto={saldo_credito}; metodo={metodo}; ref={referencia}")
                                    st.success("Pago conciliado. El pedido queda en 'Pago por validar' hasta que administración valide el abono.")
                                    st.rerun()
                    else:
                        # Cambios normales de estado, o crédito ya pagado.
                        q("UPDATE pedidos SET status=? WHERE id=?", (nuevo_status, pedido_id))
                        log_event("Cambiar estado pedido", "pedidos", pedido_id, f"{p['status']} -> {nuevo_status}")
                        st.success("Estado del pedido actualizado.")
                        st.rerun()

            if u["rol"] == "admin":
                st.markdown("---")
                confirmar_eliminar = st.checkbox("Confirmar eliminación de este pedido", key=f"confirm_del_pedido_{pedido_id}")
                if st.button("🗑️ Eliminar pedido", key=f"del_pedido_{pedido_id}", disabled=not confirmar_eliminar):
                    if credito_id:
                        st.error("Este pedido tiene un crédito asociado. Anula o elimina primero el crédito desde Validar créditos para no perder trazabilidad.")
                    else:
                        q("DELETE FROM pedidos WHERE id=?", (pedido_id,))
                        log_event("Eliminar pedido", "pedidos", pedido_id, f"Cliente={p['cliente_nombre']}; total={p['total_usd']}")
                        st.success("Pedido eliminado.")
                        st.rerun()

def creditos_usuario():
    titulo = "💳 Mis créditos y abonos" if st.session_state.user["rol"] != "vendedor" else "💳 Créditos de mis clientes"
    st.title(titulo)
    u = st.session_state.user
    visibles = usernames_visibles_para_usuario(u)
    clause, params = sql_in_clause(visibles)
    df = pd.read_sql_query(f"SELECT * FROM creditos WHERE username IN {clause} ORDER BY id DESC", get_conn(), params=params)
    if u["rol"] == "vendedor":
        st.info("Estás viendo tus créditos y los créditos de tus clientes asignados. La carga de abonos la realiza cada cliente desde su usuario.")
    if df.empty:
        st.info("No hay créditos registrados.")
        return
    for _, cr in df.iterrows():
        with st.expander(f"Crédito #{cr['id']} | {cr['cliente_nombre']} | Vence {cr['fecha_vencimiento']} | Saldo {money_usd(cr['saldo_usd'])} | {cr['status']}"):
            st.write(f"Pedido asociado: #{cr['pedido_id']}")
            st.write(f"Cliente: **{cr['cliente_nombre']}**")
            st.write(f"Monto original: {money_usd(cr['monto_usd'])}")
            st.write(f"Saldo: **{money_usd(cr['saldo_usd'])}**")
            st.caption("Crédito expresado en USD. Si pagas en bolívares, el cálculo se hace con la tasa BCV del día del pago.")
            ab = pd.read_sql_query("SELECT fecha,monto_usd,metodo,referencia,status FROM abonos WHERE credito_id=? ORDER BY id DESC", get_conn(), params=(cr['id'],))
            st.markdown("**Abonos cargados**")
            st.dataframe(ab, use_container_width=True, hide_index=True)

            if u["rol"] != "vendedor" and cr["username"] == u["username"]:
                st.markdown("**Cargar nuevo abono**")
                with st.form(f"abono_{cr['id']}"):
                    monto_usd = st.number_input("Monto USD", min_value=0.0, step=0.01, key=f"monto_{cr['id']}")
                    metodo = st.selectbox("Método", ["Pago móvil", "Transferencia", "Zelle", "Divisas", "Binance", "Otro"], key=f"met_{cr['id']}")
                    ref = st.text_input("Referencia", key=f"ref_{cr['id']}")
                    comp = st.file_uploader("Comprobante", type=["jpg","jpeg","png","webp","pdf"], key=f"comp_{cr['id']}")
                    notas = st.text_area("Notas", key=f"nota_{cr['id']}")
                    enviar = st.form_submit_button("Enviar abono para validar", type="primary")
                if enviar:
                    if monto_usd <= 0:
                        st.error("Indica un monto mayor a cero.")
                    else:
                        tasa = get_tasa_bcv()
                        path = save_uploaded_file(comp, COMPROBANTES_DIR, prefix=f"credito_{cr['id']}_{u['username']}") if comp else None
                        q("""INSERT INTO abonos (credito_id,username,fecha,monto_usd,monto_ves,metodo,referencia,comprobante_path,status,notas)
                             VALUES (?,?,?,?,?,?,?,?,?,?)""",
                          (int(cr['id']), u["username"], now(), monto_usd, monto_usd*tasa, metodo, ref, path, "Pendiente de validar", notas))
                        st.success("Abono cargado. Queda pendiente de validación por administración.")
                        st.rerun()

def creditos_admin():
    st.title("💳 Créditos y abonos")
    tab1, tab2 = st.tabs(["Créditos / cambiar estado", "Abonos por validar"])
    with tab1:
        df = pd.read_sql_query("SELECT * FROM creditos ORDER BY id DESC", get_conn())
        if df.empty: st.info("No hay créditos.")
        else:
            for _, cr in df.iterrows():
                with st.expander(f"Crédito #{cr['id']} | {cr['cliente_nombre']} | Saldo {money_usd(cr['saldo_usd'])} | Vence {cr['fecha_vencimiento']} | {cr['status']}"):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"Pedido: #{cr['pedido_id']}")
                    c2.write(f"Monto: {money_usd(cr['monto_usd'])}")
                    c3.write(f"Saldo: {money_usd(cr['saldo_usd'])}")
                    estados = ["Pendiente", "Parcial", "Pagado", "Vencido", "Anulado"]
                    idx = estados.index(cr['status']) if cr['status'] in estados else 0
                    nuevo = st.selectbox("Estado", estados, index=idx, key=f"estado_cr_{cr['id']}")
                    if nuevo != cr['status']:
                        if nuevo == "Pagado":
                            ok, msg = marcar_credito_pagado_y_finalizar_pedido(int(cr['id']), st.session_state.user["username"])
                            st.success(msg)
                        else:
                            q("UPDATE creditos SET status=? WHERE id=?", (nuevo, int(cr['id'])))
                            if nuevo in ["Pendiente", "Parcial", "Vencido"] and cr.get('pedido_id') is not None:
                                q("UPDATE pedidos SET status='Crédito pendiente' WHERE id=? AND status='Finalizado'", (int(cr['pedido_id']),))
                            log_event("Cambiar estado crédito", "creditos", int(cr['id']), f"{cr['status']} -> {nuevo}")
                        st.rerun()
                    ab = pd.read_sql_query("SELECT * FROM abonos WHERE credito_id=? ORDER BY id DESC", get_conn(), params=(int(cr['id']),))
                    st.dataframe(ab[["id","fecha","monto_usd","metodo","referencia","status"]] if not ab.empty else ab, use_container_width=True, hide_index=True)
                    confirmar_credito = st.checkbox("Confirmar eliminación de este crédito", key=f"confirm_del_credito_{int(cr['id'])}")
                    if st.button("🗑️ Eliminar crédito y sus abonos", key=f"del_credito_{int(cr['id'])}", disabled=not confirmar_credito):
                        q("DELETE FROM abonos WHERE credito_id=?", (int(cr["id"]),))
                        q("UPDATE pedidos SET credito_id=NULL, status='Anulado' WHERE credito_id=?", (int(cr["id"]),))
                        q("DELETE FROM creditos WHERE id=?", (int(cr["id"]),))
                        st.success("Crédito eliminado y pedido asociado marcado como Anulado.")
                        st.rerun()
    with tab2:
        ab = pd.read_sql_query("SELECT a.*, u.nombre FROM abonos a LEFT JOIN usuarios u ON u.username=a.username WHERE a.status='Pendiente de validar' ORDER BY a.id DESC", get_conn())
        if ab.empty: st.success("No hay abonos pendientes.")
        else:
            for _, a in ab.iterrows():
                with st.container():
                    st.markdown(f"### Abono #{a['id']} - {a['nombre'] or a['username']}")
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"Crédito: #{a['credito_id']}")
                    c2.write(f"Monto: {money_usd(a['monto_usd'])} / {money_ves(a['monto_ves'])}")
                    c3.write(f"Método: {a['metodo']} | Ref: {a['referencia']}")
                    if a['comprobante_path'] and os.path.exists(a['comprobante_path']):
                        st.caption(f"Comprobante guardado: {a['comprobante_path']}")
                        if Path(a['comprobante_path']).suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                            st.image(a['comprobante_path'], width=260)
                    colv, colr = st.columns(2)
                    if colv.button("✅ Validar abono", key=f"val_{a['id']}", type="primary"):
                        cr = q("SELECT * FROM creditos WHERE id=?", (int(a['credito_id']),), fetch=True)[0]
                        nuevo_saldo = max(0, float(cr['saldo_usd']) - float(a['monto_usd']))
                        nuevo_status = "Pagado" if nuevo_saldo <= 0.009 else "Parcial"
                        q("UPDATE abonos SET status='Validado', validado_por=?, fecha_validacion=? WHERE id=?", (st.session_state.user["username"], now(), int(a['id'])))
                        q("UPDATE creditos SET saldo_usd=?, status=? WHERE id=?", (nuevo_saldo, nuevo_status, int(a['credito_id'])))
                        if nuevo_status == "Pagado":
                            q("UPDATE pedidos SET status='Finalizado' WHERE credito_id=?", (int(a['credito_id']),))
                        log_event("Validar abono", "abonos", int(a['id']), f"Credito={a['credito_id']}; monto={a['monto_usd']}; saldo={nuevo_saldo}; status={nuevo_status}")
                        st.success("Abono validado y saldo actualizado." + (" Pedido finalizado automáticamente." if nuevo_status == "Pagado" else ""))
                        st.rerun()
                    if colr.button("❌ Rechazar", key=f"rech_{a['id']}"):
                        q("UPDATE abonos SET status='Rechazado', validado_por=?, fecha_validacion=? WHERE id=?", (st.session_state.user["username"], now(), int(a['id'])))
                        log_event("Rechazar abono", "abonos", int(a['id']), f"Credito={a['credito_id']}; monto={a['monto_usd']}")
                        st.warning("Abono rechazado.")
                        st.rerun()
                    st.markdown("---")

def usuarios_admin():
    st.title("👥 Usuarios")
    df = pd.read_sql_query("SELECT * FROM usuarios ORDER BY rol, nombre", get_conn())
    for _, r in df.iterrows():
        with st.expander(f"{r['nombre']} | {r['username']} | {r['rol']}"):
            with st.form(f"user_{r['username']}"):
                c1, c2 = st.columns(2)
                nombre = c1.text_input("Nombre", value=r["nombre"] or "")
                username = c2.text_input("Usuario/correo", value=r["username"] or "")
                rol = c1.selectbox("Rol", ["cliente", "admin", "vendedor"], index=["cliente","admin","vendedor"].index(r["rol"]) if r["rol"] in ["cliente","admin","vendedor"] else 0)
                activo = c2.checkbox("Activo", value=bool(r["activo"]))
                telefono = c1.text_input("Teléfono", value=r["telefono"] or "")
                rif = c2.text_input("RIF/CI", value=r["rif"] or "")
                ciudad = c1.text_input("Ciudad", value=r["ciudad"] or "")
                direccion = st.text_area("Dirección", value=r["direccion"] or "")
                vendedores = get_vendedores()
                opciones_vendedores = ["Sin vendedor asignado"] + [f"{nombre} <{username}>" for username, nombre in vendedores]
                actual_vendedor = r["vendedor_username"] if "vendedor_username" in r.index else None
                actual_idx = 0
                for i, (v_user, v_nom) in enumerate(vendedores, start=1):
                    if v_user == actual_vendedor:
                        actual_idx = i
                        break
                vendedor_sel = st.selectbox("Vendedor asignado", opciones_vendedores, index=actual_idx)
                vendedor_username = None if vendedor_sel == "Sin vendedor asignado" else vendedor_sel.split("<")[-1].replace(">", "").strip()
                st.markdown("#### Reglas de descuento")
                aplica_zelle = st.checkbox("Aplicar descuento Divisas / Zelle", value=bool(r["aplica_zelle_30"]))
                aplica_bcv = st.checkbox("Aplicar descuento BCV desde compra de $100", value=bool(r["aplica_bcv_10_100"]))
                st.markdown("#### Crédito")
                credito = st.checkbox("Habilitar crédito", value=bool(r["credito_habilitado"]))
                limite = st.number_input("Límite de crédito USD", min_value=0.0, value=float(r["limite_credito_usd"] or 0), step=10.0)
                dias = st.number_input("Días de crédito", min_value=1, max_value=365, value=int(r["dias_credito"] or 10), step=1)
                comision_pct = st.number_input("Comisión vendedor/colegio %", min_value=0.0, max_value=100.0, value=float(r["comision_pct"] or 0), step=0.5)
                newpass = st.text_input("Nueva clave, dejar vacío para no cambiar", type="password")
                guardar = st.form_submit_button("Guardar cambios", type="primary")
            if guardar:
                ph = hash_password(newpass) if newpass else r["password_hash"]
                try:
                    q("""UPDATE usuarios SET username=?, password_hash=?, nombre=?, rol=?, telefono=?, rif=?, direccion=?, ciudad=?, activo=?,
                         aplica_zelle_30=?, aplica_bcv_10_100=?, credito_habilitado=?, limite_credito_usd=?, dias_credito=?, vendedor_username=?, comision_pct=? WHERE username=?""",
                      (username, ph, nombre, rol, telefono, rif, direccion, ciudad, 1 if activo else 0, 1 if aplica_zelle else 0,
                       1 if aplica_bcv else 0, 1 if credito else 0, limite, int(dias), vendedor_username, comision_pct, r["username"]))
                    if username != r["username"]:
                        q("UPDATE pedidos SET username=? WHERE username=?", (username, r["username"]))
                        q("UPDATE carritos SET username=? WHERE username=?", (username, r["username"]))
                        q("UPDATE creditos SET username=? WHERE username=?", (username, r["username"]))
                        q("UPDATE abonos SET username=? WHERE username=?", (username, r["username"]))
                        q("UPDATE usuarios SET vendedor_username=? WHERE vendedor_username=?", (username, r["username"]))
                    log_event("Actualizar usuario", "usuarios", username, f"Rol={rol}; activo={activo}; vendedor={vendedor_username}; comision={comision_pct}%")
                    st.success("Usuario actualizado.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Ese usuario/correo ya existe.")

            st.markdown("---")
            if r["username"] == st.session_state.user["username"]:
                st.caption("No puedes eliminar tu propio usuario mientras estás conectado.")
            else:
                confirmar_user = st.checkbox("Confirmar eliminación de este usuario", key=f"confirm_del_user_{r['username']}")
                borrar_user = st.button("🗑️ Eliminar usuario", key=f"del_user_{r['username']}", disabled=not confirmar_user)
                if borrar_user:
                    pedidos = q("SELECT COUNT(*) AS n FROM pedidos WHERE username=?", (r["username"],), fetch=True)[0]["n"]
                    creditos = q("SELECT COUNT(*) AS n FROM creditos WHERE username=?", (r["username"],), fetch=True)[0]["n"]
                    if pedidos or creditos:
                        q("UPDATE usuarios SET activo=0 WHERE username=?", (r["username"],))
                        st.warning("El usuario tiene pedidos o créditos. Se desactivó en vez de eliminarlo para conservar el historial.")
                    else:
                        q("DELETE FROM carritos WHERE username=?", (r["username"],))
                        q("UPDATE usuarios SET vendedor_username=NULL WHERE vendedor_username=?", (r["username"],))
                        q("DELETE FROM usuarios WHERE username=?", (r["username"],))
                        st.success("Usuario eliminado.")
                    st.rerun()
    st.markdown("---")
    with st.expander("➕ Crear nuevo usuario"):
        with st.form("nuevo_usuario"):
            u = st.text_input("Correo/usuario")
            n = st.text_input("Nombre")
            p = st.text_input("Clave", type="password")
            rol = st.selectbox("Rol", ["cliente", "vendedor", "admin"])
            z = st.checkbox("Aplicar 30% Divisas/Zelle", value=False)
            b = st.checkbox("Aplicar descuento BCV desde $100", value=False)
            cred = st.checkbox("Habilitar crédito", value=False)
            limite = st.number_input("Límite crédito USD", min_value=0.0, value=0.0)
            dias = st.number_input("Días crédito", min_value=1, value=10)
            comision_pct = st.number_input("Comisión vendedor/colegio %", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            vendedores = get_vendedores()
            opciones_vendedores = ["Sin vendedor asignado"] + [f"{nombre} <{username}>" for username, nombre in vendedores]
            vendedor_sel = st.selectbox("Vendedor asignado", opciones_vendedores)
            vendedor_username = None if vendedor_sel == "Sin vendedor asignado" else vendedor_sel.split("<")[-1].replace(">", "").strip()
            crear = st.form_submit_button("Crear usuario", type="primary")
        if crear:
            if not u or not p or not n:
                st.error("Usuario, nombre y clave son obligatorios.")
            else:
                try:
                    q("""INSERT INTO usuarios (username,password_hash,nombre,rol,activo,aplica_zelle_30,aplica_bcv_10_100,credito_habilitado,limite_credito_usd,dias_credito,vendedor_username,comision_pct,creado_en)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (u, hash_password(p), n, rol, 1, 1 if z else 0, 1 if b else 0, 1 if cred else 0, limite, int(dias), vendedor_username, comision_pct, now()))
                    log_event("Crear usuario", "usuarios", u, f"Rol={rol}; vendedor={vendedor_username}; comision={comision_pct}%")
                    st.success("Usuario creado.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Ese usuario ya existe.")


def reportes_admin():
    st.title("📈 Reportes y seguimiento")
    tab_alertas, tab_comisiones, tab_excel, tab_estado, tab_auditoria = st.tabs([
        "Alertas de créditos", "Comisiones", "Exportar Excel", "Estado de cuenta", "Auditoría"
    ])

    with tab_alertas:
        st.subheader("Seguimiento de créditos")
        creditos = pd.read_sql_query("SELECT * FROM creditos ORDER BY id DESC", get_conn())
        if creditos.empty:
            st.info("No hay créditos registrados.")
        else:
            hoy = datetime.now().date()
            creditos["venc_dt"] = pd.to_datetime(creditos["fecha_vencimiento"], format="%d/%m/%Y", errors="coerce").dt.date
            vencidos = creditos[(creditos["saldo_usd"] > 0) & (creditos["venc_dt"] < hoy)]
            por_vencer = creditos[(creditos["saldo_usd"] > 0) & (creditos["venc_dt"] >= hoy) & (creditos["venc_dt"] <= hoy + timedelta(days=3))]
            c1, c2, c3 = st.columns(3)
            c1.metric("Vencidos", len(vencidos))
            c2.metric("Vencen en 3 días", len(por_vencer))
            c3.metric("Total por cobrar", money_usd(creditos.loc[creditos["saldo_usd"] > 0, "saldo_usd"].sum()))
            st.markdown("### Créditos vencidos")
            st.dataframe(vencidos[["id","cliente_nombre","fecha_vencimiento","saldo_usd","status"]] if not vencidos.empty else vencidos, use_container_width=True, hide_index=True)
            st.markdown("### Créditos por vencer")
            st.dataframe(por_vencer[["id","cliente_nombre","fecha_vencimiento","saldo_usd","status"]] if not por_vencer.empty else por_vencer, use_container_width=True, hide_index=True)
            st.markdown("### Mensajes rápidos para WhatsApp")
            for _, cr in pd.concat([vencidos, por_vencer]).head(10).iterrows():
                user_rows = q("SELECT telefono FROM usuarios WHERE username=?", (cr["username"],), fetch=True)
                tel = re.sub(r"\D", "", user_rows[0]["telefono"] if user_rows and user_rows[0]["telefono"] else "")
                msg = f"Hola {cr['cliente_nombre']}, le recordamos que su crédito #{int(cr['id'])} del pedido #{int(cr['pedido_id'])} tiene saldo pendiente de {money_usd(cr['saldo_usd'])} y vence/venció el {cr['fecha_vencimiento']}."
                url = f"https://wa.me/{tel}?text={requests.utils.quote(msg)}" if tel else ""
                st.write(f"Crédito #{int(cr['id'])} - {cr['cliente_nombre']}: {msg}")
                if url:
                    st.markdown(f"[Abrir WhatsApp]({url})")

    with tab_comisiones:
        st.subheader("Comisiones estimadas por vendedor")
        st.caption("Base: pedidos de contado no anulados + abonos validados de clientes asignados. La comisión se calcula sobre dinero cobrado, no sobre saldos pendientes.")
        df_com = calcular_comisiones_vendedores()
        st.dataframe(df_com, use_container_width=True, hide_index=True)

    with tab_excel:
        st.subheader("Exportar información")
        st.download_button("📥 Descargar reporte completo Excel", data=crear_excel_reportes(), file_name=f"reportes_pedidos_pointer_{now_file()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    with tab_estado:
        st.subheader("Estado de cuenta por cliente")
        clientes = q("SELECT username,nombre FROM usuarios WHERE rol='cliente' ORDER BY nombre", fetch=True)
        if not clientes:
            st.info("No hay clientes registrados.")
        else:
            opts = [f"{r['nombre']} <{r['username']}>" for r in clientes]
            sel = st.selectbox("Cliente", opts)
            username = sel.split("<")[-1].replace(">", "").strip()
            st.download_button("📄 Descargar estado de cuenta PDF", data=generar_pdf_estado_cuenta_cliente(username), file_name=f"estado_cuenta_{username}_{now_file()}.pdf", mime="application/pdf", use_container_width=True)
            cr = pd.read_sql_query("SELECT id,pedido_id,fecha_vencimiento,monto_usd,saldo_usd,status FROM creditos WHERE username=? ORDER BY id DESC", get_conn(), params=(username,))
            st.dataframe(cr, use_container_width=True, hide_index=True)

    with tab_auditoria:
        st.subheader("Bitácora de cambios")
        logs = pd.read_sql_query("SELECT fecha,usuario,accion,entidad,entidad_id,detalle FROM auditoria ORDER BY id DESC LIMIT 300", get_conn())
        if logs.empty:
            st.info("Aún no hay eventos registrados. La bitácora comenzará a llenarse desde esta versión.")
        else:
            st.dataframe(logs, use_container_width=True, hide_index=True)

def configuracion_admin():
    st.title("⚙️ Configuración")
    st.subheader("Tasa BCV")
    tasa = get_tasa_bcv()
    fecha = get_config("fecha_tasa_bcv", "Sin actualizar")
    fuente = get_config("fuente_tasa_bcv", "Manual")
    st.info(f"Tasa actual: **{tasa:,.2f} Bs/USD** | Última actualización: **{fecha}** | Fuente: **{fuente}**")
    st.caption("La actualización automática intenta leer únicamente el dólar desde bcv.org.ve. No consulta EUR ni P2P.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🌐 Actualizar dólar BCV oficial", type="primary"):
            tasa_auto, fuente_auto, error_auto = obtener_dolar_bcv_oficial()
            if tasa_auto:
                set_config("tasa_bcv", tasa_auto)
                set_config("fecha_tasa_bcv", now())
                set_config("fuente_tasa_bcv", fuente_auto or "BCV oficial")
                st.success(f"Dólar BCV actualizado: {tasa_auto:,.2f} Bs/USD desde {fuente_auto}")
                st.rerun()
            else:
                st.error("No se pudo obtener el dólar BCV automáticamente. Usa la opción manual.")
                if error_auto:
                    with st.expander("Ver detalle técnico del intento"):
                        st.code(error_auto)
    with c2:
        with st.form("manual_bcv"):
            nueva = st.number_input("Tasa manual USD BCV", min_value=0.0, value=float(tasa), step=0.01)
            if st.form_submit_button("Guardar tasa manual"):
                set_config("tasa_bcv", nueva)
                set_config("fecha_tasa_bcv", now() + " (manual)")
                set_config("fuente_tasa_bcv", "Manual")
                st.success("Tasa guardada.")
                st.rerun()
    st.subheader("Descuentos comerciales")
    with st.form("descuentos_comerciales"):
        pct_divisas_actual = get_descuento_divisas_pct()
        pct_bcv_actual = get_descuento_bcv_100_pct()
        pct_divisas_nuevo = st.number_input("Descuento divisas / Zelle (%)", min_value=0.0, max_value=100.0, value=float(pct_divisas_actual), step=0.5)
        pct_bcv_nuevo = st.number_input("Descuento BCV desde compra de $100 (%)", min_value=0.0, max_value=100.0, value=float(pct_bcv_actual), step=0.5)
        st.caption("Estos porcentajes se aplican solo a usuarios que tengan activa cada regla de descuento en su perfil.")
        if st.form_submit_button("Guardar descuentos comerciales"):
            set_config("descuento_divisas_pct", pct_divisas_nuevo)
            set_config("descuento_bcv_100_pct", pct_bcv_nuevo)
            st.success("Descuentos comerciales guardados.")
            st.rerun()

    st.subheader("Datos de empresa")
    with st.form("empresa"):
        nombre = st.text_input("Nombre", value=get_config("nombre_empresa", "Sistema de pedidos pointer V21 Responsive"))
        tel = st.text_input("Teléfono", value=get_config("telefono_empresa", "04127757053"))
        ig = st.text_input("Instagram", value=get_config("instagram_empresa", "@color.insumos"))
        if st.form_submit_button("Guardar datos"):
            set_config("nombre_empresa", nombre); set_config("telefono_empresa", tel); set_config("instagram_empresa", ig)
            st.success("Datos actualizados.")

def respaldo_admin():
    st.title("💾 Respaldo")
    tablas = ["usuarios", "productos", "pedidos", "creditos", "abonos", "carritos", "movimientos_inventario", "configuracion"]
    backup = {}
    for t in tablas:
        backup[t] = pd.read_sql_query(f"SELECT * FROM {t}", get_conn()).to_dict(orient="records")
    data = json.dumps(backup, indent=2, ensure_ascii=False)
    st.download_button("Descargar backup JSON", data=data, file_name=f"backup_pedidos_pointer_v6_{now_file()}.json", mime="application/json", use_container_width=True)
    st.warning("Restaurar sobrescribe registros con el mismo ID/SKU/usuario.")
    up = st.file_uploader("Subir backup JSON", type="json")
    if up and st.button("Restaurar backup", type="primary"):
        try:
            datos = json.load(up)
            for t, rows in datos.items():
                if not rows: continue
                cols = rows[0].keys()
                placeholders = ",".join(["?"]*len(cols))
                sql = f"INSERT OR REPLACE INTO {t} ({','.join(cols)}) VALUES ({placeholders})"
                vals = [tuple(row.get(c) for c in cols) for row in rows]
                q(sql, vals, many=True)
            st.success("Backup restaurado.")
            st.rerun()
        except Exception as e:
            st.error(f"Error restaurando backup: {e}")

# -----------------------------
# MAIN
# -----------------------------
init_db()
if "auth" not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None

if not st.session_state.auth:
    login_screen()
else:
    u = st.session_state.user
    with st.sidebar:
        st.title("🧾 Sistema de pedidos pointer V21 Responsive")
        st.markdown("---")
        st.write(f"**{u['nombre']}**")
        st.caption(f"Usuario: {u['username']}")
        st.caption(f"Rol: {u['rol']}")
        base = ["🛍️ Catálogo / POS", "🛒 Carrito", "📜 Mis pedidos", "💳 Mis créditos"]
        admin = ["📊 Dashboard", "📦 Productos", "📥 Importar", "👥 Usuarios", "💳 Validar créditos", "📈 Reportes", "⚙️ Configuración", "💾 Respaldo"]
        opciones = base + (admin if u["rol"] == "admin" else [])
        st.session_state.force_mobile_view = st.toggle("Forzar vista móvil", value=st.session_state.get("force_mobile_view", False), help="Útil para probar la vista móvil desde escritorio.")
        menu_sidebar = st.radio("Menú", opciones)
        if st.button("Cerrar sesión"):
            logout()

    if is_mobile_view():
        st.caption("📱 Vista móvil activa")
        default_index = opciones.index(menu_sidebar) if menu_sidebar in opciones else 0
        menu = st.selectbox("Menú rápido", opciones, index=default_index, key="menu_mobile_top")
    else:
        menu = menu_sidebar

    if menu == "🛍️ Catálogo / POS": pos_tienda()
    elif menu == "🛒 Carrito": carrito_view()
    elif menu == "📜 Mis pedidos": mis_pedidos()
    elif menu == "💳 Mis créditos": creditos_usuario()
    elif menu == "📊 Dashboard" and u["rol"] == "admin": dashboard_admin()
    elif menu == "📦 Productos" and u["rol"] == "admin": productos_admin()
    elif menu == "📥 Importar" and u["rol"] == "admin": importar_admin()
    elif menu == "👥 Usuarios" and u["rol"] == "admin": usuarios_admin()
    elif menu == "💳 Validar créditos" and u["rol"] == "admin": creditos_admin()
    elif menu == "📈 Reportes" and u["rol"] == "admin": reportes_admin()
    elif menu == "⚙️ Configuración" and u["rol"] == "admin": configuracion_admin()
    elif menu == "💾 Respaldo" and u["rol"] == "admin": respaldo_admin()
    else:
        st.error("No tienes permiso para esta sección.")
