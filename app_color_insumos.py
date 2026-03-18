import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import io
import json
import time
import re
from datetime import datetime

# --- CONFIGURACIÓN DE RUTAS Y BASE DE DATOS ---
DB_NAME = "catalogo_color_v3.db"
# Usamos rutas absolutas para evitar errores en Streamlit Cloud
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")

if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS (SQLITE) ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    # Tabla de productos con soporte para SKU único
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de usuarios con campos de contacto
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    # Tabla de pedidos para historial
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Usuario administrador por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Oficina Central', '04126901346'))
    conn.commit()

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        .product-card {
            background-color: white;
            padding: 15px;
            border-radius: 12px;
            border: 1px solid #eee;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }
        .product-img { width: 100%; height: 160px; object-fit: contain; border-radius: 8px; }
        .price-tag { color: #1a73e8; font-size: 24px; font-weight: bold; margin: 10px 0; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-thumb { background: #888; border-radius: 4px; }
    </style>
""", unsafe_allow_html=True)

# --- FUNCIONES LÓGICAS ---
def limpiar_precio(texto):
    """Extrae números de cadenas tipo 'Bs. 1.250,50' o '$ 45.00'."""
    if not texto or texto == "None": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        if clean.count('.') > 1:
            parts = clean.split('.')
            clean = "".join(parts[:-1]) + "." + parts[-1]
        return float(clean)
    except: return 0.0

def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA"]): return "🧩 JUEGOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA"]): return "📄 PAPELERÍA"
    return "📦 VARIOS"

@st.cache_data(ttl=300)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

# --- INTERFAZ DE PRODUCTO ---
@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        img_path = row['foto_path']
        if img_path and os.path.exists(img_path):
            st.image(img_path, use_container_width=True)
        else:
            st.image("https://via.placeholder.com/150?text=Sin+Imagen", use_container_width=True)
        
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:70])
        
        cant = st.number_input("Cantidad", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            user_id = st.session_state.user_data['user']
            if user_id not in st.session_state.carritos:
                st.session_state.carritos[user_id] = {}
            
            st.session_state.carritos[user_id][row['sku']] = {
                "desc": row['descripcion'], "p": row['precio'], "c": cant
            }
            st.toast(f"✅ {row['sku']} en carrito")
            time.sleep(0.5); st.rerun()

# --- FLUJO PRINCIPAL ---
init_db()

if 'auth' not in st.session_state: st.session_state.auth = False
if 'carritos' not in st.session_state: st.session_state.carritos = {}

if not st.session_state.auth:
    st.title("🔐 Color Insumos - Acceso")
    with st.form("login"):
        u = st.text_input("Usuario (Email)")
        p = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
            if res:
                st.session_state.auth = True
                st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
                st.rerun()
            else: st.error("Credenciales inválidas")
else:
    user = st.session_state.user_data
    carrito_actual = st.session_state.carritos.get(user['user'], {})
    
    with st.sidebar:
        st.title("Color Insumos")
        st.write(f"Bienvenido, **{user['nombre']}**")
        menu = st.radio("Navegación", ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_actual)})", "📜 Mis Pedidos", "📁 Cargar PDF", "👥 Clientes"])
        if st.button("🚪 Cerrar Sesión"):
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("Catálogo de Productos")
        df = cargar_catalogo()
        if df.empty:
            st.info("El catálogo está vacío. Cargue un PDF en el menú lateral.")
        else:
            busq = st.text_input("🔍 Buscar por nombre o SKU...")
            if busq:
                df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            
            for cat in sorted(df['categoria'].unique()):
                with st.expander(f"{cat}", expanded=True):
                    sub_df = df[df['categoria'] == cat].reset_index()
                    cols = st.columns(4)
                    for i, row in sub_df.iterrows():
                        with cols[i % 4]: card_producto(row, i)

    # --- MÓDULO CARRITO ---
    elif "🛒" in menu:
        st.title("Tu Carrito de Compras")
        if not carrito_actual:
            st.warning("Aún no has añadido productos.")
        else:
            total_usd = 0
            items_pedido = []
            for sku, info in list(carrito_actual.items()):
                sub = info['p'] * info['c']
                total_usd += sub
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"**{sku}** - {info['desc']}")
                    c2.write(f"{info['c']} x ${info['p']:.2f} = **${sub:.2f}**")
                    if c3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[user['user']][sku]
                        st.rerun()
                items_pedido.append({"SKU": sku, "Cant": info['c'], "Precio": info['p'], "Subtotal": sub})

            st.divider()
            pago_divisas = st.toggle("Pagar en Divisas (30% Descuento)")
            
            # Lógica de descuentos excluyentes
            if pago_divisas:
                desc = total_usd * 0.30
                final = total_usd - desc
                st.info(f"✨ Descuento Divisas (30%): -${desc:.2f}")
            elif total_usd > 100:
                desc = total_usd * 0.10
                final = total_usd - desc
                st.success(f"✅ Descuento Mayorista (10%): -${desc:.2f}")
            else:
                final = total_usd
            
            st.write(f"## Total a Pagar: ${final:.2f}")
            if st.button("🚀 Confirmar y Enviar Pedido", type="primary", use_container_width=True):
                get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                             (user['user'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(items_pedido), final, "Pendiente"))
                get_connection().commit()
                st.session_state.carritos[user['user']] = {}
                st.success("¡Pedido realizado con éxito!"); time.sleep(1); st.rerun()

    # --- MÓDULO CARGA PDF (FITZ) ---
    elif menu == "📁 Cargar PDF":
        st.title("Actualizar Inventario desde PDF")
        if user['rol'] != 'admin':
            st.error("Acceso restringido a administradores.")
        else:
            f = st.file_uploader("Subir PDF (SKU - Imagen - Desc - Divisa - BCV)", type="pdf")
            if f and st.button("Procesar Archivo"):
                with st.spinner("Extrayendo datos e imágenes..."):
                    # Guardar temporal
                    with open("temp.pdf", "wb") as tmp: tmp.write(f.getbuffer())
                    
                    doc = fitz.open("temp.pdf")
                    conn = get_connection()
                    count = 0
                    
                    for page in doc:
                        imgs = page.get_images(full=True)
                        tabs = page.find_tables()
                        if tabs:
                            for tab in tabs:
                                df_p = tab.to_pandas()
                                # Detectar columnas dinámicamente
                                col_bcv = next((i for i, c in enumerate(df_p.columns) if "BCV" in str(c).upper()), 4)
                                
                                for row_idx, row in df_p.iterrows():
                                    sku = str(row.iloc[0]).strip()
                                    if len(sku) < 2 or sku.upper() == "SKU": continue
                                    
                                    desc = str(row.iloc[2]).strip()
                                    precio = limpiar_precio(row.iloc[col_bcv])
                                    
                                    # Extraer imagen si existe en la página
                                    foto_path = ""
                                    if imgs and row_idx < len(imgs):
                                        xref = imgs[row_idx][0]
                                        pix = fitz.Pixmap(doc, xref)
                                        f_name = f"{sku}.png"
                                        f_path = os.path.join(IMG_DIR, f_name)
                                        pix.save(f_path)
                                        foto_path = f_path
                                    
                                    cat = obtener_categoria(sku, desc)
                                    conn.execute("""INSERT INTO productos VALUES (?,?,?,?,?) 
                                                 ON CONFLICT(sku) DO UPDATE SET 
                                                 descripcion=excluded.descripcion, precio=excluded.precio, foto_path=excluded.foto_path""",
                                                 (sku, desc, precio, cat, foto_path))
                                    count += 1
                    conn.commit()
                    doc.close()
                    st.success(f"✅ Se cargaron {count} productos correctamente.")
                    st.cache_data.clear(); time.sleep(1); st.rerun()

    # --- MÓDULO CLIENTES ---
    elif menu == "👥 Clientes":
        st.title("Gestión de Clientes")
        if user['rol'] == 'admin':
            with st.form("nuevo_cliente"):
                c1, c2 = st.columns(2)
                id_c = c1.text_input("ID/Email"); nom_c = c2.text_input("Nombre")
                pass_c = c1.text_input("Clave"); tel_c = c2.text_input("Teléfono")
                dir_c = st.text_area("Dirección")
                if st.form_submit_button("Registrar Cliente"):
                    try:
                        get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (id_c, pass_c, nom_c, 'cliente', dir_c, tel_c))
                        get_connection().commit(); st.success("Cliente registrado")
                    except: st.error("El ID ya existe")
            
            st.divider()
            clientes = pd.read_sql("SELECT username, nombre, telefono, direccion FROM usuarios WHERE rol='cliente'", get_connection())
            st.dataframe(clientes, use_container_width=True)
        else:
            st.info("Tus datos de contacto:")
            info = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (user['user'],)).fetchone()
            st.write(f"📍 **Dirección:** {info[4]}")
            st.write(f"📞 **Teléfono:** {info[5]}")

    # --- HISTORIAL PEDIDOS ---
    elif "Pedidos" in menu:
        st.title("Historial de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{user['user']}'"
        peds = pd.read_sql(query, get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} - ${p['total']:.2f}"):
                st.json(json.loads(p['items']))
                if user['rol'] == 'admin':
                    if st.button(f"Eliminar #{p['id']}", key=f"p_{p['id']}"):
                        get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                        get_connection().commit(); st.rerun()