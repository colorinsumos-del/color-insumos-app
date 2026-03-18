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

# --- FUNCIÓN DE EXTRACCIÓN MEJORADA (MÉTODO DE TABLAS BCV) ---
def procesar_pdf_bcv(file):
    conn = get_connection()
    productos_cargados = 0
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            # Extraemos las tablas de la página de forma estructurada
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                # Identificamos la columna "BCV" analizando las primeras filas
                col_bcv = -1
                for row_idx in range(min(3, len(table))): # Buscamos en las primeras 3 filas por si hay encabezados dobles
                    header = [str(cell).upper() if cell else "" for cell in table[row_idx]]
                    for i, cell in enumerate(header):
                        if "BCV" in cell:
                            col_bcv = i
                            break
                    if col_bcv != -1: break

                # Si encontramos la columna BCV, procesamos la tabla
                if col_bcv != -1:
                    for row in table:
                        if not row or len(row) <= col_bcv: continue
                        
                        # El SKU suele ser la primera columna (0)
                        sku = str(row[0]).strip() if row[0] else ""
                        
                        # Saltamos filas que sean encabezados o estén vacías
                        if not sku or sku.upper() in ["SKU", "CODIGO", "ITEM", "PRODUCTO"]:
                            continue
                        
                        # La descripción suele ser la segunda columna (1)
                        descripcion = str(row[1]).strip() if row[1] else ""
                        
                        # Extraemos el precio de la columna BCV detectada
                        precio_raw = str(row[col_bcv]).strip() if row[col_bcv] else ""
                        
                        # Limpiamos el precio: buscamos el patrón numérico (ej: 1.250,50)
                        precio_match = re.search(r'[\d.,]+', precio_raw)
                        if precio_match:
                            try:
                                # Convertimos formato latam (1.200,50) a float (1200.50)
                                p_str = precio_match.group(0).replace('.', '').replace(',', '.')
                                precio_final = float(p_str)
                                
                                conn.execute("""
                                    INSERT OR REPLACE INTO productos (sku, descripcion, precio, categoria) 
                                    VALUES (?, ?, ?, ?)
                                """, (sku, descripcion, precio_final, "General"))
                                productos_cargados += 1
                            except:
                                continue
    
    conn.commit()
    st.cache_data.clear() 
    return productos_cargados

# --- GENERADOR DE PDF CORREGIDO ---
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
        sku = str(item.get('SKU', 'N/A'))
        desc = str(item.get('Desc', ''))[:45]
        cant = str(item.get('Cant', '0'))
        sub = f"${item.get('Subtotal', 0):.2f}"
        pdf.cell(30, 8, sku, 1); pdf.cell(90, 8, desc, 1)
        pdf.cell(20, 8, cant, 1); pdf.cell(50, 8, sub, 1); pdf.ln()
    pdf.ln(5); pdf.set_font("helvetica", "B", 12)
    pdf.cell(190, 10, f"TOTAL FINAL: ${total:.2f}", ln=True, align="R")
    return bytes(pdf.output())

