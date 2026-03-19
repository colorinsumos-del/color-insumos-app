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
                  items TEXT, metodo_pago TEXT, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carritos 
                 (username TEXT PRIMARY KEY, data TEXT)''')
    
    # Usuario Administrador por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    # Extrae números y convierte coma en punto
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

# --- AUTENTICACIÓN Y SESIÓN ---
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
            opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Usuarios"]
        menu = st.radio("Menú Principal", opc)
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO 1: TIENDA (CONSUMO DE DATOS) ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        df = pd.read_sql("SELECT * FROM productos", get_connection())
        
        busq = st.text_input("🔍 Buscar por código o nombre...")
        if busq:
            df = df[df['descripcion'].str.contains(busq, case=False, na=False) | 
                    df['sku'].str.contains(busq, case=False, na=False)]

        if df.empty:
            st.info("El catálogo está vacío. Por favor, carga el PDF de Pointer.")
        else:
            for _, row in df.iterrows():
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([1, 3, 1, 1])
                    with col1:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            st.image(row['foto_path'], width=120)
                        else:
                            st.image("https://via.placeholder.com/120?text=S/F", width=120)
                    
                    col2.subheader(row['sku'])
                    col2.write(row['descripcion'])
                    col3.metric("Precio", f"${row['precio']:.2f}")
                    
                    cant = col4.number_input("Cant", 1, 1000, 1, key=f"q_{row['sku']}")
                    if col4.button("Añadir 🛒", key=f"btn_{row['sku']}", use_container_width=True):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario)
                        st.toast(f"Agregado: {row['sku']}")
                        st.rerun()

    # --- MÓDULO 2: CARGA PDF (EL MÉTODO ORIGINAL QUE FUNCIONÓ) ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importador de Catálogo Pointer")
        st.write("Configuración: SKU (A), Imagen (B), Descripción (C), Precio Divisas (E)")
        
        f = st.file_uploader("Subir archivo PDF", type="pdf")
        
        if f and st.button("🚀 Iniciar Procesamiento"):
            with st.status("Leyendo tablas e imágenes...") as status:
                doc = fitz.open(stream=f.read(), filetype="pdf")
                conn = get_connection()
                total_cargados = 0
                
                for page in doc:
                    # Buscamos tablas en la página
                    tabs = page.find_tables()
                    # Pre-identificamos imágenes flotantes en la página
                    img_info = page.get_image_info(hashes=True)
                    
                    for tab in tabs:
                        df_tab = tab.to_pandas()
                        for row_idx, row in df_tab.iterrows():
                            try:
                                # Columna 0: SKU
                                sku = str(row.iloc[0]).strip().replace('\n', '')
                                # Columna 2: Descripción
                                desc = str(row.iloc[2]).strip().replace('\n', ' ')
                                # Columna 4: Precio Divisas (Columna E)
                                precio = limpiar_precio(row.iloc[4])
                                
                                if len(sku) > 2 and precio > 0:
                                    foto_path = ""
                                    # Lógica de imagen: Buscamos en la celda de la Columna B (índice 1)
                                    celda_b = tab.rows[row_idx].cells[1]
                                    if celda_b:
                                        # Expandimos el área de búsqueda ligeramente
                                        rect_celda = fitz.Rect(celda_b).expand(2)
                                        
                                        for img in img_info:
                                            if rect_celda.intersects(fitz.Rect(img['bbox'])):
                                                pix = fitz.Pixmap(doc, img['xref'])
                                                # Convertir a RGB si es necesario
                                                if pix.n - pix.alpha > 3: 
                                                    pix = fitz.Pixmap(fitz.csRGB, pix)
                                                
                                                # Limpiar el nombre del archivo para evitar errores de ruta
                                                safe_sku = re.sub(r'[\\/*?:"<>|]', "_", sku)
                                                p_path = os.path.join(IMG_DIR, f"{safe_sku}.png")
                                                pix.save(p_path)
                                                foto_path = p_path
                                                break
                                    
                                    # Guardado en base de datos
                                    conn.execute("""
                                        INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                        VALUES (?,?,?,?,?) 
                                        ON CONFLICT(sku) 
                                        DO UPDATE SET 
                                            precio=excluded.precio, 
                                            descripcion=excluded.descripcion,
                                            foto_path=CASE WHEN excluded.foto_path != '' THEN excluded.foto_path ELSE foto_path END
                                    """, (sku, desc, precio, "General", foto_path))
                                    total_cargados += 1
                            except: continue
                
                conn.commit()
                status.update(label=f"¡Proceso completado! {total_cargados} productos actualizados.", state="complete")
            st.rerun()

    # --- MANTENIMIENTO DE MÓDULOS DE GESTIÓN ---
    elif menu == "📊 Gestión Ventas":
        st.title("📊 Control de Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        st.dataframe(df_p, use_container_width=True)

    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Usuarios")
        df_u = pd.read_sql("SELECT username, nombre, rol, rif, ciudad FROM usuarios", get_connection())
        st.table(df_u)