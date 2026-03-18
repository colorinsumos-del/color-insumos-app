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
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    # Productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Usuarios
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    # Pedidos base
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # --- MIGRACIÓN: Verificar y añadir columnas faltantes ---
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(pedidos)")
    columnas = [info[1] for info in cursor.fetchall()]
    
    # Si faltan estas columnas, las añadimos una por una
    nuevas_cols = {
        "cliente_nombre": "TEXT",
        "metodo_pago": "TEXT",
        "subtotal": "REAL",
        "descuento": "REAL"
    }
    
    for col, tipo in nuevas_cols.items():
        if col not in columnas:
            try:
                conn.execute(f"ALTER TABLE pedidos ADD COLUMN {col} {tipo}")
            except: pass

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
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        else:
            st.image("https://via.placeholder.com/150?text=Color+Insumos", use_container_width=True)
        
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:80])
        
        cant = st.number_input("Cantidad", 1, 500, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("🛒 Añadir", key=f"btn_{row['sku']}_{idx}", use_container_width=True):
            uid = st.session_state.user_data['user']
            if uid not in st.session_state.carritos: st.session_state.carritos[uid] = {}
            st.session_state.carritos[uid][row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast("Añadido al carrito")

# --- LÓGICA DE SESIÓN ---
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
    uid = user['user']
    if uid not in st.session_state.carritos: st.session_state.carritos[uid] = {}

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(st.session_state.carritos[uid])})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Clientes"]
        menu = st.radio("Menú", opc)
        if st.button("Salir"): 
            st.session_state.auth = False
            st.rerun()

    # --- TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 0.5])
            busq = c1.text_input("🔍 Buscar por SKU o Descripción...")
            conn = get_connection()
            res_cats = conn.execute("SELECT DISTINCT categoria FROM productos").fetchall()
            cat_sel = c2.selectbox("📂 Categoría", ["Todas"] + sorted([r[0] for r in res_cats]))
            if c3.button("🔄 Reset"): st.rerun()

        if not busq and cat_sel == "Todas":
            st.info("💡 Busca un producto o selecciona una categoría.")
        else:
            df = cargar_catalogo()
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]
            
            cols = st.columns(4)
            for i, (_, row) in enumerate(df.iterrows()):
                with cols[i % 4]: card_producto(row, i)

    # --- CARRITO Y TOTALIZACIÓN ---
    elif "🛒" in menu:
        st.title("🛒 Finalizar Pedido")
        carrito = st.session_state.carritos[uid]
        if not carrito: st.warning("Tu carrito está vacío.")
        else:
            subtotal_bruto = 0
            items_pedido = []
            for sku, info in list(carrito.items()):
                monto = info['p'] * info['c']
                subtotal_bruto += monto
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 1, 0.5])
                    col1.write(f"**{sku}** - {info['desc']}")
                    col2.write(f"{info['c']} x ${info['p']:.2f} = ${monto:.2f}")
                    if col3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[uid][sku]
                        st.rerun()
                items_pedido.append({"sku": sku, "desc": info['desc'], "cant": info['c'], "precio": info['p']})

            st.divider()
            c_pago, c_total = st.columns(2)
            with c_pago:
                metodo = st.radio("Método de Pago", ["Transferencia BS (BCV)", "Divisas / Zelle (-10% Descuento)"])
            
            with c_total:
                desc = 0.10 if "Divisas" in metodo else 0.0
                if subtotal_bruto > 100: desc += 0.05
                monto_desc = subtotal_bruto * desc
                total_neto = subtotal_bruto - monto_desc
                st.write(f"Subtotal: ${subtotal_bruto:.2f}")
                st.write(f"Ahorro: -${monto_desc:.2f} ({desc*100:.0f}%)")
                st.write(f"### Total Final: ${total_neto:.2f}")

            if st.button("Confirmar Pedido ✅", use_container_width=True, type="primary"):
                get_connection().execute(
                    """INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) 
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), 
                     json.dumps(items_pedido), metodo, subtotal_bruto, monto_desc, total_neto, "Pendiente")
                )
                get_connection().commit()
                st.session_state.carritos[uid] = {}
                st.success("Pedido enviado. ¡Gracias!")
                time.sleep(1); st.rerun()

    # --- GESTIÓN DE VENTAS (ADMIN) ---
    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📊 Registro de Ventas")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        df_p = pd.read_sql(query, get_connection())
        
        if df_p.empty: st.write("No hay pedidos registrados.")
        else:
            if user['rol'] == 'admin':
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_p.to_excel(writer, index=False)
                st.download_button("📥 Descargar Excel", data=output.getvalue(), file_name="ventas_color.xlsx")
            
            for _, p in df_p.iterrows():
                # El .get() previene errores si hay datos viejos sin esa columna
                c_nom = p.get('cliente_nombre', 'Cliente Antiguo')
                with st.expander(f"Pedido #{p['id']} - {c_nom} | {p['fecha']} | ${p['total']:.2f}"):
                    st.write(f"**Pago:** {p.get('metodo_pago', 'No especificado')}")
                    st.table(pd.DataFrame(json.loads(p['items'])))
                    if user['rol'] == 'admin':
                        nuevo_st = st.selectbox("Estado", ["Pendiente", "Pagado", "Enviado"], key=f"st_{p['id']}")
                        if st.button("Actualizar", key=f"btn_{p['id']}"):
                            get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (nuevo_st, p['id']))
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
                                        conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio", (sku, desc, prec, "General"))
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