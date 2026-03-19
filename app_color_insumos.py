import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
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

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Gestión Ventas", "📁 Cargar Inventario", "👥 Usuarios"]
        menu = st.radio("Menú", opc)
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        df = pd.read_sql("SELECT * FROM productos", get_connection())
        busq = st.text_input("🔍 Buscar...")
        if busq:
            df = df[df['descripcion'].str.contains(busq, case=False, na=False) | df['sku'].str.contains(busq, case=False, na=False)]
        
        for _, row in df.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 3, 1, 1])
                with c1:
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], width=100)
                    else: st.image("https://via.placeholder.com/100?text=S/F", width=100)
                c2.write(f"**{row['sku']}**\n\n{row['descripcion']}")
                c3.subheader(f"${row['precio']:.2f}")
                cant = c4.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                if c4.button("🛒", key=f"add_{row['sku']}"):
                    carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                    guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO CARGA (PDF Y EXCEL) ---
    elif menu == "📁 Cargar Inventario":
        st.title("📁 Importador Maestro")
        st.info("Configurado para: SKU(A), Imagen(B), Descripción(C), Precio(E)")
        f = st.file_uploader("Subir Archivo", type=["pdf", "xlsx"])
        
        if f and st.button("🚀 Iniciar Procesamiento"):
            conn = get_connection()
            if f.name.endswith('.xlsx'):
                df_ex = pd.read_excel(f)
                for _, row in df_ex.iterrows():
                    try:
                        sku = str(row.iloc[0]).strip()
                        desc = str(row.iloc[2]).strip()
                        precio = limpiar_precio(row.iloc[4]) # Columna E
                        if len(sku) > 2 and precio > 0:
                            conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, descripcion=excluded.descripcion", (sku, desc, precio, "General"))
                    except: continue
                conn.commit()
                st.success("Excel cargado")
            else:
                # PROCESAMIENTO PDF CON FOCO EN COLUMNA B PARA IMÁGENES
                doc = fitz.open(stream=f.read(), filetype="pdf")
                for page in doc:
                    tabs = page.find_tables()
                    img_list = page.get_image_info(hashes=True)
                    for tab in tabs:
                        df_tab = tab.to_pandas()
                        for row_idx, row in df_tab.iterrows():
                            try:
                                sku = str(row.iloc[0]).strip().replace('\n', '')
                                desc = str(row.iloc[2]).strip().replace('\n', ' ')
                                precio = limpiar_precio(row.iloc[4]) # Columna E
                                
                                if len(sku) > 2 and precio > 0:
                                    foto_path = ""
                                    # BUSCAR IMAGEN EN COLUMNA B (CELDA 1)
                                    celda_b = tab.rows[row_idx].cells[1]
                                    if celda_b:
                                        rect = fitz.Rect(celda_b)
                                        for img in img_list:
                                            if rect.intersects(fitz.Rect(img['bbox'])):
                                                pix = fitz.Pixmap(doc, img['xref'])
                                                if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                                                p_path = os.path.join(IMG_DIR, f"{sku.replace('/','_')}.png")
                                                pix.save(p_path)
                                                foto_path = p_path
                                                break
                                    
                                    conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                                 VALUES (?,?,?,?,?) ON CONFLICT(sku) 
                                                 DO UPDATE SET precio=excluded.precio, foto_path=excluded.foto_path""", 
                                                 (sku, desc, precio, "General", foto_path))
                            except: continue
                conn.commit()
                st.success("PDF Procesado")
            st.rerun()

    # --- RESTO DE MÓDULOS ---
    elif menu == "👥 Usuarios":
        st.title("👥 Usuarios")
        df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
        st.dataframe(df_u)

    elif "Ventas" in menu:
        st.title("📊 Ventas")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        st.dataframe(df_p)