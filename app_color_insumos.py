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

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- OPTIMIZACIÓN DE CACHÉ ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=300)
def cargar_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- ESTILO CSS ---
st.markdown("""
    <style>
        [data-testid="stSidebarNav"] { max-height: 100vh; overflow-y: auto; }
        .stButton button { border-radius: 8px; }
        /* Efecto de pulso para el carrito con items */
        .cart-active { color: #FF4B4B; font-weight: bold; }
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

# --- FRAGMENTO DE PRODUCTO (RÁPIDO) ---
@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'])
        st.write(f"💰 **${row['precio']:.2f}**")
        
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast(f"✅ {row['sku']} añadido")
            time.sleep(0.5)
            st.rerun() # Recargamos para actualizar el contador del menú lateral

# --- ESTADO DE SESIÓN ---
if 'auth' not in st.session_state: st.session_state.auth = False
if 'user_data' not in st.session_state: st.session_state.user_data = None
if 'carrito' not in st.session_state: st.session_state.carrito = {}

init_db()

if not st.session_state.auth:
    st.title("🚀 Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        conn = get_connection()
        res = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
else:
    user = st.session_state.user_data
    
    # --- LÓGICA DE ICONO DINÁMICO ---
    num_items = len(st.session_state.carrito)
    cart_label = f"🛒 Mi Pedido ({num_items})" if num_items > 0 else "🛒 Comprar"
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False; st.rerun()
        st.divider()
        
        # Menú dinámico
        if user['rol'] == 'admin':
            nav = ["🛍️ Catálogo Admin", "📁 Cargar PDF", "👥 Clientes", "📊 Pedidos Totales"]
        else:
            nav = [cart_label, "📜 Mis Pedidos"]
            
        menu = st.radio("Navegación", nav)

    # --- VISTA TIENDA ---
    if menu in [cart_label, "🛍️ Catálogo Admin"]:
        tab_cat, tab_car = st.tabs(["📦 Productos", "🧾 Revisar Carrito"])
        
        with tab_cat:
            df_cat = cargar_catalogo_cache()
            if not df_cat.empty:
                busq = st.text_input("🔍 Buscar por SKU o nombre...")
                df_v = df_cat[df_cat['descripcion'].str.contains(busq, case=False) | df_cat['sku'].str.contains(busq, case=False)] if busq else df_cat
                
                for cat in sorted(df_v['categoria'].unique()):
                    with st.expander(cat, expanded=True):
                        itms = df_v[df_v['categoria'] == cat]
                        cols = st.columns(4)
                        for idx, row in itms.reset_index().iterrows():
                            with cols[idx % 4]:
                                card_producto(row, idx)

        with tab_car:
            if not st.session_state.carrito:
                st.info("Tu carrito está vacío. ¡Explora el catálogo!")
            else:
                total = 0
                resumen_excel = []
                for sku, info in list(st.session_state.carrito.items()):
                    sub = info['p'] * info['c']
                    total += sub
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([3, 1, 1])
                        c1.write(f"**{sku}** - {info['desc']}\n({info['c']} x ${info['p']})")
                        c2.write(f"**${sub:.2f}**")
                        if c3.button("🗑️", key=f"rm_{sku}"):
                            del st.session_state.carrito[sku]
                            st.rerun()
                    resumen_excel.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                st.write(f"## Total: ${total:.2f}")
                
                if st.button("🚀 Procesar Pedido Web", type="primary", use_container_width=True):
                    with st.spinner("Guardando pedido..."):
                        conn = get_connection()
                        conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                     (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen_excel), total, "Pendiente"))
                        conn.commit()
                        st.session_state.carrito = {}
                        st.success("¡Pedido enviado!")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()

    # --- OTRAS SECCIONES (IGUAL QUE ANTES) ---
    elif menu == "📜 Mis Pedidos" or menu == "📊 Pedidos Totales":
        st.title("Historial de Pedidos")
        conn = get_connection()
        query = "SELECT * FROM pedidos WHERE username=? ORDER BY id DESC" if user['rol'] == 'cliente' else "SELECT * FROM pedidos ORDER BY id DESC"
        peds = pd.read_sql(query, conn, params=(user['user'],) if user['rol'] == 'cliente' else ())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} - ${p['total']:.2f}"):
                st.table(pd.DataFrame(json.loads(p['items'])))