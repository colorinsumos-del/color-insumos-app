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
    # Limpieza para el formato del PDF de Pointer
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

@st.cache_data(ttl=60)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

# --- INICIO DE SISTEMA ---
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

    # Cálculo de totales para el Sidebar
    subtotal_live = sum(item['p'] * item['c'] for item in carrito_usuario.values())
    desc_live = subtotal_live * 0.10 if subtotal_live > 100 else 0.0
    total_live = subtotal_live - desc_live

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        st.write(f"Rol: {user['rol'].upper()}")
        st.divider()
        st.subheader("🛒 Resumen")
        st.write(f"Items: {len(carrito_usuario)}")
        st.write(f"Total: **${total_live:.2f}**")
        
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Usuarios"]
        
        menu = st.radio("Menú Principal", opc)
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        df = cargar_catalogo()
        busq = st.text_input("🔍 Buscar por SKU o Descripción...")
        if busq: 
            df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]

        for i, row in df.iterrows():
            item_carrito = carrito_usuario.get(row['sku'])
            with st.container(border=(item_carrito is not None)):
                c1, c2, c3, c4, c5, c6 = st.columns([1, 1.5, 4, 1, 1, 1])
                with c1:
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], width=80)
                    else: st.image("https://via.placeholder.com/80?text=📦", width=80)
                
                c2.markdown(f"**{row['sku']}**")
                c3.write(row['descripcion'])
                c4.markdown(f"**${row['precio']:.2f}**")
                
                cant = c5.number_input("Cant", 1, 1000, int(item_carrito['c']) if item_carrito else 1, key=f"q_{row['sku']}", label_visibility="collapsed")
                
                if item_carrito:
                    if c6.button("🗑️", key=f"del_{row['sku']}"):
                        del carrito_usuario[row['sku']]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                else:
                    if c6.button("🛒", key=f"add_{row['sku']}"):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO CARGAR PDF (BASADO EN CELDAS) ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario (Pointer)")
        f = st.file_uploader("Subir PDF de Lista de Precios", type="pdf")
        
        if f and st.button("Procesar Celdas del PDF"):
            with st.status("Leyendo celdas y fotos...") as status:
                doc = fitz.open(stream=f.read(), filetype="pdf")
                conn = get_connection()
                
                for page in doc:
                    tabs = page.find_tables()
                    if tabs:
                        for tab in tabs:
                            df_tab = tab.to_pandas()
                            # Pointer PDF: Col 0=SKU, Col 1=Imagen, Col 2=Desc, Col 3=Precio Divisa
                            for row_idx, row in df_tab.iterrows():
                                try:
                                    sku = str(row.iloc[0]).strip()
                                    desc = str(row.iloc[2]).strip()
                                    precio = limpiar_precio(row.iloc[3])
                                    
                                    if len(sku) > 2 and precio > 0:
                                        foto_path = ""
                                        # Extraer imagen de la celda específica (Columna 1)
                                        celda_img = tab.rows[row_idx].cells[1]
                                        rect_celda = fitz.Rect(celda_img)
                                        
                                        for img_info in page.get_image_info(hashes=True):
                                            if rect_celda.intersects(fitz.Rect(img_info['bbox'])):
                                                pix = fitz.Pixmap(doc, img_info['xref'])
                                                if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                                                
                                                safe_sku = re.sub(r'[\\/*?:"<>|]', "_", sku)
                                                p_path = os.path.join(IMG_DIR, f"{safe_sku}.png")
                                                pix.save(p_path)
                                                foto_path = p_path
                                                break
                                        
                                        conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                                     VALUES (?,?,?,?,?) ON CONFLICT(sku) 
                                                     DO UPDATE SET precio=excluded.precio, foto_path=excluded.foto_path""", 
                                                     (sku, desc, precio, "General", foto_path))
                                except: continue
                conn.commit()
                status.update(label="¡Inventario actualizado!", state="complete")
            st.rerun()

    # --- MÓDULO USUARIOS (COMPLETO) ---
    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Clientes y Equipo")
        t1, t2 = st.tabs(["Lista de Usuarios", "➕ Crear Nuevo"])
        
        with t1:
            bus_cli = st.text_input("Buscar por nombre, RIF o ciudad...")
            df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
            if bus_cli:
                df_u = df_u[df_u['nombre'].str.contains(bus_cli, case=False, na=False)]
            
            for _, cli in df_u.iterrows():
                with st.expander(f"👤 {cli['nombre']} | {cli['rol'].upper()}"):
                    with st.form(key=f"ed_u_{cli['username']}"):
                        col1, col2 = st.columns(2)
                        en = col1.text_input("Nombre", value=cli['nombre'])
                        erif = col2.text_input("RIF", value=cli.get('rif', ''))
                        ep = col1.text_input("Clave", value=cli['password'])
                        et = col2.text_input("Teléfono", value=cli['telefono'])
                        ec = col1.text_input("Ciudad", value=cli.get('ciudad', ''))
                        ed = st.text_area("Dirección", value=cli['direccion'])
                        ero = st.selectbox("Rol", ["cliente", "admin"], index=0 if cli['rol']=='cliente' else 1)
                        
                        b1, b2 = st.columns(2)
                        if b1.form_submit_button("💾 Guardar"):
                            get_connection().execute(
                                "UPDATE usuarios SET nombre=?, password=?, telefono=?, direccion=?, rif=?, ciudad=?, rol=? WHERE username=?",
                                (en, ep, et, ed, erif, ec, ero, cli['username'])
                            )
                            get_connection().commit(); st.success("Actualizado"); st.rerun()
                        if b2.form_submit_button("🗑️ Eliminar"):
                            get_connection().execute("DELETE FROM usuarios WHERE username=?", (cli['username'],))
                            get_connection().commit(); st.rerun()

        with t2:
            with st.form("nuevo_u"):
                st.subheader("Registrar Nuevo Usuario")
                c1, c2 = st.columns(2)
                nu = c1.text_input("Correo/Usuario")
                np = c2.text_input("Contraseña")
                nn = c1.text_input("Nombre Completo")
                nr = c2.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("🚀 Crear Usuario"):
                    get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (nu, np, nn, nr))
                    get_connection().commit(); st.success("Creado con éxito"); st.rerun()

    # --- GESTIÓN VENTAS Y PEDIDOS ---
    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📜 Historial de Transacciones")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}'"
        df_p = pd.read_sql(query, get_connection())
        
        for _, p in df_p.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} | Total: ${p['total']:.2f}"):
                st.write(f"**Cliente:** {p['cliente_nombre']} | **Status:** {p['status']}")
                st.table(pd.DataFrame(json.loads(p['items'])))
                if user['rol'] == 'admin':
                    ns = st.selectbox("Cambiar Estado", ["Pendiente", "Pagado", "Enviado"], key=f"s_{p['id']}")
                    if st.button("Actualizar", key=f"b_{p['id']}"):
                        get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (ns, p['id']))
                        get_connection().commit(); st.rerun()