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
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Usuario Administrador por defecto
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
            user_id = st.session_state.user_data['user']
            # Inicializar carrito del usuario si no existe
            if user_id not in st.session_state.carritos:
                st.session_state.carritos[user_id] = {}
            
            st.session_state.carritos[user_id][row['sku']] = {
                "desc": row['descripcion'], 
                "p": row['precio'], 
                "c": cant
            }
            st.toast(f"✅ Añadido al carrito")

# --- INICIO DE LA APLICACIÓN ---
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
        else: st.error("Credenciales inválidas")
else:
    user = st.session_state.user_data
    uid = user['user']
    
    # Asegurar que el carrito del usuario actual esté listo
    if uid not in st.session_state.carritos:
        st.session_state.carritos[uid] = {}

    with st.sidebar:
        st.header(f"📦 {user['nombre']}")
        # Mostrar conteo individual en el menú
        cant_items = len(st.session_state.carritos[uid])
        opciones = ["🛍️ Tienda", f"🛒 Carrito ({cant_items})", "📜 Mis Pedidos"]
        
        if user['rol'] == 'admin':
            opciones += ["📊 Panel de Control", "📁 Cargar Inventario", "👥 Clientes"]
        
        menu = st.radio("Navegación", opciones)
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    # --- LÓGICA DE TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 0.5])
            busq = c1.text_input("🔍 Buscar por SKU o Descripción...")
            conn = get_connection()
            res_cats = conn.execute("SELECT DISTINCT categoria FROM productos").fetchall()
            cat_sel = c2.selectbox("📂 Categoría", ["Todas"] + sorted([r[0] for r in res_cats]))
            if c3.button("🔄 Reset"): st.rerun()

        if not busq and cat_sel == "Todas":
            st.info("💡 Utiliza el buscador o selecciona una categoría para ver los productos.")
        else:
            df = cargar_catalogo()
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]
            
            if df.empty: st.warning("No hay coincidencias.")
            else:
                cols = st.columns(4)
                for i, (_, row) in enumerate(df.iterrows()):
                    with cols[i % 4]: card_producto(row, i)

    # --- LÓGICA DE CARRITO CON DESCUENTOS ---
    elif "🛒" in menu:
        st.title("🛒 Mi Carrito de Compras")
        carrito = st.session_state.carritos[uid]
        
        if not carrito:
            st.warning("El carrito está vacío.")
        else:
            total_bruto = 0
            lista_items = []
            for sku, info in list(carrito.items()):
                sub = info['p'] * info['c']
                total_bruto += sub
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 1, 0.5])
                    col1.write(f"**{sku}**\n{info['desc']}")
                    col2.write(f"{info['c']} x ${info['p']:.2f} = **${sub:.2f}**")
                    if col3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[uid][sku]
                        st.rerun()
                lista_items.append({"sku": sku, "desc": info['desc'], "cant": info['c'], "precio": info['p']})

            st.divider()
            c_pago, c_tot = st.columns(2)
            
            with c_pago:
                st.subheader("Opciones de Pago")
                pago_divisas = st.toggle("Pagar en Divisas (Efectivo/Zelle) -10%")
            
            with c_tot:
                # Aplicación de descuentos
                desc_volumen = 0.10 if total_bruto > 100 else 0
                desc_metodo = 0.10 if pago_divisas else 0
                desc_total_pct = (desc_volumen + desc_metodo) * 100
                total_neto = total_bruto * (1 - (desc_volumen + desc_metodo))
                
                st.write(f"Subtotal: ${total_bruto:.2f}")
                if desc_total_pct > 0:
                    st.success(f"Descuento Aplicado: {desc_total_pct:.0f}%")
                st.write(f"## Total Final: ${total_neto:.2f}")

            if st.button("✅ Confirmar y Enviar Pedido", type="primary", use_container_width=True):
                get_connection().execute(
                    "INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                    (uid, datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(lista_items), total_neto, "Pendiente")
                )
                get_connection().commit()
                st.session_state.carritos[uid] = {} # Vaciar solo el de este usuario
                st.success("¡Pedido registrado exitosamente!")
                time.sleep(1); st.rerun()

    # --- GESTIÓN DE PEDIDOS Y REPORTES ---
    elif "Pedidos" in menu:
        st.title("📜 Historial de Pedidos")
        # Si es admin ve todo, si no, solo lo suyo
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        df_p = pd.read_sql(query, get_connection())
        
        if df_p.empty:
            st.write("No hay pedidos registrados aún.")
        else:
            if user['rol'] == 'admin':
                # Botón de Excel para el Admin
                buff = io.BytesIO()
                with pd.ExcelWriter(buff, engine='openpyxl') as writer:
                    df_p.to_excel(writer, index=False)
                st.download_button("📥 Descargar Reporte Excel", data=buff.getvalue(), file_name="pedidos_color_insumos.xlsx")
            
            for _, p in df_p.iterrows():
                status_color = "🔵" if p['status'] == "Pendiente" else "🟢"
                with st.expander(f"{status_color} Pedido #{p['id']} - {p['username']} - {p['fecha']} - Total: ${p['total']:.2f}"):
                    items_df = pd.DataFrame(json.loads(p['items']))
                    st.table(items_df)
                    
                    if user['rol'] == 'admin':
                        c_st, c_bt = st.columns(2)
                        nuevo_st = c_st.selectbox("Actualizar Estado", ["Pendiente", "Procesado", "Pagado", "Enviado"], key=f"s_{p['id']}")
                        if c_bt.button("Guardar Cambio", key=f"b_{p['id']}"):
                            get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (nuevo_st, p['id']))
                            get_connection().commit(); st.rerun()

    # --- CARGA PDF (SOLO ADMIN) ---
    elif menu == "📁 Cargar Inventario":
        st.title("📁 Importación desde PDF Pointer")
        f = st.file_uploader("Subir Lista", type="pdf")
        if f and st.button("Procesar"):
            with st.spinner("Leyendo productos..."):
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
                                        conn.execute("""INSERT INTO productos (sku, descripcion, precio, categoria) 
                                                     VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio""", 
                                                     (sku, desc, prec, "General"))
                                except: pass
                conn.commit()
                st.success("Inventario actualizado."); time.sleep(1); st.rerun()

    # --- GESTIÓN CLIENTES (SOLO ADMIN) ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        clientes = pd.read_sql("SELECT username, nombre, telefono FROM usuarios WHERE rol='cliente'", get_connection())
        st.dataframe(clientes, use_container_width=True)
        with st.form("registro_cliente"):
            st.write("Registrar nuevo cliente")
            c1, c2 = st.columns(2)
            nu = c1.text_input("Usuario (Email)")
            np = c2.text_input("Clave Temporal")
            nn = c1.text_input("Nombre / Empresa")
            nt = c2.text_input("Teléfono")
            if st.form_submit_button("Registrar"):
                get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (nu, np, nn, 'cliente', '', nt))
                get_connection().commit(); st.success("Cliente creado"); st.rerun()