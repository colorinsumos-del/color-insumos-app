import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import json
import time
from datetime import datetime

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

# --- INICIALIZACIÓN Y MIGRACIÓN ---
def init_db():
    conn = get_connection()
    # Tabla de productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de usuarios
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT DEFAULT '', telefono TEXT DEFAULT '')''')
    # Tabla de pedidos (Ya era persistente, pero aseguramos su estructura)
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # NUEVA TABLA: Carrito Persistente
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')
    
    # Usuario admin por defecto
    try:
        conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                     ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
        conn.commit()
    except: pass

# --- FUNCIONES DE BASE DE DATOS PARA EL CARRITO ---
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
    # Convertir a formato de diccionario compatible con tu lógica anterior
    return {item[0]: {"desc": item[1], "p": item[2], "c": item[3]} for item in items}

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        html { overflow-y: scroll !important; }
        [data-testid="stSidebar"] section { overflow-y: scroll !important; }
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-thumb { background: #888; border-radius: 5px; }
        .stButton button { border-radius: 8px; }
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
            st.toast(f"✅ {row['sku']} guardado en base de datos")
            time.sleep(0.5); st.rerun()

# --- INICIO APP ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'user_data' not in st.session_state: st.session_state.user_data = None

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
    # RECUPERAR CARRITO DESDE DB
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
            cats = ["Todas"] + sorted(df['categoria'].unique().tolist())
            cat_sel = c2.selectbox("Categoría", cats)
            
            df_v = df.copy()
            if busq: df_v = df_v[df_v['descripcion'].str.contains(busq, case=False) | df_v['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df_v = df_v[df_v['categoria'] == cat_sel]
            
            for cat in sorted(df_v['categoria'].unique()):
                with st.expander(cat, expanded=True):
                    cols = st.columns(4)
                    for idx, row in df_v[df_v['categoria'] == cat].reset_index().iterrows():
                        with cols[idx % 4]: card_producto(row, idx)

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
                            eliminar_item_carrito(user['user'], sku)
                            st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                st.divider()
                st.write(f"**Subtotal:** ${total_base:.2f}")
                
                pago_divisas = st.toggle("💸 Pagar en Divisas (Aplica 30% de descuento)")
                total_final = total_base - (total_base * 0.30) if pago_divisas else total_base
                
                if pago_divisas: st.info(f"✨ Descuento 30% aplicado: -${(total_base * 0.30):.2f}")
                elif total_base > 100:
                    desc = total_base * 0.10
                    total_final = total_base - desc
                    st.success(f"✅ Descuento 10% por compra > $100: -${desc:.2f}")

                st.write(f"## Total Final: ${total_final:.2f}")
                
                if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total_final, "Pendiente"))
                    get_connection().commit()
                    limpiar_carrito(user['user'])
                    st.success("¡Pedido realizado con éxito!"); time.sleep(1); st.rerun()

    # --- MIS PEDIDOS (Para Clientes) ---
    elif menu == "📜 Mis Pedidos":
        st.title("📜 Historial de mis Pedidos")
        mis_peds = pd.read_sql("SELECT * FROM pedidos WHERE username=? ORDER BY id DESC", get_connection(), params=(user['user'],))
        if mis_peds.empty: st.info("Aún no has realizado pedidos.")
        for _, p in mis_peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} - Total: ${p['total']:.2f}"):
                st.table(pd.DataFrame(json.loads(p['items'])))
                st.status(f"Estado: {p['status']}")

    # --- PEDIDOS TOTALES (Solo Admin) ---
    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control Global de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} ({p['fecha']})"):
                df_it = pd.DataFrame(json.loads(p['items']))
                st.table(df_it)
                st.write(f"**Total: ${p['total']:.2f}**")
                if st.button(f"Eliminar #{p['id']}", key=f"del_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- GESTIÓN DE CLIENTES ---
    elif menu == "👥 Gestión Clientes":
        # (Se mantiene igual a tu lógica de edición/creación en base de datos)
        st.title("👥 Gestión de Clientes")
        # ... (código previo de gestión de clientes) ...

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo")
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Procesar"):
            st.info("Implementa la función 'procesar_pdf' para actualizar los productos.")