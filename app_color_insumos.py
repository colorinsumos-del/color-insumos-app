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

# --- GENERADOR DE PDF ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    
    # Encabezado
    pdf.cell(190, 10, "COLOR INSUMOS - REPORTE DE PEDIDO", ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    
    # Tabla de Productos
    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 10, "SKU", 1)
    pdf.cell(90, 10, "Descripcion", 1)
    pdf.cell(20, 10, "Cant.", 1)
    pdf.cell(50, 10, "Subtotal", 1)
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    for item in items:
        desc = item['Desc'][:45] 
        pdf.cell(30, 8, str(item['SKU']), 1)
        pdf.cell(90, 8, desc, 1)
        pdf.cell(20, 8, str(item['Cant']), 1)
        pdf.cell(50, 8, f"${item['Subtotal']:.2f}", 1)
        pdf.ln()
    
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(190, 10, f"TOTAL FINAL: ${total:.2f}", ln=True, align="R")
    
    return pdf.output(dest='S').encode('latin-1', errors='ignore')

# --- INICIALIZACIÓN Y MIGRACIÓN ---
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

def limpiar_carrito(username):
    conn = get_connection()
    conn.execute("DELETE FROM carrito_items WHERE username=?", (username,))
    conn.commit()

def obtener_carrito_db(username):
    conn = get_connection()
    cursor = conn.execute("SELECT sku, descripcion, precio, cantidad FROM carrito_items WHERE username=?", (username,))
    items = cursor.fetchall()
    return {item[0]: {"desc": item[1], "p": item[2], "c": item[3]} for item in items}

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        .main .block-container { padding-top: 2rem !important; padding-bottom: 3rem !important; }
        html { overflow-y: auto !important; }
        header[data-testid="stHeader"] { z-index: 99; background-color: rgba(255, 255, 255, 0.8); backdrop-filter: blur(10px); }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-thumb { background: #cccccc; border-radius: 10px; }
        .stButton button { border-radius: 8px; margin-top: 5px; }
    </style>
""", unsafe_allow_html=True)

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:60])
        st.write(f"### ${row['precio']:.2f}")
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            guardar_item_carrito(st.session_state.user_data['user'], row, cant)
            st.toast(f"✅ {row['sku']} guardado")
            time.sleep(0.5); st.rerun()

# --- INICIO APP ---
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
    num_items = len(carrito_actual)
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("🔄 Sincronizar"): st.cache_data.clear(); st.rerun()
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        cart_lbl = f"🛒 Carrito ({num_items})" if num_items > 0 else "🛒 Comprar"
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
            busq = c1.text_input("🔍 Buscar SKU o Nombre...")
            cats = ["Seleccionar Categoría"] + sorted(df['categoria'].unique().tolist())
            cat_sel = c2.selectbox("Filtrar por Categoría", cats)
            
            if busq or (cat_sel != "Seleccionar Categoría"):
                df_v = df.copy()
                if busq: df_v = df_v[df_v['descripcion'].str.contains(busq, case=False) | df_v['sku'].str.contains(busq, case=False)]
                if cat_sel != "Seleccionar Categoría": df_v = df_v[df_v['categoria'] == cat_sel]
                
                st.divider()
                if df_v.empty: st.warning("No se encontraron productos.")
                else:
                    st.subheader(f"📦 Resultados ({len(df_v)} productos)")
                    cols = st.columns(4)
                    for idx, row in df_v.reset_index().iterrows():
                        with cols[idx % 4]: card_producto(row, idx)
            else:
                st.info("👋 Por favor, usa el buscador o selecciona una categoría.")

        with t2:
            if not carrito_actual: st.info("Carrito vacío.")
            else:
                total_base = 0
                resumen = []
                for sku, info in carrito_actual.items():
                    sub = info['p'] * info['c']
                    total_base += sub
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        col1.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']})")
                        col2.write(f"**${sub:.2f}**")
                        if col3.button("🗑️", key=f"rm_{sku}"): 
                            eliminar_item_carrito(user['user'], sku); st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                st.divider()
                pago_divisas = st.toggle("💸 Pagar en Divisas (Aplica 30% de descuento)")
                total_final = total_base * 0.70 if pago_divisas else total_base
                st.write(f"## Total Final: ${total_final:.2f}")
                
                if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total_final, "Pendiente"))
                    get_connection().commit()
                    limpiar_carrito(user['user'])
                    st.success("¡Pedido realizado con éxito!"); time.sleep(1); st.rerun()

    # --- PEDIDOS TOTALES (Admin) ---
    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control Global de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['username']} ({p['fecha']})"):
                items_list = json.loads(p['items'])
                df_it = pd.DataFrame(items_list)
                st.table(df_it)
                st.write(f"### Total: ${p['total']:.2f}")
                
                st.divider()
                c_pdf, c_xl, c_del = st.columns(3)
                
                pdf_data = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items_list, p['total'])
                c_pdf.download_button("📄 PDF", data=pdf_data, file_name=f"Pedido_{p['id']}.pdf", mime="application/pdf", use_container_width=True)
                
                out_xl = io.BytesIO()
                with pd.ExcelWriter(out_xl, engine='openpyxl') as writer: df_it.to_excel(writer, index=False)
                c_xl.download_button("📈 Excel", data=out_xl.getvalue(), file_name=f"Pedido_{p['id']}.xlsx", use_container_width=True)
                
                if c_del.button(f"🗑️ Eliminar #{p['id']}", key=f"del_{p['id']}", use_container_width=True):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],)); get_connection().commit(); st.rerun()

    # --- GESTIÓN DE CLIENTES ---
    elif menu == "👥 Gestión Clientes":
        st.title("👥 Panel de Control de Clientes")
        tab1, tab2 = st.tabs(["📝 Listado", "➕ Nuevo Cliente"])
        with tab1:
            df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin'", get_connection())
            for idx, row in df_u.iterrows():
                with st.container(border=True):
                    st.subheader(f"🏢 {row['nombre']}")
                    st.write(f"**ID:** {row['username']} | **Tel:** {row['telefono']}")
                    if st.button("✏️ Editar", key=f"e_{row['username']}"): st.session_state[f"ed_{row['username']}"] = True
                    if st.session_state.get(f"ed_{row['username']}", False):
                        with st.form(f"f_{row['username']}"):
                            en, et = st.text_input("Nombre", value=row['nombre']), st.text_input("Tel", value=row['telefono'])
                            if st.form_submit_button("Guardar"):
                                get_connection().execute("UPDATE usuarios SET nombre=?, telefono=? WHERE username=?", (en, et, row['username']))
                                get_connection().commit(); st.rerun()
        with tab2:
            with st.form("new_u"):
                n_u, n_p, n_n = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
                if st.form_submit_button("Registrar"):
                    try:
                        get_connection().execute("INSERT INTO usuarios (username,password,nombre,rol) VALUES (?,?,?,?)", (n_u, n_p, n_n, 'cliente'))
                        get_connection().commit(); st.success("Registrado"); st.rerun()
                    except: st.error("Ya existe")

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo")
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Procesar"): st.info("Función de procesamiento pendiente.")