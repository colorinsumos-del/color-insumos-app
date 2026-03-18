import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import json
import shutil
import time
from datetime import datetime
from PIL import Image  # Librería para redimensionar imágenes

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE VELOCIDAD (CACHÉ) ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- INICIALIZACIÓN Y MIGRACIÓN ---
def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    cursor = conn.execute("PRAGMA table_info(usuarios)")
    columnas = [info[1] for info in cursor.fetchall()]
    if "direccion" not in columnas:
        conn.execute("ALTER TABLE usuarios ADD COLUMN direccion TEXT DEFAULT ''")
    if "telefono" not in columnas:
        conn.execute("ALTER TABLE usuarios ADD COLUMN telefono TEXT DEFAULT ''")
    
    try:
        conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                     ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Oficina Central', '0000-00-00'))
        conn.commit()
    except: pass

# --- FUNCIONES DE PROCESAMIENTO (IMÁGENES PEQUEÑAS) ---
def procesar_pdf(pdf_file):
    progress_bar = st.progress(0)
    with open("temp.pdf", "wb") as f: f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)
    
    with pdfplumber.open("temp.pdf") as pdf:
        total_p = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            tables = page.find_tables()
            if not tables: continue
            imgs_pag = [{'bbox': img['bbox'], 'xref': x[0]} for img, x in zip(doc[i].get_image_info(), doc[i].get_images(full=True))]
            for row in tables[0].rows:
                try:
                    sku_t = page.within_bbox(row.cells[0]).extract_text()
                    if not sku_t or "REFERENCIA" in sku_t.upper(): continue
                    sku = sku_t.strip().split('\n')[0]
                    desc = page.within_bbox(row.cells[2]).extract_text().replace('\n', ' ').strip()
                    precio = float(page.within_bbox(row.cells[3]).extract_text().replace(',', '.').strip())
                    y_mid = (row.bbox[1] + row.bbox[3]) / 2
                    
                    f_path = ""
                    for img in imgs_pag:
                        if img['bbox'][1] <= y_mid <= img['bbox'][3]:
                            pix = fitz.Pixmap(doc, img['xref'])
                            if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                            
                            # --- REDIMENSIONAMIENTO A MINIATURA ---
                            img_pil = Image.open(io.BytesIO(pix.tobytes()))
                            img_pil.thumbnail((300, 300)) # Tamaño máximo 300px
                            f_path = os.path.join(IMG_DIR, f"{sku}.webp")
                            img_pil.save(f_path, "WEBP", quality=75) # WebP es más ligero
                            break
                    
                    productos.append({"sku": sku, "descripcion": desc, "precio": precio, 
                                    "categoria": "VARIOS", "foto_path": f_path})
                except: continue
            progress_bar.progress((i + 1) / total_p)
            
    pd.DataFrame(productos).to_sql('productos', get_connection(), if_exists='replace', index=False)
    st.cache_data.clear()
    st.success("Catálogo y miniaturas actualizadas.")

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.write(f"### ${row['precio']:.2f}")
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast("✅ Añadido")

# --- ESTILOS CSS ---
st.markdown("<style>html { overflow-y: scroll !important; } .stButton button { border-radius: 8px; }</style>", unsafe_allow_html=True)

# --- INICIO DE APLICACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'carrito' not in st.session_state: st.session_state.carrito = {}

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
else:
    user = st.session_state.user_data
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("🔄 Sincronizar"): st.cache_data.clear(); st.rerun()
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav = ["🛒 Tienda", "📊 Pedidos", "📁 Cargar PDF", "👥 Clientes"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav)

    # --- TIENDA ---
    if "🛒" in menu:
        df = obtener_catalogo_cache()
        busq = st.text_input("🔍 Buscar SKU o Nombre...")
        if busq:
            df_v = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            cols = st.columns(5) # 5 columnas ahora que las fotos son pequeñas
            for idx, row in df_v.reset_index().iterrows():
                with cols[idx % 5]: card_producto(row, idx)
        else: st.info("Escribe algo para buscar productos.")

    # --- GESTIÓN DE CLIENTES (CORRECCIÓN DE VISIBILIDAD) ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        t1, t2 = st.tabs(["Lista", "Nuevo"])
        with t1:
            # Filtro corregido: muestra a todos los que NO son admin
            df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin'", get_connection())
            for idx, row in df_u.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['nombre']}** ({row['username']})")
                    c2.write(f"📞 {row['telefono']} | 📍 {row['direccion']}")
                    if c3.button("🗑️", key=f"del_{row['username']}"):
                        get_connection().execute("DELETE FROM usuarios WHERE username=?", (row['username'],))
                        get_connection().commit(); st.rerun()
        with t2:
            with st.form("new_u"):
                nu, np, nn = st.text_input("ID/Email"), st.text_input("Clave"), st.text_input("Nombre")
                nt, nd = st.text_input("Teléfono"), st.text_area("Dirección")
                if st.form_submit_button("Registrar"):
                    get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (nu, np, nn, 'cliente', nd, nt))
                    get_connection().commit(); st.success("Registrado"); st.rerun()

    # --- PEDIDOS TOTALES ---
    elif menu == "📊 Pedidos":
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']}"):
                st.table(pd.DataFrame(json.loads(p['items'])))
                if st.button(f"🗑️ Eliminar Pedido #{p['id']}", key=f"dp_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Procesar"):
            with st.spinner("Optimizando imágenes..."): procesar_pdf(f)