import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import time
import re
from datetime import datetime

# --- CONFIGURACIÓN DE RUTAS ---
# Usamos v10 para forzar la creación de la tabla con PRIMARY KEY
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")

if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    # SKU debe ser PRIMARY KEY para que funcione el ON CONFLICT
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

# --- FUNCIONES DE LIMPIEZA ---
def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    # Elimina todo lo que no sea número, coma o punto
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        # Manejo de múltiples puntos (ej: 1.250.00)
        if clean.count('.') > 1:
            parts = clean.split('.')
            clean = "".join(parts[:-1]) + "." + parts[-1]
        return float(clean)
    except: return 0.0

def obtener_categoria(sku, descripcion):
    d = str(descripcion).upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PUZZLE"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "SACAPUNTA"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "SOBRE"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "PEGA", "SILICON", "REGLA"]): return "✂️ MANUALIDADES"
    return "📦 OTROS"

@st.cache_data(ttl=60)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

# --- INTERFAZ ---
@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        img_path = row['foto_path']
        if img_path and os.path.exists(img_path):
            st.image(img_path, use_container_width=True)
        else:
            st.image("https://via.placeholder.com/150?text=No+Disponible", use_container_width=True)
        
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:80])
        
        cant = st.number_input("Cantidad", 1, 500, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("🛒 Añadir", key=f"btn_{row['sku']}_{idx}", use_container_width=True):
            user_id = st.session_state.user_data['user']
            if user_id not in st.session_state.carritos: st.session_state.carritos[user_id] = {}
            st.session_state.carritos[user_id][row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast(f"✅ Añadido: {row['sku']}")

# --- APP ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'carritos' not in st.session_state: st.session_state.carritos = {}

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Acceso incorrecto")
else:
    user = st.session_state.user_data
    carrito_actual = st.session_state.carritos.get(user['user'], {})
    
    with st.sidebar:
        st.header(f"Hola, {user['nombre']}")
        menu = st.radio("Menú", ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_actual)})", "📁 Cargar PDF", "👥 Clientes"])
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA (ULTRA RÁPIDO Y CORREGIDO) ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo Color Insumos")
        
        # --- BUSCADOR Y FILTROS ---
        with st.container(border=True):
            col_busq, col_cat, col_reset = st.columns([2, 1, 0.5])
            
            with col_busq:
                # Usamos una clave simple. Si queremos resetear, Streamlit lo maneja mejor con el botón.
                busq = st.text_input("🔍 Buscar por SKU o Descripción...", placeholder="Escribe algo para buscar...")
            
            with col_cat:
                # Obtenemos categorías solo para el selector
                conn = get_connection()
                res_cats = conn.execute("SELECT DISTINCT categoria FROM productos").fetchall()
                lista_cats = ["Seleccionar Categoría"] + sorted([r[0] for r in res_cats])
                cat_sel = st.selectbox("📂 Filtrar por Departamento", lista_cats)
            
            with col_reset:
                st.write(" ")
                if st.button("🔄 Limpiar", use_container_width=True):
                    st.rerun()

        st.divider()

        # --- LÓGICA DE VISUALIZACIÓN ---
        # Si no hay búsqueda ni categoría seleccionada, mostramos bienvenida
        if not busq and (cat_sel == "Seleccionar Categoría"):
            st.markdown("""
                ### 👋 ¡Bienvenido al Catálogo Virtual!
                Para comenzar a armar tu pedido, utiliza las herramientas de arriba:
                1. **Escribe** el nombre de un producto o su SKU.
                2. **O selecciona** una categoría específica para ver los artículos disponibles.
                
                *Esto hace que la aplicación cargue más rápido y ahorres datos.*
            """)
        else:
            # Solo cargamos los datos de la DB si hay algo que buscar
            df = cargar_catalogo()
            df_filtrado = df.copy()
            
            if busq:
                df_filtrado = df_filtrado[
                    df_filtrado['descripcion'].str.contains(busq, case=False) | 
                    df_filtrado['sku'].str.contains(busq, case=False)
                ]
            
            if cat_sel != "Seleccionar Categoría":
                df_filtrado = df_filtrado[df_filtrado['categoria'] == cat_sel]

            if df_filtrado.empty:
                st.warning("No encontramos coincidencias. Intenta con otra palabra.")
            else:
                st.caption(f"Resultados encontrados: {len(df_filtrado)}")
                cols = st.columns(4)
                for i, (_, row) in enumerate(df_filtrado.iterrows()):
                    with cols[i % 4]:
                        card_producto(row, i)

    elif menu == "📁 Cargar PDF":
        st.title("📁 Carga Masiva (Lista POINTER)")
        if user['rol'] != 'admin': st.error("No tienes permisos.")
        else:
            archivo = st.file_uploader("Sube el PDF de Pointer", type="pdf")
            if archivo and st.button("🚀 Iniciar Procesamiento"):
                with st.spinner("Procesando tablas e imágenes..."):
                    with open("temp_pointer.pdf", "wb") as t: t.write(archivo.getbuffer())
                    doc = fitz.open("temp_pointer.pdf")
                    conn = get_connection()
                    count = 0
                    
                    for page in doc:
                        imgs = page.get_images(full=True)
                        tabs = page.find_tables()
                        if tabs:
                            for tab in tabs:
                                df_p = tab.to_pandas()
                                # Limpiar nombres de columnas
                                df_p.columns = [str(c).upper().strip() for c in df_p.columns]
                                
                                # Buscamos la columna de PRECIO BCV (normalmente la 4ta)
                                col_bcv = next((i for i, c in enumerate(df_p.columns) if "BCV" in c), 4)

                                for row_idx, row in df_p.iterrows():
                                    sku = str(row.iloc[0]).strip().replace("\n", "")
                                    if len(sku) < 3 or sku.upper() == "SKU": continue
                                    
                                    desc = str(row.iloc[2]).strip().replace("\n", " ")
                                    precio = limpiar_precio(row.iloc[col_bcv])
                                    
                                    # Extracción de Imagen
                                    f_path = ""
                                    try:
                                        if imgs and row_idx < len(imgs):
                                            xref = imgs[row_idx][0]
                                            pix = fitz.Pixmap(doc, xref)
                                            if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                                            f_name = f"{sku}.png"
                                            f_path = os.path.join(IMG_DIR, f_name)
                                            pix.save(f_path)
                                    except: pass
                                    
                                    cat = obtener_categoria(sku, desc)
                                    conn.execute("""
                                        INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                        VALUES (?, ?, ?, ?, ?)
                                        ON CONFLICT(sku) DO UPDATE SET 
                                            descripcion=excluded.descripcion, 
                                            precio=excluded.precio, 
                                            foto_path=excluded.foto_path
                                    """, (sku, desc, precio, cat, f_path))
                                    count += 1
                    conn.commit()
                    doc.close()
                    os.remove("temp_pointer.pdf")
                    st.cache_data.clear()
                    st.success(f"✅ Se cargaron {count} productos."); time.sleep(1); st.rerun()

    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        if user['rol'] == 'admin':
            clientes = pd.read_sql("SELECT username, nombre, telefono FROM usuarios WHERE rol='cliente'", get_connection())
            st.dataframe(clientes, use_container_width=True)
            with st.form("nuevo"):
                st.write("Registrar nuevo cliente")
                c1, c2 = st.columns(2)
                un = c1.text_input("Email/Usuario"); pn = c2.text_input("Clave")
                nn = c1.text_input("Nombre Empresa"); tn = c2.text_input("Teléfono")
                if st.form_submit_button("Crear"):
                    get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (un, pn, nn, 'cliente', '', tn))
                    get_connection().commit(); st.rerun()