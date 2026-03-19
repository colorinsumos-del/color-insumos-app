import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import re
import shutil
from datetime import datetime

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")

# Carpetas de importación masiva (GitHub)
CARPETAS_IMPORTAR = [
    os.path.join(BASE_DIR, "importar_fotos"),
    os.path.join(BASE_DIR, "importar_fotos2")
]

# Crear estructura de carpetas
os.makedirs(IMG_DIR, exist_ok=True)
for carpeta in CARPETAS_IMPORTAR:
    os.makedirs(carpeta, exist_ok=True)

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
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try: return float(clean)
    except: return 0.0

def guardar_carrito_db(username, carrito_dict):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carritos (username, data) VALUES (?, ?)", (username, json.dumps(carrito_dict)))
    conn.commit()

def cargar_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT data FROM carritos WHERE username=?", (username,)).fetchone()
    return json.loads(res[0]) if res else {}

# --- FUNCIÓN DE VINCULACIÓN MASIVA DE IMÁGENES ---
def vincular_imagenes_locales():
    conn = get_connection()
    exito = 0
    extensiones = ('.png', '.jpg', '.jpeg', '.webp')
    
    for ruta_carpeta in CARPETAS_IMPORTAR:
        if not os.path.exists(ruta_carpeta): continue
        archivos = os.listdir(ruta_carpeta)
        
        for archivo in archivos:
            if archivo.lower().endswith(extensiones):
                sku_archivo = os.path.splitext(archivo)[0].strip()
                # Verificar si el SKU existe en la DB
                existe = conn.execute("SELECT sku FROM productos WHERE sku = ?", (sku_archivo,)).fetchone()
                
                if existe:
                    ext = os.path.splitext(archivo)[1]
                    nombre_final = f"{re.sub(r'[\\\\/*?:\"<>|]', '_', sku_archivo)}{ext}"
                    ruta_destino = os.path.join(IMG_DIR, nombre_final)
                    
                    shutil.copy(os.path.join(ruta_carpeta, archivo), ruta_destino)
                    conn.execute("UPDATE productos SET foto_path = ? WHERE sku = ?", (ruta_destino, sku_archivo))
                    exito += 1
    conn.commit()
    return exito

# --- INTERFAZ ---
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
            opc += ["📊 Gestión Ventas", "📁 Cargar Catálogo", "🖼️ Vincular Fotos", "👥 Usuarios"]
        menu = st.radio("Menú Principal", opc)
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        df = pd.read_sql("SELECT * FROM productos", get_connection())
        busq = st.text_input("🔍 Buscar SKU o Producto...")
        if busq:
            df = df[df['descripcion'].str.contains(busq, case=False, na=False) | df['sku'].str.contains(busq, case=False, na=False)]
        
        for _, row in df.iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 3, 1, 1])
                with c1:
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], width=120)
                    else: st.image("https://via.placeholder.com/120?text=SIN+FOTO", width=120)
                c2.subheader(row['sku'])
                c2.write(row['descripcion'])
                c3.metric("Precio", f"${row['precio']:.2f}")
                cant = c4.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                if c4.button("Añadir", key=f"btn_{row['sku']}"):
                    carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                    guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO CARGAR PDF / EXCEL ---
    elif menu == "📁 Cargar Catálogo":
        st.title("📁 Importar Datos")
        tab1, tab2 = st.tabs(["📄 Cargar PDF", "Excel (Próximamente)"])
        
        with tab1:
            f = st.file_uploader("Subir PDF de Pointer", type="pdf")
            if f and st.button("🚀 Iniciar Extracción PDF"):
                doc = fitz.open(stream=f.read(), filetype="pdf")
                conn = get_connection()
                for page in doc:
                    tabs = page.find_tables()
                    for tab in tabs:
                        df_t = tab.to_pandas()
                        for _, row in df_t.iterrows():
                            try:
                                sku = str(row.iloc[0]).strip().replace('\n', '')
                                desc = str(row.iloc[2]).strip()
                                precio = limpiar_precio(row.iloc[4]) # Columna E
                                if len(sku) > 2 and precio > 0:
                                    conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, descripcion=excluded.descripcion", (sku, desc, precio, "General"))
                            except: continue
                conn.commit()
                st.success("¡Datos del PDF cargados! Ahora usa 'Vincular Fotos' para las imágenes.")

    # --- MÓDULO VINCULAR FOTOS (LAS 2 CARPETAS) ---
    elif menu == "🖼️ Vincular Fotos":
        st.title("🖼️ Vinculación Masiva")
        st.info(f"Escaneando carpetas: `importar_fotos` e `importar_fotos2`")
        if st.button("🔗 Cruzar Fotos con Productos"):
            total = vincular_imagenes_locales()
            st.success(f"✅ Se han vinculado {total} fotos exitosamente.")
            st.balloons()

    # --- OTROS MÓDULOS ---
    elif menu == "📊 Gestión Ventas":
        st.title("📊 Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        st.dataframe(df_p)

    elif menu == "👥 Usuarios":
        st.title("👥 Usuarios")
        df_u = pd.read_sql("SELECT username, nombre, rol FROM usuarios", get_connection())
        st.table(df_u)