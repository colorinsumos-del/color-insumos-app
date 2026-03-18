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

# --- CONFIGURACIÓN DE RUTAS Y BASE DE DATOS ---
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
    # Productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Usuarios
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    # Pedidos (Incluye campos de totalización y método de pago)
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  cliente_nombre TEXT,
                  fecha TEXT, 
                  items TEXT, 
                  metodo_pago TEXT,
                  subtotal REAL,
                  descuento REAL,
                  total REAL, 
                  status TEXT)''')
    
    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

# --- FUNCIONES DE APOYO ---
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
            uid = st.session_state.user_data['user']
            if uid not in st.session_state.carritos:
                st.session_state.carritos[uid] = {}
            
            st.session_state.carritos[uid][row['sku']] = {
                "desc": row['descripcion'], 
                "p": row['precio'], 
                "c": cant
            }
            st.toast(f"✅ {row['sku']} añadido al carrito")

# --- LÓGICA DE SESIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'carritos' not in st.session_state: st.session_state.carritos = {}

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario / Email")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Acceso denegado")
else:
    user = st.session_state.user_data
    uid = user['user']
    if uid not in st.session_state.carritos: st.session_state.carritos[uid] = {}

    with st.sidebar:
        st.header(f"👋 {user['nombre']}")
        num_items = len(st.session_state.carritos[uid])
        opciones = ["🛍️ Tienda", f"🛒 Carrito ({num_items})", "📜 Mis Pedidos"]
        
        if user['rol'] == 'admin':
            opciones += ["📊 Gestión de Ventas", "📁 Cargar PDF", "👥 Clientes"]
        
        menu = st.radio("Menú Principal", opciones)
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Insumos")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 0.5])
            busq = c1.text_input("🔍 Buscar por SKU o Descripción...")
            conn = get_connection()
            res_cats = conn.execute("SELECT DISTINCT categoria FROM productos").fetchall()
            cat_sel = c2.selectbox("📂 Departamento", ["Todas"] + sorted([r[0] for r in res_cats]))
            if c3.button("🔄 Reset"): st.rerun()

        if not busq and cat_sel == "Todas":
            st.info("Bienvenido. Escribe el nombre de un producto o selecciona una categoría para empezar.")
        else:
            df = cargar_catalogo()
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]
            
            if df.empty: st.warning("No se encontraron productos.")
            else:
                cols = st.columns(4)
                for i, (_, row) in enumerate(df.iterrows()):
                    with cols[i % 4]: card_producto(row, i)

    # --- MÓDULO CARRITO Y TOTALIZACIÓN ---
    elif "🛒" in menu:
        st.title("🛒 Revisión de Pedido")
        carrito = st.session_state.carritos[uid]
        
        if not carrito:
            st.warning("Tu carrito está vacío.")
        else:
            total_bruto = 0
            items_pedido = []
            for sku, info in list(carrito.items()):
                monto_item = info['p'] * info['c']
                total_bruto += monto_item
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 1, 0.5])
                    col1.write(f"**{sku}** - {info['desc']}")
                    col2.write(f"{info['c']} x ${info['p']:.2f} = **${monto_item:.2f}**")
                    if col3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[uid][sku]
                        st.rerun()
                items_pedido.append({"SKU": sku, "Descripción": info['desc'], "Cant": info['c'], "Precio": info['p']})

            st.divider()
            c_pago, c_resumen = st.columns(2)
            
            with c_pago:
                st.subheader("💳 Método de Pago")
                metodo = st.radio("Seleccione uno:", ["Transferencia Bolívares (BCV)", "Divisas / Zelle (-10% Descuento)"])
            
            with c_resumen:
                # Lógica de descuentos
                desc_metodo = 0.10 if "Divisas" in metodo else 0.0
                desc_volumen = 0.05 if total_bruto > 100 else 0.0 # Descuento extra por compras grandes
                
                pct_total = (desc_metodo + desc_volumen)
                monto_descuento = total_bruto * pct_total
                total_neto = total_bruto - monto_descuento
                
                st.write(f"Subtotal: ${total_bruto:.2f}")
                if pct_total > 0:
                    st.success(f"Descuento Aplicado: {pct_total*100:.0f}% (-${monto_descuento:.2f})")
                st.write(f"## Total a Pagar: ${total_neto:.2f}")

            if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                get_connection().execute(
                    """INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) 
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), 
                     json.dumps(items_pedido), metodo, total_bruto, monto_descuento, total_neto, "Pendiente")
                )
                get_connection().commit()
                st.session_state.carritos[uid] = {} # Limpiar solo el carrito del usuario actual
                st.success("¡Pedido enviado con éxito! Nos contactaremos pronto.")
                time.sleep(1); st.rerun()

    # --- GESTIÓN DE VENTAS (ADMIN) Y MIS PEDIDOS (CLIENTE) ---
    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📜 Registro de Pedidos")
        
        # Filtrar vista: Admin ve todo, Cliente solo lo suyo
        query = "SELECT * FROM pedidos ORDER BY id DESC"
        if user['rol'] != 'admin':
            query = f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        
        df_p = pd.read_sql(query, get_connection())
        
        if df_p.empty:
            st.write("No hay pedidos registrados.")
        else:
            # Opción de Exportar para Admin
            if user['rol'] == 'admin':
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_p.to_excel(writer, index=False, sheet_name='Ventas')
                st.download_button("📥 Descargar Reporte Excel", data=output.getvalue(), 
                                   file_name=f"ventas_color_insumos_{datetime.now().strftime('%Y%m%d')}.xlsx")
            
            for _, p in df_p.iterrows():
                with st.expander(f"📦 Pedido #{p['id']} - {p['cliente_nombre']} | {p['fecha']} | ${p['total']:.2f} ({p['status']})"):
                    st.write(f"**Usuario:** {p['username']} | **Método:** {p['metodo_pago']}")
                    st.write(f"**Subtotal:** ${p['subtotal']:.2f} | **Ahorro:** -${p['descuento']:.2f}")
                    
                    items_list = json.loads(p['items'])
                    st.table(pd.DataFrame(items_list))
                    
                    if user['rol'] == 'admin':
                        c1, c2 = st.columns(2)
                        nuevo_st = c1.selectbox("Cambiar Estatus", ["Pendiente", "Pagado", "Enviado", "Cancelado"], key=f"st_{p['id']}")
                        if c2.button("Actualizar", key=f"up_{p['id']}"):
                            get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (nuevo_st, p['id']))
                            get_connection().commit(); st.rerun()

    # --- MÓDULO CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario")
        archivo = st.file_uploader("Subir Lista PDF", type="pdf")
        if archivo and st.button("Procesar Lista"):
            with st.spinner("Leyendo catálogo..."):
                with open("temp.pdf", "wb") as f: f.write(archivo.getbuffer())
                doc = fitz.open("temp.pdf")
                conn = get_connection()
                for page in doc:
                    tabs = page.find_tables()
                    if tabs:
                        for tab in tabs:
                            for row in tab.to_pandas().itertuples():
                                try:
                                    # Mapeo según estructura de PDF Pointer
                                    sku, desc, prec = str(row[1]), str(row[3]), limpiar_precio(row[5])
                                    if len(sku) > 2:
                                        conn.execute(
                                            """INSERT INTO productos (sku, descripcion, precio, categoria) 
                                               VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio""",
                                            (sku, desc, prec, "General")
                                        )
                                except: pass
                conn.commit()
                st.success("Inventario actualizado correctamente.")
                st.cache_data.clear(); time.sleep(1); st.rerun()

    # --- MÓDULO CLIENTES ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        clientes = pd.read_sql("SELECT username, nombre, telefono, direccion FROM usuarios WHERE rol='cliente'", get_connection())
        st.dataframe(clientes, use_container_width=True)
        
        with st.form("nuevo_cliente"):
            st.write("Registrar Nuevo Cliente")
            c1, c2 = st.columns(2)
            u_n = c1.text_input("Email/Usuario")
            p_n = c2.text_input("Clave Inicial")
            n_n = c1.text_input("Nombre / Razón Social")
            t_n = c2.text_input("Teléfono")
            d_n = st.text_area("Dirección de Despacho")
            if st.form_submit_button("Registrar"):
                get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (u_n, p_n, n_n, 'cliente', d_n, t_n))
                get_connection().commit()
                st.success("Cliente creado"); st.rerun()