# --- BASE DE DATOS ---
def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT DEFAULT '', telefono TEXT DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio REAL, cantidad INTEGER, PRIMARY KEY (username, sku))''')
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

def guardar_item_carrito(username, row, cant):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carrito_items VALUES (?,?,?,?,?)", (username, row['sku'], row['descripcion'], row['precio'], cant))
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

# --- ESTILOS ---
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
            st.toast("✅ Añadido al carrito")
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
        else: st.error("Usuario o clave incorrectos")
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

    if "🛒" in menu or "Comprar" in menu:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar SKU...")
            cat_sel = c2.selectbox("Categoría", ["Seleccionar"] + sorted(df['categoria'].unique().tolist()))
            if busq or cat_sel != "Seleccionar":
                df_v = df.copy()
                if busq: df_v = df_v[df_v['sku'].str.contains(busq, case=False)]
                if cat_sel != "Seleccionar": df_v = df_v[df_v['categoria'] == cat_sel]
                cols = st.columns(4)
                for idx, row in df_v.reset_index().iterrows():
                    with cols[idx % 4]: card_producto(row, idx)
            else: st.info("👋 Selecciona una categoría o busca un SKU.")
        with t2:
            if not carrito_actual: st.info("Carrito vacío.")
            else:
                total = 0; resumen = []
                for sku, info in carrito_actual.items():
                    sub = info['p'] * info['c']; total += sub
                    st.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']}) = **${sub:.2f}**")
                    if st.button("🗑️", key=f"rm_{sku}"): eliminar_item_carrito(user['user'], sku); st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                st.divider(); st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", use_container_width=True, type="primary"):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    get_connection().commit(); limpiar_carrito(user['user']); st.success("¡Pedido enviado!"); time.sleep(1); st.rerun()

    elif menu == "📜 Mis Pedidos":
        st.title("📜 Historial de Pedidos")
        mis_peds = pd.read_sql("SELECT * FROM pedidos WHERE username=? ORDER BY id DESC", get_connection(), params=(user['user'],))
        for _, p in mis_peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} - Total: ${p['total']:.2f}"):
                st.table(pd.DataFrame(json.loads(p['items'])))

    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control Global de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 #{p['id']} - {p['username']}"):
                items_list = json.loads(p['items']); st.table(pd.DataFrame(items_list))
                c1, c2, c3 = st.columns(3)
                try:
                    pdf_bytes = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items_list, p['total'])
                    c1.download_button("📄 PDF", data=pdf_bytes, file_name=f"Pedido_{p['id']}.pdf", key=f"pdf_{p['id']}")
                except: c1.error("Error PDF")
                output_xl = io.BytesIO()
                with pd.ExcelWriter(output_xl, engine='openpyxl') as writer: pd.DataFrame(items_list).to_excel(writer, index=False)
                c2.download_button("📈 Excel", data=output_xl.getvalue(), file_name=f"Pedido_{p['id']}.xlsx", key=f"xl_{p['id']}")
                if c3.button("🗑️ Eliminar", key=f"del_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],)); get_connection().commit(); st.rerun()

    elif menu == "👥 Gestión Clientes":
        st.title("👥 Gestión de Clientes")
        t_l, t_n = st.tabs(["📝 Listado", "➕ Nuevo"])
        with t_l:
            conn = get_connection()
            df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin' ORDER BY nombre ASC", conn)
            for idx, row in df_u.iterrows():
                u_id = row['username']
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"**{row['nombre']}** (`{u_id}`) | Clave: `{row['password']}`")
                        st.write(f"Tel: {row['telefono']} | Dir: {row['direccion']}")
                    if c2.button("✏️ Editar", key=f"ed_{u_id}"): st.session_state[f"ea_{u_id}"] = True
                    if st.session_state.get(f"ea_{u_id}", False):
                        with st.form(f"f_{u_id}"):
                            nn, nt, nd, np = st.text_input("Nombre", row['nombre']), st.text_input("Tel", row['telefono']), st.text_area("Dir", row['direccion']), st.text_input("Clave", row['password'])
                            if st.form_submit_button("Guardar"):
                                conn.execute("UPDATE usuarios SET nombre=?, telefono=?, direccion=?, password=? WHERE username=?", (nn, nt, nd, np, u_id))
                                conn.commit(); st.session_state[f"ea_{u_id}"] = False; st.rerun()
        with t_n:
            with st.form("new_c"):
                nu, np, nn = st.text_input("ID/Email"), st.text_input("Clave"), st.text_input("Nombre")
                if st.form_submit_button("Registrar"):
                    try:
                        get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (nu, np, nn, 'cliente'))
                        get_connection().commit(); st.success("Creado"); st.rerun()
                    except: st.error("Error: Usuario ya existe")

    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo (Precio BCV)")
        st.info("Sube el PDF. El sistema buscará la columna **BCV** en las tablas para actualizar los precios.")
        f = st.file_uploader("Seleccionar archivo PDF", type="pdf")
        if f is not None:
            if st.button("🚀 Iniciar Procesamiento de PDF", use_container_width=True, type="primary"):
                with st.spinner("Analizando tablas y detectando columna BCV..."):
                    cantidad = procesar_pdf_bcv(f)
                    if cantidad > 0:
                        st.success(f"✅ ¡Éxito! Se cargaron/actualizaron {cantidad} productos."); time.sleep(2); st.rerun()
                    else: st.error("No se detectó la columna 'BCV'. Verifica el formato del PDF.")