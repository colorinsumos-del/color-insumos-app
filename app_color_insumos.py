import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import json
import time
from datetime import datetime
from fpdf import FPDF

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

# --- GENERADOR DE PDF (CORRECCIÓN DEFINITIVA) ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    
    pdf.cell(190, 10, "COLOR INSUMOS - REPORTE DE PEDIDO", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 10, "SKU", 1)
    pdf.cell(90, 10, "Descripcion", 1)
    pdf.cell(20, 10, "Cant.", 1)
    pdf.cell(50, 10, "Subtotal", 1)
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    for item in items:
        desc = item.get('Desc', '')[:45]
        pdf.cell(30, 8, str(item.get('SKU', '')), 1)
        pdf.cell(90, 8, desc, 1)
        pdf.cell(20, 8, str(item.get('Cant', 0)), 1)
        pdf.cell(50, 8, f"${item.get('Subtotal', 0):.2f}", 1)
        pdf.ln()
    
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(190, 10, f"TOTAL FINAL: ${total:.2f}", ln=True, align="R")
    
    # IMPORTANTE: fpdf2 devuelve bytes directamente. No usar dest='S' ni .encode()
    return pdf.output()

# --- INICIALIZACIÓN DE BASE DE DATOS ---
def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT DEFAULT '', telefono TEXT DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')
    
    try:
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                     ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
        conn.commit()
    except: pass

# --- FUNCIONES DE CARRITO PERSISTENTE ---
def guardar_item_carrito(username, row, cant):
    conn = get_connection()
    conn.execute('''INSERT OR REPLACE INTO carrito_items (username, sku, descripcion, precio, cantidad) 
                 VALUES (?, ?, ?, ?, ?)''', (username, row['sku'], row['descripcion'], row['precio'], cant))
    conn.commit()

def eliminar_item_carrito(username, sku):
    conn = get_connection()
    conn.execute("DELETE FROM carrito_items WHERE username=? AND sku=?", (username, sku))
    conn.commit()

def obtener_carrito_db(username):
    conn = get_connection()
    cursor = conn.execute("SELECT sku, descripcion, precio, cantidad FROM carrito_items WHERE username=?", (username,))
    items = cursor.fetchall()
    return {item[0]: {"desc": item[1], "p": item[2], "c": item[3]} for item in items}

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
            st.toast(f"✅ {row['sku']} añadido")
            time.sleep(0.5); st.rerun()

# --- AUTENTICACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    carrito_actual = obtener_carrito_db(user['user'])
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        cart_lbl = f"🛒 Carrito ({len(carrito_actual)})" if carrito_actual else "🛒 Comprar"
        nav = [cart_lbl, "📜 Mis Pedidos"]
        if user['rol'] == 'admin':
            nav = [cart_lbl, "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Gestión Clientes"]
        menu = st.radio("Navegación", nav)

    # --- TIENDA ---
    if "🛒" in menu:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar SKU...")
            cat_sel = c2.selectbox("Categoría", ["Seleccionar"] + sorted(df['categoria'].unique().tolist()))
            
            if busq or cat_sel != "Seleccionar":
                df_v = df.copy()
                if busq: df_v = df_v[df_v['sku'].str.contains(busq, case=False) | df_v['descripcion'].str.contains(busq, case=False)]
                if cat_sel != "Seleccionar": df_v = df_v[df_v['categoria'] == cat_sel]
                
                cols = st.columns(4)
                for idx, row in df_v.reset_index().iterrows():
                    with cols[idx % 4]: card_producto(row, idx)
            else:
                st.info("Seleccione una categoría o busque un producto.")

        with t2:
            if not carrito_actual: st.info("Carrito vacío.")
            else:
                total = 0
                resumen = []
                for sku, info in carrito_actual.items():
                    sub = info['p'] * info['c']
                    total += sub
                    st.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']}) = ${sub:.2f}")
                    if st.button("🗑️", key=f"del_{sku}"):
                        eliminar_item_carrito(user['user'], sku); st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                st.divider()
                st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", use_container_width=True, type="primary"):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    get_connection().commit()
                    limpiar_carrito(user['user'])
                    st.success("Pedido enviado"); time.sleep(1); st.rerun()

    # --- MIS PEDIDOS (VISTA CLIENTE CORREGIDA) ---
    elif menu == "📜 Mis Pedidos":
        st.title("📜 Mis Pedidos Realizados")
        mis_peds = pd.read_sql("SELECT * FROM pedidos WHERE username=? ORDER BY id DESC", get_connection(), params=(user['user'],))
        if mis_peds.empty:
            st.info("Aún no tienes pedidos.")
        else:
            for _, p in mis_peds.iterrows():
                with st.expander(f"Pedido #{p['id']} - {p['fecha']} (${p['total']:.2f})"):
                    st.table(pd.DataFrame(json.loads(p['items'])))

    # --- PEDIDOS TOTALES (VISTA ADMIN CORREGIDA) ---
    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} ({p['fecha']})", expanded=False):
                items_list = json.loads(p['items'])
                st.table(pd.DataFrame(items_list))
                st.write(f"**Total: ${p['total']:.2f}**")
                
                c1, c2, c3 = st.columns(3)
                # Generación de PDF sin errores de codificación/atributo
                pdf_bytes = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items_list, p['total'])
                c1.download_button("📄 PDF", data=pdf_bytes, file_name=f"Pedido_{p['id']}.pdf", key=f"pdf_{p['id']}")
                
                if c3.button("🗑️ Eliminar", key=f"del_admin_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- GESTIÓN DE CLIENTES ---
    elif menu == "👥 Gestión Clientes":
        st.title("👥 Gestión de Clientes")
        # Aquí va tu código previo de gestión de clientes...
        df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin'", get_connection())
        st.dataframe(df_u)