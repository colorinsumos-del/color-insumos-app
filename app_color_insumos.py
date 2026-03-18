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
    # Tablas Base
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # --- SISTEMA DE MIGRACIÓN AUTOMÁTICA ---
    # Esto evita el KeyError añadiendo las columnas si no existen
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(pedidos)")
    columnas_actuales = [info[1] for info in cursor.fetchall()]
    
    columnas_nuevas = {
        "cliente_nombre": "TEXT",
        "metodo_pago": "TEXT",
        "subtotal": "REAL",
        "descuento": "REAL"
    }
    
    for col, tipo in columnas_nuevas.items():
        if col not in columnas_actuales:
            try:
                conn.execute(f"ALTER TABLE pedidos ADD COLUMN {col} {tipo}")
            except Exception as e:
                print(f"Error migrando columna {col}: {e}")

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
            st.image("https://via.placeholder.com/150?text=Color+Insumos", use_container_width=True)
        
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:80])
        
        cant = st.number_input("Cantidad", 1, 500, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("🛒 Añadir", key=f"btn_{row['sku']}_{idx}", use_container_width=True):
            uid = st.session_state.user_data['user']
            if uid not in st.session_state.carritos:
                st.session_state.carritos[uid] = {}
            st.session_state.carritos[uid][row['sku']] = {
                "desc": row['descripcion'], "p": row['precio'], "c": cant
            }
            st.toast("✅ Añadido")

# --- FLUJO PRINCIPAL ---
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
        else: st.error("Acceso denegado")
else:
    user = st.session_state.user_data
    uid = user['user']
    if uid not in st.session_state.carritos: st.session_state.carritos[uid] = {}

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        num_c = len(st.session_state.carritos[uid])
        opc = ["🛍️ Tienda", f"🛒 Carrito ({num_c})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin':
            opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Clientes"]
        
        menu = st.radio("Menú", opc)
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 0.5])
            busq = c1.text_input("🔍 Buscar por SKU o Descripción...")
            res_cats = get_connection().execute("SELECT DISTINCT categoria FROM productos").fetchall()
            cat_sel = c2.selectbox("📂 Departamento", ["Todas"] + sorted([r[0] for r in res_cats]))
            if c3.button("🔄 Reset"): st.rerun()

        if not busq and cat_sel == "Todas":
            st.info("Escribe algo para buscar o selecciona una categoría.")
        else:
            df = cargar_catalogo()
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]
            
            cols = st.columns(4)
            for i, (_, row) in enumerate(df.iterrows()):
                with cols[i % 4]: card_producto(row, i)

    # --- MÓDULO CARRITO ---
    elif "🛒" in menu:
        st.title("🛒 Finalizar Pedido")
        carrito = st.session_state.carritos[uid]
        if not carrito: st.warning("Tu carrito está vacío.")
        else:
            total_b = 0
            items_p = []
            for sku, info in list(carrito.items()):
                monto = info['p'] * info['c']
                total_b += monto
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 1, 0.5])
                    col1.write(f"**{sku}** - {info['desc']}")
                    col2.write(f"{info['c']} x ${info['p']:.2f} = **${monto:.2f}**")
                    if col3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[uid][sku]
                        st.rerun()
                items_p.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Precio": info['p']})

            st.divider()
            cp, cr = st.columns(2)
            with cp:
                metodo = st.radio("Método de Pago", ["Transferencia BS (BCV)", "Divisas / Zelle (-10% Descuento)"])
            with cr:
                desc_p = 0.10 if "Divisas" in metodo else 0.0
                if total_b > 100: desc_p += 0.05
                monto_d = total_b * desc_p
                total_n = total_b - monto_d
                st.write(f"Subtotal: ${total_b:.2f}")
                st.write(f"Descuento: {desc_p*100:.0f}% (-${monto_d:.2f})")
                st.write(f"### Total: ${total_n:.2f}")

            if st.button("Confirmar Pedido ✅", type="primary", use_container_width=True):
                get_connection().execute(
                    """INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) 
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), 
                     json.dumps(items_p), metodo, total_b, monto_d, total_n, "Pendiente")
                )
                get_connection().commit()
                st.session_state.carritos[uid] = {}
                st.success("¡Pedido enviado!")
                time.sleep(1); st.rerun()

    # --- MÓDULO MIS PEDIDOS / GESTIÓN VENTAS ---
    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📜 Historial y Gestión de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        df_p = pd.read_sql(query, get_connection())
        
        if df_p.empty: st.write("No hay pedidos registrados.")
        else:
            if user['rol'] == 'admin':
                # Exportación Excel
                buff = io.BytesIO()
                with pd.ExcelWriter(buff, engine='openpyxl') as writer:
                    df_p.to_excel(writer, index=False)
                st.download_button("📥 Descargar Reporte Excel", data=buff.getvalue(), file_name="ventas_color.xlsx")

            for _, p in df_p.iterrows():
                # Obtenemos info extra del cliente desde la tabla usuarios
                info_cli = get_connection().execute("SELECT telefono, direccion FROM usuarios WHERE username=?", (p['username'],)).fetchone()
                tlf = info_cli[0] if info_cli else "N/A"
                dir_cli = info_cli[1] if info_cli else "No registrada"
                
                # Prevenimos error de columna inexistente con .get()
                nom_c = p.get('cliente_nombre', 'Cliente')
                with st.expander(f"Pedido #{p['id']} - {nom_c} | {p['fecha']} | ${p['total']:.2f}"):
                    c_det, c_cli = st.columns([2, 1])
                    with c_det:
                        st.write(f"**Pago:** {p.get('metodo_pago', 'N/A')}")
                        st.table(pd.DataFrame(json.loads(p['items'])))
                    with c_cli:
                        st.info(f"**Datos del Cliente:**\n\n👤 {nom_c}\n\n📧 {p['username']}\n\n📞 {tlf}\n\n📍 {dir_cli}")
                    
                    if user['rol'] == 'admin':
                        nst = st.selectbox("Estatus", ["Pendiente", "Pagado", "Enviado"], key=f"s_{p['id']}")
                        if st.button("Actualizar", key=f"b_{p['id']}"):
                            get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (nst, p['id']))
                            get_connection().commit(); st.rerun()

    # --- MÓDULO CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Catálogo PDF")
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Procesar"):
            with st.spinner("Leyendo..."):
                with open("temp.pdf", "wb") as file: file.write(f.getbuffer())
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
                st.success("Actualizado."); st.cache_data.clear(); time.sleep(1); st.rerun()

    # --- MÓDULO CLIENTES ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        clientes = pd.read_sql("SELECT username, nombre, telefono, direccion FROM usuarios WHERE rol='cliente'", get_connection())
        st.dataframe(clientes, use_container_width=True)
        with st.form("reg"):
            st.write("Registrar Nuevo Cliente")
            c1, c2 = st.columns(2)
            u_n, p_n = c1.text_input("Usuario/Email"), c2.text_input("Clave")
            n_n, t_n = c1.text_input("Nombre Empresa"), c2.text_input("Teléfono")
            d_n = st.text_area("Dirección de Entrega")
            if st.form_submit_button("Guardar"):
                get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (u_n, p_n, n_n, 'cliente', d_n, t_n))
                get_connection().commit(); st.success("Creado."); st.rerun()