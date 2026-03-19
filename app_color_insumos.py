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
from PIL import Image  # Para validar imágenes corruptas

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
    # Tablas Base con todas las columnas necesarias
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

    # Sidebar con Totales en Vivo
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
                
                with c1: # CORRECCIÓN VALUERROR IMAGEN
                    try:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            img = Image.open(row['foto_path'])
                            st.image(img, width=60)
                        else: st.image("https://via.placeholder.com/60?text=📦", width=60)
                    except: st.image("https://via.placeholder.com/60?text=Error", width=60)
                
                c2.markdown(f"**{row['sku']}**")
                c3.write(row['descripcion'])
                c4.markdown(f"**${row['precio']:.2f}**")
                
                cant = c5.number_input("Cant", 1, 100, int(item_carrito['c']) if item_carrito else 1, key=f"q_{row['sku']}")
                
                if item_carrito:
                    if cant != item_carrito['c']:
                        carrito_usuario[row['sku']]['c'] = cant
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    if c6.button("🗑️", key=f"del_{row['sku']}"):
                        del carrito_usuario[row['sku']]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                else:
                    if c6.button("🛒", key=f"add_{row['sku']}"):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO USUARIOS (AMPLIADO) ---
    elif menu == "👥 Usuarios":
        st.title("👥 Administración de Usuarios")
        t1, t2 = st.tabs(["Lista de Usuarios", "➕ Crear Nuevo"])
        
        with t1:
            bus_user = st.text_input("Filtrar usuarios...")
            df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
            if bus_user: df_u = df_u[df_u['nombre'].str.contains(bus_user, case=False) | df_u['username'].str.contains(bus_user, case=False)]
            
            for _, u_row in df_u.iterrows():
                with st.expander(f"👤 {u_row['nombre']} ({u_row['rol']})"):
                    with st.form(f"f_edit_{u_row['username']}"):
                        col_a, col_b = st.columns(2)
                        e_nom = col_a.text_input("Nombre", value=u_row['nombre'])
                        e_pass = col_b.text_input("Clave", value=u_row['password'], type="password")
                        e_rif = col_a.text_input("RIF/CI", value=u_row.get('rif', ''))
                        e_tlf = col_b.text_input("Teléfono", value=u_row['telefono'])
                        e_rol = col_a.selectbox("Rol", ["admin", "cliente"], index=0 if u_row['rol']=="admin" else 1)
                        e_ciu = col_b.text_input("Ciudad", value=u_row.get('ciudad', ''))
                        e_dir = st.text_area("Dirección", value=u_row['direccion'])
                        
                        b1, b2, _ = st.columns([1, 1, 3])
                        if b1.form_submit_button("💾 Actualizar"):
                            get_connection().execute("""UPDATE usuarios SET nombre=?, password=?, rif=?, telefono=?, rol=?, ciudad=?, direccion=? 
                                                     WHERE username=?""", (e_nom, e_pass, e_rif, e_tlf, e_rol, e_ciu, e_dir, u_row['username']))
                            get_connection().commit(); st.success("Guardado"); st.rerun()
                        if b2.form_submit_button("🗑️ Eliminar"):
                            if u_row['username'] != 'colorinsumos@gmail.com':
                                get_connection().execute("DELETE FROM usuarios WHERE username=?", (u_row['username'],))
                                get_connection().commit(); st.rerun()
                            else: st.error("No se puede eliminar el admin principal")

        with t2:
            with st.form("nuevo_u"):
                st.subheader("Datos del Nuevo Usuario")
                c1, c2 = st.columns(2)
                n_user = c1.text_input("Email/Usuario (ID)")
                n_pass = c2.text_input("Contraseña")
                n_nom = c1.text_input("Nombre Completo")
                n_rol = c2.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("Crear Usuario"):
                    try:
                        get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                                                 (n_user, n_pass, n_nom, n_rol))
                        get_connection().commit(); st.success("Usuario Creado"); st.rerun()
                    except: st.error("El usuario ya existe")

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
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
            
            st.divider()
            metodo = st.selectbox("Método de Pago", ["Zelle / Divisas", "Transferencia BS (BCV)"])
            st.write(f"### Total a Pagar: ${total_live:.2f}")
            
            if st.button("Finalizar Compra ✅", type="primary", use_container_width=True):
                get_connection().execute(
                    "INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(list(carrito_usuario.values())), metodo, subtotal_live, desc_live, total_live, "Pendiente")
                )
                guardar_carrito_db(uid, {}); get_connection().commit()
                st.success("¡Pedido registrado exitosamente!"); time.sleep(1); st.rerun()

    # --- MÓDULO PDF / INVENTARIO ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario desde PDF")
        f = st.file_uploader("Subir PDF de Proveedor", type="pdf")
        if f and st.button("Procesar Archivo"):
            with open("temp.pdf", "wb") as file: file.write(f.getbuffer())
            doc = fitz.open("temp.pdf")
            conn = get_connection()
            for page in doc:
                tabs = page.find_tables()
                if tabs:
                    for tab in tabs:
                        for row in tab.to_pandas().itertuples():
                            try:
                                sku, desc, prec = str(row[1]), str(row[3]), limpiar_precio(row[5])
                                if len(sku) > 2:
                                    conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio", (sku, desc, prec, "General"))
                            except: pass
            conn.commit(); st.success("Inventario actualizado correctamente"); st.rerun()

    # --- HISTORIAL DE PEDIDOS ---
    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📜 Historial de Transacciones")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        df_p = pd.read_sql(query, get_connection())
        for _, p in df_p.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} | Total: ${p['total']:.2f} ({p['status']})"):
                st.write(f"**Cliente:** {p['cliente_nombre']} | **Pago:** {p['metodo_pago']}")
                st.table(pd.DataFrame(json.loads(p['items'])))
                if user['rol'] == 'admin':
                    new_status = st.selectbox("Cambiar Estado", ["Pendiente", "Pagado", "Despachado"], key=f"st_{p['id']}")
                    if st.button("Actualizar Estado", key=f"up_{p['id']}"):
                        get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (new_status, p['id']))
                        get_connection().commit(); st.rerun()