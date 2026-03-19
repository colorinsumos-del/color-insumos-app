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
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol, direccion, telefono) VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

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
    # Extraer solo números y puntos/comas
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
    subtotal_live = sum(item['p'] * item['c'] for item in carrito_usuario.values())
    desc_live = subtotal_live * 0.10 if subtotal_live > 100 else 0.0
    total_live = subtotal_live - desc_live

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        st.write(f"Total: **${total_live:.2f}**")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Usuarios"]
        menu = st.radio("Menú", opc)
        if st.button("Salir"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        df = cargar_catalogo()
        busq = st.text_input("🔍 Buscar SKU o Producto...")
        if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
        
        for i, row in df.iterrows():
            item_carrito = carrito_usuario.get(row['sku'])
            with st.container(border=(item_carrito is not None)):
                c1, c2, c3, c4, c5, c6 = st.columns([1, 1.2, 4, 1, 1, 1])
                with c1:
                    try:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            st.image(row['foto_path'], width=80)
                        else: st.image("https://via.placeholder.com/80?text=SIN+FOTO", width=80)
                    except: st.image("https://via.placeholder.com/80?text=ERROR", width=80)
                c2.write(f"**{row['sku']}**")
                c3.write(row['descripcion'])
                c4.write(f"${row['precio']:.2f}")
                cant = c5.number_input("Cant", 1, 500, int(item_carrito['c']) if item_carrito else 1, key=f"q_{row['sku']}")
                if item_carrito:
                    if c6.button("🗑️", key=f"del_{row['sku']}"):
                        del carrito_usuario[row['sku']]; guardar_carrito_db(uid, carrito_usuario); st.rerun()
                else:
                    if c6.button("🛒", key=f"add_{row['sku']}"):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO FORTALECIDO: CARGAR PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importador Maestro de Inventario")
        st.info("Este módulo procesará el SKU, Descripción, Precio e Imágenes automáticamente.")
        f = st.file_uploader("Subir PDF de Pointer", type="pdf")
        
        if f and st.button("🚀 Iniciar Procesamiento Profundo"):
            with st.status("Analizando estructura del PDF...") as status:
                doc = fitz.open(stream=f.read(), filetype="pdf")
                conn = get_connection()
                
                for page in doc:
                    # 1. Extraer todas las palabras con sus coordenadas
                    words = page.get_text("words") 
                    # 2. Extraer metadatos de imágenes en la página
                    img_list = page.get_image_info(hashes=True)
                    
                    # Usamos find_tables como base, pero con refuerzo manual
                    tabs = page.find_tables()
                    if tabs:
                        for tab in tabs:
                            df_tab = tab.to_pandas()
                            for row_idx, row in df_tab.iterrows():
                                try:
                                    # Intentar capturar datos por posición de columna
                                    sku = str(row.iloc[0]).strip()
                                    desc = str(row.iloc[2]).strip()
                                    precio = limpiar_precio(row.iloc[4]) # Precio Divisas suele ser la col 4 o 5
                                    
                                    if len(sku) > 3 and precio > 0:
                                        foto_path = ""
                                        # Buscar imagen en la celda de la columna "IMAGEN" (col index 1)
                                        celda_img = tab.rows[row_idx].cells[1]
                                        if celda_img:
                                            # Comparar coordenadas de cada imagen con la celda
                                            rect_celda = fitz.Rect(celda_img)
                                            for img_info in img_list:
                                                if rect_celda.intersects(fitz.Rect(img_info['bbox'])):
                                                    pix = fitz.Pixmap(doc, img_info['xref'])
                                                    # Forzar a RGB si es necesario
                                                    if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                                                    
                                                    p_name = f"{sku.replace('/','_')}.png"
                                                    p_path = os.path.join(IMG_DIR, p_name)
                                                    pix.save(p_path)
                                                    foto_path = p_path
                                                    break
                                        
                                        # Guardar o actualizar en DB
                                        conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                                     VALUES (?,?,?,?,?) ON CONFLICT(sku) 
                                                     DO UPDATE SET precio=excluded.precio, 
                                                     descripcion=excluded.descripcion,
                                                     foto_path=CASE WHEN excluded.foto_path != '' THEN excluded.foto_path ELSE foto_path END""", 
                                                     (sku, desc, precio, "General", foto_path))
                                except: continue
                conn.commit()
                status.update(label="¡Inventario cargado con éxito!", state="complete")
            st.success("Se han procesado todos los productos detectados.")
            st.rerun()

    # --- MÓDULO USUARIOS (SIN CAMBIOS) ---
    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Usuarios")
        t1, t2 = st.tabs(["Lista", "Nuevo"])
        with t1:
            df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
            for _, u_row in df_u.iterrows():
                with st.expander(f"👤 {u_row['nombre']}"):
                    with st.form(f"fe_{u_row['username']}"):
                        en = st.text_input("Nombre", value=u_row['nombre'])
                        ec = st.text_input("Clave", value=u_row['password'])
                        if st.form_submit_button("Guardar"):
                            get_connection().execute("UPDATE usuarios SET nombre=?, password=? WHERE username=?", (en, ec, u_row['username']))
                            get_connection().commit(); st.rerun()
        with t2:
            with st.form("nu"):
                un, pw, nm = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
                if st.form_submit_button("Crear"):
                    get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (un, pw, nm, 'cliente'))
                    get_connection().commit(); st.rerun()

    # --- CARRITO Y VENTAS (SIN CAMBIOS) ---
    elif "🛒" in menu:
        st.title("🛒 Carrito")
        if not carrito_usuario: st.info("Vacío")
        else:
            for s, i in list(carrito_usuario.items()):
                st.write(f"**{s}** - {i['desc']} (${i['p']})")
            if st.button("Finalizar Pedido"):
                get_connection().execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, total, status) VALUES (?,?,?,?,?,?)",
                                         (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y"), json.dumps(list(carrito_usuario.values())), total_live, "Pendiente"))
                guardar_carrito_db(uid, {}); get_connection().commit(); st.success("Listo"); st.rerun()

    elif "Ventas" in menu or "Pedidos" in menu:
        st.title("📜 Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        st.dataframe(df_p)