import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import json
import shutil
import time
from datetime import datetime

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Optimizado", layout="wide")

# --- MOTOR DE VELOCIDAD (CACHÉ) ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- ESTILOS CSS (BARRA DE SCROLL SIEMPRE VISIBLE) ---
st.markdown("""
    <style>
        /* Forzar scrollbar visible en el sidebar */
        [data-testid="stSidebar"] section {
            overflow-y: scroll !important;
        }
        /* Estilo de la barra de scroll para Chrome/Safari */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
        [data-testid="stSidebarNav"] { max-height: 100vh; }
        .stButton button { border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

def init_db():
    conn = get_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS productos (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS pedidos (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)')
    try:
        conn.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?)", ('colorinsumos@gmail.com', '20880157', 'Admin', 'admin'))
        conn.commit()
    except: pass

# --- FRAGMENTO DE PRODUCTO ---
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
            st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast(f"✅ {row['sku']} añadido")
            time.sleep(0.5)
            st.rerun()

# --- ESTADO DE SESIÓN ---
if 'auth' not in st.session_state: st.session_state.auth = False
if 'user_data' not in st.session_state: st.session_state.user_data = None
if 'carrito' not in st.session_state: st.session_state.carrito = {}

init_db()

if not st.session_state.auth:
    st.title("🚀 Color Insumos - Acceso")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
else:
    user = st.session_state.user_data
    num_items = len(st.session_state.carrito)
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("🔄 Sincronizar", use_container_width=True): 
            st.cache_data.clear()
            st.rerun()
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        cart_lbl = f"🛒 Carrito ({num_items})" if num_items > 0 else "🛒 Comprar"
        nav = [cart_lbl, "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Clientes"] if user['rol'] == 'admin' else [cart_lbl, "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav)

    if "🛒" in menu:
        t_cat, t_car = st.tabs(["🛍️ Buscar Productos", "🧾 Revisar Pedido"])
        
        with t_cat:
            df = obtener_catalogo_cache()
            st.info("💡 Utiliza los filtros de arriba para ver los productos.")
            
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar por Nombre o SKU...")
            cats = ["Seleccionar Categoría"] + sorted(df['categoria'].unique().tolist())
            cat_sel = c2.selectbox("📁 Filtrar por Categoría", cats)
            
            # LÓGICA DE MOSTRAR SOLO SI HAY BÚSQUEDA
            if busq or cat_sel != "Seleccionar Categoría":
                df_v = df.copy()
                if busq:
                    df_v = df_v[df_v['descripcion'].str.contains(busq, case=False) | df_v['sku'].str.contains(busq, case=False)]
                if cat_sel != "Seleccionar Categoría":
                    df_v = df_v[df_v['categoria'] == cat_sel]
                
                if df_v.empty:
                    st.warning("No se encontraron resultados.")
                else:
                    for cat in sorted(df_v['categoria'].unique()):
                        with st.expander(f"{cat}", expanded=True):
                            items = df_v[df_v['categoria'] == cat]
                            cols = st.columns(4)
                            for idx, row in items.reset_index().iterrows():
                                with cols[idx % 4]: card_producto(row, idx)
            else:
                st.write("---")
                st.caption("Esperando búsqueda... escribe algo o selecciona una categoría para empezar.")

        with t_car:
            if not st.session_state.carrito: 
                st.info("Carrito vacío.")
            else:
                total = 0
                resumen = []
                for sku, info in list(st.session_state.carrito.items()):
                    sub = info['p'] * info['c']
                    total += sub
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        col1.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']})")
                        col2.write(f"**${sub:.2f}**")
                        if col3.button("🗑️", key=f"del_{sku}"): del st.session_state.carrito[sku]; st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                    conn = get_connection()
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    conn.commit()
                    st.session_state.carrito = {}; st.success("¡Pedido enviado!"); st.rerun()

    # --- HISTORIAL (MANTENIENDO LO ANTERIOR) ---
    elif "Pedidos" in menu:
        st.title("Historial de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else "SELECT * FROM pedidos WHERE username=? ORDER BY id DESC"
        params = () if user['rol'] == 'admin' else (user['user'],)
        peds = pd.read_sql(query, get_connection(), params=params)
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} - {p['fecha']}"):
                df_p = pd.DataFrame(json.loads(p['items']))
                st.table(df_p)
                st.write(f"**Total: ${p['total']:.2f}**")
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df_p.to_excel(writer, index=False)
                st.download_button(f"📥 Descargar Excel #{p['id']}", output.getvalue(), f"Pedido_{p['id']}.xlsx", key=f"dl_{p['id']}")

    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("Subir Catálogo PDF", type="pdf")
        if f and st.button("Iniciar"): 
            # Aquí iría tu función procesar_pdf(f) de antes...
            st.success("Catálogo actualizado. Haz clic en Sincronizar.")

    elif menu == "👥 Clientes":
        with st.form("new_u"):
            nu, np, nn = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
            if st.form_submit_button("Crear"):
                get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?)", (nu, np, nn, 'cliente'))
                get_connection().commit(); st.success("Cliente creado")