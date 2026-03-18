import streamlit as st
import pandas as pd
import sqlite3
import os
import re
import fitz  # PyMuPDF
import io
import time
from datetime import datetime

# --- CONFIGURACIÓN DE RUTAS SEGURA ---
DB_NAME = "color_insumos_v31.db"
# Usamos una ruta relativa al directorio actual del script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "productos")

# Crear directorios si no existen antes de cualquier operación
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos Pro", layout="wide")

# --- ESTILOS CSS ---
st.markdown("""
    <style>
    .product-card {
        background-color: white;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #eee;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    .product-img {
        width: 100%;
        height: 150px;
        object-fit: contain;
        border-radius: 8px;
    }
    .price-tag { color: #1a73e8; font-size: 22px; font-weight: bold; margin: 10px 0; }
    .product-name { font-weight: 600; font-size: 14px; height: 45px; overflow: hidden; }
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

# --- MOTOR DE EXTRACCIÓN (TEXTO + IMÁGENES) ---
def procesar_pdf_avanzado(uploaded_file):
    # Guardar temporalmente el archivo para que fitz lo lea
    with open("temp.pdf", "wb") as f:
        f.write(uploaded_file.getbuffer())
    
    doc = fitz.open("temp.pdf")
    conn = get_connection()
    productos_leidos = 0

    for page_index in range(len(doc)):
        page = doc[page_index]
        # Extraer imágenes de la página
        image_list = page.get_images(full=True)
        
        # Intentar extraer tablas
        tabs = page.find_tables()
        if tabs:
            for tab in tabs:
                df = tab.to_pandas()
                df.columns = [str(c).upper().strip() for c in df.columns]
                
                # Mapeo de columnas: SKU (0), Desc (1), BCV (Busca por nombre)
                col_bcv = next((i for i, c in enumerate(df.columns) if "BCV" in c), 2)

                for _, row in df.iterrows():
                    sku = str(row.iloc[0]).strip()
                    if not sku or sku == "None" or len(sku) < 2: continue
                    
                    desc = str(row.iloc[1]).strip()
                    
                    # LIMPIEZA DE PRECIO RADICAL (Para evitar el 0)
                    raw_price = str(row.iloc[col_bcv])
                    # Eliminamos todo lo que no sea dígito, coma o punto
                    clean_price = re.sub(r'[^\d,.]', '', raw_price).replace(',', '.')
                    try:
                        # Si hay varios puntos (ej 1.200.50), dejamos solo el último
                        if clean_price.count('.') > 1:
                            parts = clean_price.split('.')
                            clean_price = "".join(parts[:-1]) + "." + parts[-1]
                        precio = float(clean_price)
                    except:
                        precio = 0.0

                    # Manejo de Imagen
                    img_filename = f"{sku}.png"
                    img_path_full = os.path.join(IMG_DIR, img_filename)
                    # Ruta relativa para mostrar en Streamlit
                    img_rel_path = f"static/productos/{img_filename}"
                    
                    if image_list and not os.path.exists(img_path_full):
                        try:
                            xref = image_list[0][0]
                            base_image = doc.extract_image(xref)
                            with open(img_path_full, "wb") as f_img:
                                f_img.write(base_image["image"])
                        except:
                            img_rel_path = None # Fallback si falla la extracción

                    conn.execute("""INSERT INTO productos (sku, descripcion, precio, imagen_path) 
                                 VALUES (?, ?, ?, ?) ON CONFLICT(sku) DO UPDATE SET 
                                 descripcion=excluded.descripcion, precio=excluded.precio, imagen_path=excluded.imagen_path""",
                                 (sku, desc, precio, img_rel_path))
                    productos_leidos += 1
    
    conn.commit()
    doc.close()
    if os.path.exists("temp.pdf"): os.remove("temp.pdf")
    return productos_leidos

# --- INTERFAZ PRINCIPAL ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ Sistema Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth, st.session_state.user = True, {"id": res[0], "rol": res[3]}
            st.rerun()
        else: st.error("Clave incorrecta")
else:
    menu = st.sidebar.radio("Menú", ["🛒 Catálogo", "🧾 Carrito", "📁 Cargar PDF", "🚪 Salir"])

    if menu == "🚪 Salir":
        st.session_state.auth = False
        st.rerun()

    elif menu == "🛒 Catálogo":
        st.title("🛍️ Catálogo de Insumos")
        prods = pd.read_sql("SELECT * FROM productos", get_connection())
        
        if prods.empty:
            st.info("Catálogo vacío. Carga un PDF para empezar.")
        else:
            cols = st.columns(4)
            for idx, row in prods.iterrows():
                with cols[idx % 4]:
                    img_url = row['imagen_path'] if row['imagen_path'] and os.path.exists(row['imagen_path']) else "https://via.placeholder.com/150?text=Insumo"
                    
                    st.markdown(f"""
                    <div class="product-card">
                        <img src="{img_url}" class="product-img">
                        <div class="product-name">{row['descripcion']}</div>
                        <div class="price-tag">$ {row['precio']:.2f}</div>
                        <div style="font-size:10px; color:gray;">SKU: {row['sku']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button("Añadir 🛒", key=f"add_{row['sku']}", use_container_width=True):
                        conn = get_connection()
                        conn.execute("INSERT OR REPLACE INTO carrito VALUES (?,?,?,?,?)",
                                    (st.session_state.user['id'], row['sku'], row['descripcion'], row['precio'], 1))
                        conn.commit()
                        st.toast(f"✅ {row['sku']} añadido")

    # --- CARGA PDF (MOTOR ACTUALIZADO) ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo con Imágenes y Precios")
        st.warning("Asegúrese de que el PDF tenga las columnas: SKU, IMAGEN, DESCRIPCION, PRECIO DIVISAS, PRECIO BCV")
        
        f = st.file_uploader("Subir PDF de Inventario", type="pdf")
        
        if f and st.button("🚀 Iniciar Procesamiento Maestro"):
            with st.spinner("Leyendo tablas y extrayendo imágenes..."):
                try:
                    # Guardar temporalmente para que fitz lo procese
                    with open("temp_carga.pdf", "wb") as tmp:
                        tmp.write(f.getbuffer())
                    
                    doc = fitz.open("temp_carga.pdf")
                    conn = get_connection()
                    productos_nuevos = 0

                    for page_index in range(len(doc)):
                        page = doc[page_index]
                        img_list = page.get_images(full=True)
                        tabs = page.find_tables()
                        
                        if tabs:
                            for tab in tabs:
                                df_pdf = tab.to_pandas()
                                # Estandarizar encabezados
                                df_pdf.columns = [str(c).upper().strip() for c in df_pdf.columns]
                                
                                # Mapeo dinámico de columnas
                                col_sku = 0 # Usualmente la primera
                                col_desc = 2 # Según tu orden: SKU(0), IMG(1), DESC(2)
                                col_bcv = next((i for i, c in enumerate(df_pdf.columns) if "BCV" in c), 4)

                                for row_idx, row in df_pdf.iterrows():
                                    sku = str(row.iloc[col_sku]).strip()
                                    if not sku or sku == "None" or len(sku) < 2: continue
                                    
                                    descripcion = str(row.iloc[col_desc]).strip()
                                    
                                    # Limpieza de precio (Evita el 0.0)
                                    raw_price = str(row.iloc[col_bcv])
                                    clean_p = re.sub(r'[^\d,.]', '', raw_price).replace(',', '.')
                                    try:
                                        # Manejo de puntos de miles (ej: 1.250.00 -> 1250.00)
                                        if clean_p.count('.') > 1:
                                            parts = clean_p.split('.')
                                            clean_p = "".join(parts[:-1]) + "." + parts[-1]
                                        precio = float(clean_p)
                                    except:
                                        precio = 0.0

                                    # Extracción de Imagen relacionada
                                    foto_final = ""
                                    if img_list:
                                        try:
                                            # Intentamos tomar la imagen correspondiente a la fila
                                            xref = img_list[row_idx][0] if row_idx < len(img_list) else img_list[0][0]
                                            base_img = doc.extract_image(xref)
                                            foto_path = os.path.join(IMG_DIR, f"{sku}.png")
                                            with open(foto_path, "wb") as f_img:
                                                f_img.write(base_img["image"])
                                            foto_final = foto_path
                                        except: pass

                                    # Clasificación automática por nombre
                                    categoria = obtener_categoria(sku, descripcion)

                                    conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                                 VALUES (?, ?, ?, ?, ?) ON CONFLICT(sku) DO UPDATE SET 
                                                 descripcion=excluded.descripcion, precio=excluded.precio, 
                                                 foto_path=excluded.foto_path""", 
                                                 (sku, descripcion, precio, categoria, foto_final))
                                    productos_nuevos += 1
                    
                    conn.commit()
                    doc.close()
                    os.remove("temp_carga.pdf")
                    st.cache_data.clear() # Limpiar caché para ver cambios
                    st.success(f"✅ ¡Catálogo Actualizado! Se procesaron {productos_nuevos} productos.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error crítico al procesar: {e}")