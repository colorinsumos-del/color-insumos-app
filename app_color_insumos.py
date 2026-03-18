import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import json
import time
import re
import pdfplumber
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- FUNCIÓN DE EXTRACCIÓN (CALIBRADA PARA 'PRECIO BCV') ---
def procesar_pdf_bcv(file):
    conn = get_connection()
    productos_cargados = 0
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                # Buscamos la columna que contenga "PRECIO BCV"
                col_bcv = -1
                for row_idx in range(min(5, len(table))):
                    row_cells = [str(c).upper() if c else "" for c in table[row_idx]]
                    for i, cell in enumerate(row_cells):
                        if "PRECIO BCV" in cell or "BCV" in cell:
                            col_bcv = i
                            break
                    if col_bcv != -1: break

                if col_bcv != -1:
                    for row in table:
                        if not row or len(row) <= col_bcv: continue
                        
                        sku = str(row[0]).strip() if row[0] else ""
                        # Filtro para saltar encabezados
                        if not sku or sku.upper() in ["SKU", "CODIGO", "ITEM", "PRODUCTO", "PRECIO BCV"]:
                            continue
                        
                        descripcion = str(row[1]).strip() if row[1] else ""
                        precio_raw = str(row[col_bcv]).strip() if row[col_bcv] else ""
                        
                        # Limpieza de precio para formatos 1.250,50 o 1250,50
                        precio_match = re.search(r'[\d.,]+', precio_raw)
                        if precio_match:
                            try:
                                p_str = precio_match.group(0)
                                # Convertir formato visual a número real
                                if "," in p_str and "." in p_str:
                                    if p_str.rfind(",") > p_str.rfind("."): 
                                        p_str = p_str.replace(".", "").replace(",", ".")
                                    else:
                                        p_str = p_str.replace(",", "")
                                elif "," in p_str:
                                    p_str = p_str.replace(",", ".")
                                
                                precio_final = float(p_str)
                                
                                # INSERT OR REPLACE actualiza si el SKU ya existe
                                conn.execute("""
                                    INSERT OR REPLACE INTO productos (sku, descripcion, precio, categoria) 
                                    VALUES (?, ?, ?, 'General')
                                """, (sku, descripcion, precio_final))
                                productos_cargados += 1
                            except:
                                continue
    
    conn.commit()
    st.cache_data.clear() 
    return productos_cargados

# --- GENERADOR DE PDF ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(190, 10, "COLOR INSUMOS - REPORTE DE PEDIDO", ln=True, align="C")
    pdf.set_font("helvetica", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 10, "SKU", 1); pdf.cell(90, 10, "Descripcion", 1)
    pdf.cell(20, 10, "Cant.", 1); pdf.cell(50, 10, "Subtotal", 1); pdf.ln()
    pdf.set_font("helvetica", "", 9)
    for item in items:
        pdf.cell(30, 8, str(item.get('SKU', 'N/A')), 1)
        pdf.cell(90, 8, str(item.get('Desc', ''))[:45], 1)
        pdf.cell(20, 8, str(item.get('Cant', '0')), 1)
        pdf.cell(50, 8, f"${item.get('Subtotal', 0):.2f}", 1); pdf.ln()
    pdf.ln(5); pdf.set_font("helvetica", "B", 12)
    pdf.cell(190, 10, f"TOTAL FINAL: ${total:.2f}", ln=True, align="R")
    return bytes(pdf.output())

# --- BASE DE DATOS (IMPORTANTE: SKU COMO PRIMARY KEY) ---
def init_db():
    conn = get_connection()
    # Definimos SKU como PRIMARY KEY para que el UPDATE funcione
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- FUNCIONES DE CARRITO ---
def guardar_item_carrito(username, row, cant):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carrito_items VALUES (?,?,?,?,?)", 
                 (username, row['sku'], row['descripcion'], row['precio'], cant))
    conn.commit()

def eliminar_item_carrito(username, sku):
    conn = get_connection()
    conn.execute("DELETE FROM carrito_items WHERE username=? AND sku=?", (username, sku))
    conn.commit()

def obtener_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT sku, descripcion, precio, cantidad FROM carrito_items WHERE username=?", (username,)).fetchall()
    return {item[0]: {"desc": item[1], "p": item[2], "c": item[3]} for item in res}

def limpiar_carrito(username):
    conn = get_connection()
    conn.execute("DELETE FROM carrito_items WHERE username=?", (username,))
    conn.commit()

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        .main .block-container { padding-top: 2rem !important; }
        header[data-testid="stHeader"] { z-index: 99; background: rgba(255,255,255,0.8); backdrop-filter: blur(10px); }
        .stButton button { border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.write(f"### ${row['precio']:.2f}")
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            guardar_item_carrito(st.session_state.user_data['user'], row, cant)
            st.toast("✅ Añadido")
            time.sleep(0.5); st.rerun()

# --- NAVEGACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u = st.text_input("Usuario (Email)").strip()
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u,)).fetchone()
        if res and res[1] == p:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Acceso denegado")
else:
    user = st.session_state.user_data
    carrito_actual = obtener_carrito_db(user['user'])
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav = [f"🛒 Carrito ({len(carrito_actual)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin':
            nav = ["🛒 Comprar", "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Gestión Clientes"]
        menu = st.radio("Menú", nav)

    # --- TIENDA ---
    if "🛒" in menu or "Comprar" in menu:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar SKU...")
            cat_sel = c2.selectbox("Categoría", ["Todos"] + sorted(df['categoria'].unique().tolist()))
            df_v = df.copy()
            if busq: df_v = df_v[df_v['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todos": df_v = df_v[df_v['categoria'] == cat_sel]
            cols = st.columns(4)
            for idx, row in df_v.reset_index().iterrows():
                with cols[idx % 4]: card_producto(row, idx)
        with t2:
            if not carrito_actual: st.info("Carrito vacío.")
            else:
                total = 0; resumen = []
                for sku, info in carrito_actual.items():
                    sub = info['p'] * info['c']; total += sub
                    st.write(f"**{sku}** - {info['desc']} (${sub:.2f})")
                    if st.button("🗑️", key=f"rm_{sku}"): eliminar_item_carrito(user['user'], sku); st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", use_container_width=True, type="primary"):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    get_connection().commit(); limpiar_carrito(user['user']); st.success("Enviado"); time.sleep(1); st.rerun()

    # --- PEDIDOS TOTALES ---
    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['username']}"):
                items = json.loads(p['items']); st.table(pd.DataFrame(items))
                pdf_b = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items, p['total'])
                st.download_button("📄 PDF", data=pdf_b, file_name=f"Pedido_{p['id']}.pdf", key=f"p_{p['id']}")

    # --- GESTIÓN CLIENTES ---
    elif menu == "👥 Gestión Clientes":
        st.title("👥 Listado de Clientes")
        df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin'", get_connection())
        st.table(df_u[['username', 'nombre', 'telefono']])

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Precios (PRECIO BCV)")
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("🚀 Procesar"):
            with st.spinner("Actualizando..."):
                cant = procesar_pdf_bcv(f)
                if cant > 0:
                    st.success(f"✅ Se actualizaron {cant} productos."); time.sleep(2); st.rerun()
                else: st.error("No se encontró la columna 'PRECIO BCV'.")