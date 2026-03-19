import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import re
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
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

def guardar_carrito_db(username, carrito_dict):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carritos (username, data) VALUES (?, ?)", (username, json.dumps(carrito_dict)))
    conn.commit()

def cargar_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT data FROM carritos WHERE username=?", (username,)).fetchone()
    return json.loads(res[0]) if res else {}

# --- FLUJO DE SESIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
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

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': opc += ["📁 Cargar PDF", "👥 Usuarios"]
        menu = st.radio("Menú", opc)
        if st.button("Salir"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA (CORREGIDO) ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        
        # Forzar lectura fresca de la base de datos
        conn = get_connection()
        df = pd.read_sql("SELECT * FROM productos", conn)
        
        if df.empty:
            st.info("El catálogo está vacío. Por favor, carga un PDF desde el panel de administrador.")
        else:
            busq = st.text_input("🔍 Buscar por SKU o Descripción...")
            if busq:
                df = df[df['descripcion'].str.contains(busq, case=False, na=False) | 
                        df['sku'].str.contains(busq, case=False, na=False)]

            for i, row in df.iterrows():
                item_carrito = carrito_usuario.get(row['sku'])
                with st.container(border=True):
                    c1, c2, c3, c4, c5 = st.columns([1, 4, 1, 1, 1])
                    with c1:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            st.image(row['foto_path'], width=100)
                        else:
                            st.image("https://via.placeholder.com/100?text=SIN+FOTO", width=100)
                    
                    c2.subheader(row['sku'])
                    c2.write(row['descripcion'])
                    c3.write(f"**${row['precio']:.2f}**")
                    
                    cant = c4.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                    
                    if c5.button("🛒 Añadir", key=f"add_{row['sku']}"):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario)
                        st.toast(f"Añadido: {row['sku']}")
                        st.rerun()

    # --- MÓDULO CARGAR PDF (BASADO EN TUS CELDAS) ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importador de Inventario")
        f = st.file_uploader("Sube el PDF de Pointer", type="pdf")
        if f and st.button("Procesar Inventario"):
            with st.status("Analizando PDF...") as status:
                doc = fitz.open(stream=f.read(), filetype="pdf")
                conn = get_connection()
                
                for page in doc:
                    tabs = page.find_tables()
                    for tab in tabs:
                        df_tab = tab.to_pandas()
                        for row_idx, row in df_tab.iterrows():
                            try:
                                # Según tu archivo: Col 0=SKU, Col 2=Desc, Col 3=Precio
                                sku = str(row.iloc[0]).strip().replace('\n', '')
                                desc = str(row.iloc[2]).strip().replace('\n', ' ')
                                precio = limpiar_precio(row.iloc[3])
                                
                                if len(sku) > 2 and precio > 0:
                                    foto_path = ""
                                    # Buscar imagen en celda 1
                                    celda = tab.rows[row_idx].cells[1]
                                    if celda:
                                        rect = fitz.Rect(celda)
                                        for img in page.get_image_info(hashes=True):
                                            if rect.intersects(fitz.Rect(img['bbox'])):
                                                pix = fitz.Pixmap(doc, img['xref'])
                                                if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                                                safe_sku = re.sub(r'[\\/*?:"<>|]', "_", sku)
                                                p_path = os.path.join(IMG_DIR, f"{safe_sku}.png")
                                                pix.save(p_path)
                                                foto_path = p_path
                                                break
                                    
                                    conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                                 VALUES (?,?,?,?,?) ON CONFLICT(sku) 
                                                 DO UPDATE SET precio=excluded.precio, descripcion=excluded.descripcion, foto_path=excluded.foto_path""", 
                                                 (sku, desc, precio, "General", foto_path))
                            except: continue
                conn.commit()
                status.update(label="Inventario cargado correctamente!", state="complete")
            st.rerun()

    # --- OTROS MÓDULOS (USUARIOS, CARRITO) ---
    elif "Carrito" in menu:
        st.title("🛒 Tu Carrito")
        if not carrito_usuario:
            st.info("Tu carrito está vacío")
        else:
            for s, i in list(carrito_usuario.items()):
                st.write(f"**{s}** - {i['desc']} | ${i['p']} x {i['c']}")
                if st.button("Eliminar", key=f"del_{s}"):
                    del carrito_usuario[s]
                    guardar_carrito_db(uid, carrito_usuario)
                    st.rerun()

    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Usuarios")
        df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
        st.dataframe(df_u)