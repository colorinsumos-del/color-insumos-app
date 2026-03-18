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

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
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
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

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

@st.cache_data(ttl=60)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        img_path = row['foto_path']
        if img_path and os.path.exists(img_path):
            st.image(img_path, use_container_width=True)
        else:
            st.image("https://via.placeholder.com/150?text=No+Disponible", use_container_width=True)
        
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:80])
        
        cant = st.number_input("Cantidad", 1, 500, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("🛒 Añadir", key=f"btn_{row['sku']}_{idx}", use_container_width=True):
            user_id = st.session_state.user_data['user']
            if user_id not in st.session_state.carritos:
                st.session_state.carritos[user_id] = {}
            st.session_state.carritos[user_id][row['sku']] = {
                "desc": row['descripcion'], 
                "p": row['precio'], 
                "c": cant
            }
            st.toast(f"✅ {row['sku']} añadido")

# --- APP ---
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
        else: st.error("Acceso incorrecto")
else:
    user = st.session_state.user_data
    user_id = user['user']
    if user_id not in st.session_state.carritos:
        st.session_state.carritos[user_id] = {}
    
    with st.sidebar:
        st.header(f"Hola, {user['nombre']}")
        opciones = ["🛍️ Tienda", f"🛒 Carrito ({len(st.session_state.carritos[user_id])})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin':
            opciones += ["📊 Gestión Pedidos", "📁 Cargar PDF", "👥 Clientes"]
        
        menu = st.radio("Menú", opciones)
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    # --- TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 0.5])
            busq = c1.text_input("🔍 Buscar por SKU o Nombre...")
            conn = get_connection()
            res_cats = conn.execute("SELECT DISTINCT categoria FROM productos").fetchall()
            cat_sel = c2.selectbox("📂 Categoría", ["Todas"] + sorted([r[0] for r in res_cats]))
            if c3.button("🔄 Reset"): st.rerun()

        if not busq and cat_sel == "Todas":
            st.info("👋 Bienvenido. Por favor busca un producto o selecciona una categoría para empezar.")
        else:
            df = cargar_catalogo()
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]
            
            cols = st.columns(4)
            for i, (_, row) in enumerate(df.iterrows()):
                with cols[i % 4]: card_producto(row, i)

    # --- CARRITO ---
    elif "🛒" in menu:
        st.title("🛒 Tu Carrito")
        carrito = st.session_state.carritos[user_id]
        if not carrito:
            st.warning("Carrito vacío.")
        else:
            total = 0
            resumen_items = []
            for sku, info in list(carrito.items()):
                sub = info['p'] * info['c']
                total += sub
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 1, 0.5])
                    col1.write(f"**{sku}** - {info['desc']}")
                    col2.write(f"{info['c']} x ${info['p']:.2f} = **${sub:.2f}**")
                    if col3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[user_id][sku]
                        st.rerun()
                resumen_items.append({"sku": sku, "cant": info['c'], "precio": info['p']})

            st.divider()
            st.write(f"### Total: ${total:.2f}")
            if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                             (user_id, datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(resumen_items), total, "Pendiente"))
                get_connection().commit()
                st.session_state.carritos[user_id] = {}
                st.success("Pedido enviado correctamente.")
                time.sleep(1); st.rerun()

    # --- GESTIÓN DE PEDIDOS (ADMIN) Y MIS PEDIDOS (CLIENTE) ---
    elif "Pedidos" in menu:
        st.title("📜 Listado de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC"
        if user['rol'] != 'admin':
            query = f"SELECT * FROM pedidos WHERE username='{user_id}' ORDER BY id DESC"
        
        df_p = pd.read_sql(query, get_connection())
        
        if df_p.empty: st.write("No hay pedidos.")
        else:
            if user['rol'] == 'admin':
                # EXPORTAR EXCEL
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_p.to_excel(writer, index=False, sheet_name='Pedidos')
                st.download_button("📥 Descargar Todo en Excel", data=output.getvalue(), 
                                   file_name="reporte_pedidos.xlsx", mime="application/vnd.ms-excel")
            
            for _, p in df_p.iterrows():
                with st.expander(f"Pedido #{p['id']} - {p['username']} ({p['fecha']}) - ${p['total']:.2f} [{p['status']}]"):
                    st.table(pd.DataFrame(json.loads(p['items'])))
                    if user['rol'] == 'admin':
                        ns = st.selectbox("Cambiar Estado", ["Pendiente", "Pagado", "Enviado"], key=f"st_{p['id']}")
                        if st.button("Actualizar", key=f"up_{p['id']}"):
                            get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (ns, p['id']))
                            get_connection().commit(); st.rerun()

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario")
        archivo = st.file_uploader("PDF Pointer", type="pdf")
        if archivo and st.button("Procesar"):
            with st.spinner("Cargando..."):
                with open("temp.pdf", "wb") as f: f.write(archivo.getbuffer())
                doc = fitz.open("temp.pdf")
                conn = get_connection()
                for page in doc:
                    tabs = page.find_tables()
                    if tabs:
                        for tab in tabs:
                            for row in tab.to_pandas().itertuples():
                                try:
                                    sku, desc, prec = str(row[1]), str(row[3]), limpiar_precio(row[5])
                                    if len(sku) > 2:
                                        conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) VALUES (?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio", (sku, desc, prec, "General", ""))
                                except: pass
                conn.commit()
                st.success("Inventario Actualizado"); st.rerun()

    # --- CLIENTES ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        clientes = pd.read_sql("SELECT username, nombre, telefono FROM usuarios WHERE rol='cliente'", get_connection())
        st.dataframe(clientes, use_container_width=True)
        with st.form("n_c"):
            un, pn, nn, tn = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre"), st.text_input("Tlf")
            if st.form_submit_button("Registrar Cliente"):
                get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (un, pn, nn, 'cliente', '', tn))
                get_connection().commit(); st.rerun()