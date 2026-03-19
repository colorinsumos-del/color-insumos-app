import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import time
import re
import io
from datetime import datetime
from PIL import Image

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT, 
                  rif TEXT, ciudad TEXT, notas TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, cliente_nombre TEXT, fecha TEXT, 
                  items TEXT, metodo_pago TEXT, subtotal REAL, descuento REAL, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carritos 
                 (username TEXT PRIMARY KEY, data TEXT)''')
    
    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol, direccion, telefono) VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

# --- FUNCIONES DE SOPORTE ---
def guardar_carrito_db(username, carrito_dict):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carritos (username, data) VALUES (?, ?)", (username, json.dumps(carrito_dict)))
    conn.commit()

def cargar_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT data FROM carritos WHERE username=?", (username,)).fetchone()
    return json.loads(res[0]) if res else {}

def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        if clean.count('.') > 1:
            parts = clean.split('.')
            clean = "".join(parts[:-1]) + "." + parts[-1]
        return float(clean)
    except: return 0.0

@st.cache_data(ttl=60)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

# --- FLUJO DE AUTENTICACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    uid = user['user']
    carrito_usuario = cargar_carrito_db(uid)

    subtotal_live = sum(item['p'] * item['c'] for item in carrito_usuario.values())
    desc_live = subtotal_live * 0.10 if subtotal_live > 100 else 0.0
    total_live = subtotal_live - desc_live

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        with st.container(border=True):
            st.subheader("📊 Totales en Vivo")
            st.write(f"Productos: {len(carrito_usuario)}")
            st.write(f"Total: **${total_live:.2f}**")
        
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Usuarios"]
        menu = st.radio("Menú", opc)
        if st.button("Salir"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        df = cargar_catalogo()
        busq = st.text_input("🔍 Buscar por SKU o Descripción...")
        if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]

        for i, row in df.iterrows():
            item_carrito = carrito_usuario.get(row['sku'])
            with st.container(border=(item_carrito is not None)):
                c1, c2, c3, c4, c5, c6 = st.columns([0.8, 1.2, 4, 1, 1.2, 1])
                with c1:
                    try:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            img_valida = Image.open(row['foto_path'])
                            st.image(img_valida, width=70)
                        else: st.image("https://via.placeholder.com/70?text=📦", width=70)
                    except: st.image("https://via.placeholder.com/70?text=Err", width=70)
                
                c2.markdown(f"**{row['sku']}**")
                c3.write(row['descripcion'])
                c4.markdown(f"**${row['precio']:.2f}**")
                cant = c5.number_input("n", 1, 500, int(item_carrito['c']) if item_carrito else 1, key=f"q_{row['sku']}", label_visibility="collapsed")
                
                if item_carrito:
                    if cant != item_carrito['c']:
                        carrito_usuario[row['sku']]['c'] = cant
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    if c6.button("🗑️", key=f"del_{row['sku']}"):
                        del carrito_usuario[row['sku']]; guardar_carrito_db(uid, carrito_usuario); st.rerun()
                else:
                    if c6.button("🛒", key=f"add_{row['sku']}"):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO CARRITO ---
    elif "🛒" in menu:
        st.title("🛒 Confirmar Pedido")
        if not carrito_usuario: st.info("Tu carrito está vacío")
        else:
            for sku, info in list(carrito_usuario.items()):
                with st.container(border=True):
                    col1, col2, col3 = st.columns([4, 1, 1])
                    col1.write(f"**{sku}** - {info['desc']}")
                    col2.write(f"${info['p']:.2f} x {info['c']}")
                    if col3.button("Eliminar", key=f"rcart_{sku}"):
                        del carrito_usuario[sku]; guardar_carrito_db(uid, carrito_usuario); st.rerun()
            
            st.divider()
            metodo = st.selectbox("Método de Pago", ["Zelle / Divisas", "Transferencia BS (BCV)"])
            if st.button("Finalizar Compra ✅", type="primary", use_container_width=True):
                get_connection().execute(
                    "INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(list(carrito_usuario.values())), metodo, subtotal_live, desc_live, total_live, "Pendiente")
                )
                guardar_carrito_db(uid, {}); get_connection().commit(); st.success("¡Pedido enviado!"); time.sleep(1); st.rerun()

    # --- MÓDULO CARGAR PDF (CON EXTRACCIÓN DE IMÁGENES) ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario e Imágenes")
        f = st.file_uploader("Subir PDF de Pointer", type="pdf")
        if f and st.button("Procesar Inventario"):
            with st.status("Leyendo PDF y extrayendo fotos...") as status:
                doc = fitz.open(stream=f.read(), filetype="pdf")
                conn = get_connection()
                for page in doc:
                    tabs = page.find_tables()
                    if tabs:
                        for tab in tabs:
                            df_tab = tab.to_pandas()
                            for row in df_tab.itertuples():
                                try:
                                    sku, desc, precio = str(row[1]).strip(), str(row[3]).strip(), limpiar_precio(row[5])
                                    if len(sku) > 3:
                                        foto_path = ""
                                        celda_img = tab.rows[row.Index].cells[1]
                                        if celda_img:
                                            for img in page.get_image_info(hashes=True):
                                                if fitz.Rect(img['bbox']).intersects(celda_img):
                                                    pix = fitz.Pixmap(doc, img['xref'])
                                                    path = os.path.join(IMG_DIR, f"{sku}.png")
                                                    pix.save(path); foto_path = path; break
                                        
                                        conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                                     VALUES (?,?,?,?,?) ON CONFLICT(sku) 
                                                     DO UPDATE SET precio=excluded.precio, foto_path=excluded.foto_path""", 
                                                     (sku, desc, precio, "General", foto_path))
                                except: continue
                conn.commit()
                status.update(label="¡Listo!", state="complete")
            st.rerun()

    # --- MÓDULO USUARIOS (GESTIÓN COMPLETA) ---
    elif menu == "👥 Usuarios":
        st.title("👥 Administración de Usuarios")
        t1, t2 = st.tabs(["Lista de Usuarios", "➕ Nuevo"])
        with t1:
            df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
            for _, u_row in df_u.iterrows():
                with st.expander(f"👤 {u_row['nombre']} ({u_row['username']})"):
                    with st.form(f"edit_{u_row['username']}"):
                        c1, c2 = st.columns(2)
                        en = c1.text_input("Nombre", value=u_row['nombre'])
                        ec = c2.text_input("Clave", value=u_row['password'])
                        er = c1.selectbox("Rol", ["admin", "cliente"], index=0 if u_row['rol']=="admin" else 1)
                        if st.form_submit_button("Guardar"):
                            get_connection().execute("UPDATE usuarios SET nombre=?, password=?, rol=? WHERE username=?", (en, ec, er, u_row['username']))
                            get_connection().commit(); st.rerun()
                        if st.form_submit_button("Eliminar"):
                            get_connection().execute("DELETE FROM usuarios WHERE username=?", (u_row['username'],))
                            get_connection().commit(); st.rerun()
        with t2:
            with st.form("nuevo_u"):
                st.subheader("Registrar Nuevo")
                nu, np, nn = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
                nr = st.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("Crear"):
                    get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (nu, np, nn, nr))
                    get_connection().commit(); st.success("Creado"); st.rerun()

    # --- GESTIÓN VENTAS Y PEDIDOS ---
    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📜 Historial")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}'"
        df_p = pd.read_sql(query, get_connection())
        for _, p in df_p.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} (${p['total']})"):
                st.write(f"**Cliente:** {p['cliente_nombre']} | **Status:** {p['status']}")
                st.table(pd.DataFrame(json.loads(p['items'])))
                if user['rol'] == 'admin':
                    ns = st.selectbox("Nuevo Estado", ["Pendiente", "Pagado", "Enviado"], key=f"s_{p['id']}")
                    if st.button("Actualizar", key=f"b_{p['id']}"):
                        get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (ns, p['id']))
                        get_connection().commit(); st.rerun()