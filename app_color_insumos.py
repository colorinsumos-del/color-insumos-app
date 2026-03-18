import streamlit as st
import pandas as pd
import sqlite3
import os
import re
import fitz  # PyMuPDF para imágenes y texto avanzado
import io
from PIL import Image
from datetime import datetime

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v30.db"
IMG_DIR = "static/productos"
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos Pro", layout="wide")

# --- ESTILOS ---
st.markdown("""
    <style>
    .product-card {
        background-color: white;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #eee;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .product-img {
        width: 100%;
        height: 150px;
        object-fit: contain;
    }
    .price-tag { color: #1a73e8; font-size: 20px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- BASE DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, imagen_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito 
                 (username TEXT, sku TEXT, nombre TEXT, precio REAL, cantidad INTEGER, PRIMARY KEY(username, sku))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)''')
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES ('colorinsumos@gmail.com','20880157','Admin','admin')")
    conn.commit()

# --- MOTOR DE EXTRACCIÓN AVANZADO (TEXTO + IMÁGENES) ---
def procesar_pdf_avanzado(uploaded_file):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    conn = get_connection()
    productos_leidos = 0

    for page_index in range(len(doc)):
        page = doc[page_index]
        tabs = page.find_tables() # Busca tablas estructuradas
        
        # Extraer imágenes de la página
        image_list = page.get_images(full=True)
        
        if tabs:
            for tab in tabs:
                df = tab.to_pandas()
                # Limpiar nombres de columnas
                df.columns = [str(c).upper().strip() for c in df.columns]
                
                # Identificar columnas por posición o nombre
                col_sku = 0 
                col_desc = 1
                col_bcv = next((i for i, c in enumerate(df.columns) if "BCV" in c), 2)

                for _, row in df.iterrows():
                    sku = str(row.iloc[col_sku]).strip()
                    if not sku or sku == "None" or len(sku) < 2: continue
                    
                    desc = str(row.iloc[col_desc]).strip()
                    
                    # Limpieza profunda de precios para evitar el "0"
                    raw_price = str(row.iloc[col_bcv])
                    # Extrae solo números y puntos/comas
                    clean_price = re.sub(r'[^\d,.]', '', raw_price).replace(',', '.')
                    try:
                        precio = float(clean_price) if clean_price else 0.0
                    except:
                        precio = 0.0

                    # Guardar en DB
                    img_path = f"{IMG_DIR}/{sku}.png"
                    
                    # Si hay imágenes en esta página, intentamos asociar la primera encontrada al primer SKU
                    # (Esto es una aproximación, los PDFs no vinculan celda con imagen directamente)
                    if image_list and not os.path.exists(img_path):
                        xref = image_list[0][0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        with open(img_path, "wb") as f:
                            f.write(image_bytes)

                    conn.execute("""INSERT INTO productos (sku, descripcion, precio, imagen_path) 
                                 VALUES (?, ?, ?, ?) ON CONFLICT(sku) DO UPDATE SET 
                                 descripcion=excluded.descripcion, precio=excluded.precio""",
                                 (sku, desc, precio, img_path))
                    productos_leidos += 1
    
    conn.commit()
    return productos_leidos

# --- INTERFAZ ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth, st.session_state.user = True, {"id": res[0], "rol": res[3]}
            st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["🛒 Catálogo", "🧾 Carrito", "📁 Cargar PDF"])

    if menu == "🛒 Catálogo":
        st.title("🛒 Catálogo de Productos")
        prods = pd.read_sql("SELECT * FROM productos", get_connection())
        
        if prods.empty:
            st.info("Carga un PDF para activar el catálogo.")
        else:
            cols = st.columns(4)
            for idx, row in prods.iterrows():
                with cols[idx % 4]:
                    # Mostrar imagen si existe
                    img_src = row['imagen_path'] if os.path.exists(row['imagen_path']) else "https://via.placeholder.com/150"
                    
                    st.markdown(f"""
                    <div class="product-card">
                        <img src="{img_src}" class="product-img">
                        <div class="product-name"><b>{row['descripcion']}</b></div>
                        <div class="price-tag">$ {row['precio']:.2f}</div>
                        <div style="font-size:10px; color:gray;">SKU: {row['sku']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button("Añadir", key=f"add_{row['sku']}"):
                        conn = get_connection()
                        conn.execute("INSERT OR REPLACE INTO carrito VALUES (?,?,?,?,?)",
                                    (st.session_state.user['id'], row['sku'], row['descripcion'], row['precio'], 1))
                        conn.commit()
                        st.success(f"Añadido {row['sku']}")

    elif menu == "📁 Cargar PDF":
        st.title("📁 Importación Maestra")
        file = st.file_uploader("Sube tu PDF (debe tener imágenes y columnas SKU, Descripción, BCV)", type="pdf")
        if file and st.button("🚀 Extraer Todo"):
            with st.spinner("Extrayendo texto e imágenes..."):
                total = procesar_pdf_avanzado(file)
                st.success(f"¡Listo! Se procesaron {total} productos e imágenes.")
                st.rerun()