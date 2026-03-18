import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import time
import re
from datetime import datetime

# --- CONFIGURACIÓN ---
# Cambiamos el nombre de la DB para resetear el esquema erróneo
DB_NAME = "catalogo_color_v4.db" 
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
    # CRÍTICO: SKU debe ser PRIMARY KEY para que ON CONFLICT funcione
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Usuario administrador
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Oficina Central', '04126901346'))
    conn.commit()

# --- ESTILOS ---
st.markdown("""
    <style>
        .product-card { background-color: white; padding: 15px; border-radius: 12px; border: 1px solid #eee; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px; }
        .product-img { width: 100%; height: 160px; object-fit: contain; border-radius: 8px; }
        .price-tag { color: #1a73e8; font-size: 24px; font-weight: bold; margin: 10px 0; }
    </style>
""", unsafe_allow_html=True)

# --- FUNCIONES AUXILIARES ---
def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        if clean.count('.') > 1:
            parts = clean.split('.')
            clean = "".join(parts[:-1]) + "." + parts[-1]
        return float(clean)
    except: return 0.0

def obtener_categoria(sku, descripcion):
    d = str(descripcion).upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA"]): return "🧩 JUEGOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA"]): return "📄 PAPELERÍA"
    return "📦 VARIOS"

@st.cache_data(ttl=300)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        img = row['foto_path']
        if img and os.path.exists(img): st.image(img, use_container_width=True)
        else: st.image("https://via.placeholder.com/150?text=Sin+Imagen", use_container_width=True)
        
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:70])
        
        cant = st.number_input("Cantidad", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            user_id = st.session_state.user_data['user']
            if user_id not in st.session_state.carritos: st.session_state.carritos[user_id] = {}
            st.session_state.carritos[user_id][row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast(f"✅ Añadido: {row['sku']}")
            time.sleep(0.5); st.rerun()

# --- APP PRINCIPAL ---
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
        else: st.error("Acceso denegado")
else:
    user = st.session_state.user_data
    carrito_actual = st.session_state.carritos.get(user['user'], {})
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        menu = st.radio("Menú", ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_actual)})", "📁 Cargar PDF", "👥 Clientes"])
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Insumos")
        df = cargar_catalogo()
        if df.empty: st.info("Carga un PDF para ver productos.")
        else:
            busq = st.text_input("🔍 Buscar...")
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            
            for cat in sorted(df['categoria'].unique()):
                with st.expander(cat, expanded=True):
                    sub = df[df['categoria'] == cat].reset_index()
                    cols = st.columns(4)
                    for i, row in sub.iterrows():
                        with cols[i % 4]: card_producto(row, i)

    elif "🛒" in menu:
        st.title("🛒 Tu Carrito")
        if not carrito_actual: st.warning("Vacío")
        else:
            total = 0
            items_list = []
            for sku, info in list(carrito_actual.items()):
                sub = info['p'] * info['c']
                total += sub
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"**{sku}** - {info['desc']}")
                    c2.write(f"${sub:.2f}")
                    if c3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[user['user']][sku]
                        st.rerun()
                items_list.append({"SKU": sku, "Cant": info['c'], "Sub": sub})
            
            st.divider()
            divisas = st.toggle("Pago en Divisas (-30%)")
            final = total * 0.7 if divisas else (total * 0.9 if total > 100 else total)
            st.write(f"### Total: ${final:.2f}")
            if st.button("🚀 Confirmar Pedido", use_container_width=True, type="primary"):
                get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                             (user['user'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(items_list), final, "Pendiente"))
                get_connection().commit()
                st.session_state.carritos[user['user']] = {}
                st.success("Pedido enviado"); time.sleep(1); st.rerun()

    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario")
        if user['rol'] != 'admin': st.error("Solo Admin")
        else:
            f = st.file_uploader("Subir PDF", type="pdf")
            if f and st.button("Procesar"):
                with st.spinner("Procesando..."):
                    with open("temp.pdf", "wb") as tmp: tmp.write(f.getbuffer())
                    doc = fitz.open("temp.pdf")
                    conn = get_connection()
                    count = 0
                    for page in doc:
                        imgs = page.get_images(full=True)
                        tabs = page.find_tables()
                        if tabs:
                            for tab in tabs:
                                df_p = tab.to_pandas()
                                col_bcv = next((i for i, c in enumerate(df_p.columns) if "BCV" in str(c).upper()), 4)
                                for row_idx, row in df_p.iterrows():
                                    sku = str(row.iloc[0]).strip()
                                    if len(sku) < 2 or sku.upper() == "SKU": continue
                                    
                                    desc = str(row.iloc[2]).strip()
                                    precio = limpiar_precio(row.iloc[col_bcv])
                                    
                                    # Extracción de Imagen con corrección de color
                                    f_path = ""
                                    try:
                                        if imgs and row_idx < len(imgs):
                                            xref = imgs[row_idx][0]
                                            pix = fitz.Pixmap(doc, xref)
                                            # Convertir a RGB si es CMYK para evitar errores de guardado
                                            if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                                            f_path = os.path.join(IMG_DIR, f"{sku}.png")
                                            pix.save(f_path)
                                    except: pass
                                    
                                    cat = obtener_categoria(sku, desc)
                                    # SQL CORREGIDO: Columnas explícitas y SKU como PK
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
                    st.success(f"Cargados {count} productos"); st.cache_data.clear(); time.sleep(1); st.rerun()

    elif menu == "👥 Clientes":
        st.title("Gestión de Clientes")
        if user['rol'] == 'admin':
            clientes = pd.read_sql("SELECT username, nombre, telefono FROM usuarios WHERE rol='cliente'", get_connection())
            st.dataframe(clientes, use_container_width=True)
            with st.form("n_c"):
                c1, c2 = st.columns(2)
                u_n = c1.text_input("Usuario/Email"); p_n = c2.text_input("Clave")
                nom_n = c1.text_input("Nombre"); tel_n = c2.text_input("Teléfono")
                if st.form_submit_button("Registrar"):
                    get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (u_n, p_n, nom_n, 'cliente', '', tel_n))
                    get_connection().commit(); st.rerun()