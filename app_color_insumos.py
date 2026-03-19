import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import re
import shutil
from datetime import datetime
from io import BytesIO
from fpdf import FPDF 

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")
CARPETAS_IMPORTAR = [os.path.join(BASE_DIR, "importar_fotos"), os.path.join(BASE_DIR, "importar_fotos2")]

os.makedirs(IMG_DIR, exist_ok=True)
for carpeta in CARPETAS_IMPORTAR: os.makedirs(carpeta, exist_ok=True)

st.set_page_config(page_title="Color Insumos - ERP Maestro", layout="wide")

# --- ESTILOS CSS PARA DISEÑO COMPACTO ---
st.markdown("""
    <style>
    .compact-row {
        padding: 5px 15px;
        border-bottom: 1px solid #eee;
        display: flex;
        align-items: center;
    }
    .stImage > img {
        object-fit: cover;
        height: 60px !important;
        width: 60px !important;
        border-radius: 5px;
    }
    .totalizer-bar {
        background-color: #f8f9fa;
        padding: 10px 20px;
        border-radius: 8px;
        margin-bottom: 15px;
        border: 1px solid #dee2e6;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .sku-text { font-weight: bold; color: #1f77b4; margin-bottom: 0; }
    .desc-text { font-size: 0.9rem; color: #666; margin-bottom: 0; }
    </style>
    """, unsafe_allow_html=True)

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, 
                  direccion TEXT, telefono TEXT, rif TEXT, ciudad TEXT, notas TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, cliente_nombre TEXT, fecha TEXT, 
                  items TEXT, metodo_pago TEXT, subtotal REAL, descuento REAL, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carritos (username TEXT PRIMARY KEY, data TEXT)''')
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- FUNCIONES DE APOYO ---
def auto_categorizar(descripcion):
    desc = descripcion.lower()
    if any(x in desc for x in ['papel', 'lapiz', 'boligrafo', 'cuaderno', 'resma', 'sacapunta']): return "Papelería"
    if any(x in desc for x in ['tinta', 'toner', 'cartucho', 'ink']): return "Consumibles"
    if any(x in desc for x in ['impresora', 'pc', 'mouse', 'teclado', 'usb']): return "Tecnología"
    return "Otros"

def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try: return float(clean)
    except: return 0.0

def guardar_carrito_db(username, carrito_dict):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carritos (username, data) VALUES (?, ?)", (username, json.dumps(carrito_dict)))
    conn.commit()

def cargar_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT data FROM carritos WHERE username=?", (username,)).fetchone()
    return json.loads(res[0]) if res else {}

def generar_pdf_recibo(pedido):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, f"COLOR INSUMOS - Pedido #{pedido['id']}", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 7, f"Cliente: {pedido['cliente_nombre']} | Fecha: {pedido['fecha']}", ln=True)
    pdf.cell(200, 7, f"Metodo: {pedido['metodo_pago']}", ln=True)
    pdf.ln(5)
    items = json.loads(pedido['items'])
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(80, 8, "Descripcion", 1, 0, 'C', True)
    pdf.cell(20, 8, "Cant", 1, 0, 'C', True)
    pdf.cell(40, 8, "Precio", 1, 0, 'C', True)
    pdf.cell(40, 8, "Total", 1, 1, 'C', True)
    for sku, d in items.items():
        pdf.cell(80, 8, f" {sku}", 1)
        pdf.cell(20, 8, str(d['c']), 1, 0, 'C')
        pdf.cell(40, 8, f" ${d['p']:.2f}", 1, 0, 'R')
        pdf.cell(40, 8, f" ${(d['p']*d['c']):.2f}", 1, 1, 'R')
    pdf.ln(5)
    pdf.cell(140, 8, "TOTAL:", 0, 0, 'R')
    pdf.cell(40, 8, f"${pedido['total']:.2f}", 1, 1, 'R', True)
    return pdf.output(dest='S').encode('latin-1')

def vincular_imagenes_locales():
    conn = get_connection()
    exito = 0
    extensiones = ('.png', '.jpg', '.jpeg', '.webp')
    for ruta_carpeta in CARPETAS_IMPORTAR:
        if not os.path.exists(ruta_carpeta): continue
        for archivo in os.listdir(ruta_carpeta):
            if archivo.lower().endswith(extensiones):
                sku_archivo = os.path.splitext(archivo)[0].strip()
                existe = conn.execute("SELECT sku FROM productos WHERE sku = ?", (sku_archivo,)).fetchone()
                if existe:
                    ext = os.path.splitext(archivo)[1]
                    nombre_final = f"{re.sub(r'[\\\\/*?:\"<>|]', '_', sku_archivo)}{ext}"
                    ruta_destino = os.path.join(IMG_DIR, nombre_final)
                    shutil.copy(os.path.join(ruta_carpeta, archivo), ruta_destino)
                    conn.execute("UPDATE productos SET foto_path = ? WHERE sku = ?", (ruta_destino, sku_archivo))
                    exito += 1
    conn.commit()
    return exito

# --- INICIO APLICACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    uid = user['user']
    carrito_usuario = cargar_carrito_db(uid)
    subtotal_v = sum(d['p'] * d['c'] for d in carrito_usuario.values())
    cant_v = sum(d['c'] for d in carrito_usuario.values())

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({cant_v})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Ventas", "📁 Carga", "🖼️ Fotos", "👥 Usuarios"]
        menu = st.radio("Navegación", opc)
        st.divider()
        st.metric("Subtotal Cuenta", f"${subtotal_v:.2f}")
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA HORIZONTAL COMPACTA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        st.markdown(f'<div class="totalizer-bar"><span>Artículos: <b>{cant_v}</b></span><span>Total estimado: <b>${subtotal_v:.2f}</b></span></div>', unsafe_allow_html=True)
        
        c1, c2, c3 = st.columns([3, 2, 1])
        busq = c1.text_input("🔍 Buscar...", key="tienda_search")
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", get_connection())
        cat_sel = c2.selectbox("📂 Rubro", ["Todas"] + df_cats['categoria'].tolist())
        if c3.button("✖️ Limpiar", use_container_width=True): st.rerun()

        query = "SELECT * FROM productos WHERE 1=1"
        params = []
        if cat_sel != "Todas": query += " AND categoria = ?"; params.append(cat_sel)
        if busq: query += " AND (descripcion LIKE ? OR sku LIKE ?)"; params.extend([f"%{busq}%", f"%{busq}%"])
        
        df = pd.read_sql(query, get_connection(), params=params)

        if df.empty:
            st.info("No hay productos. Intenta con otra búsqueda.")
        else:
            items_pag = 15
            total_p = (len(df) // items_pag) + (1 if len(df) % items_pag > 0 else 0)
            p_sel = st.number_input(f"Página (de {total_p})", 1, total_p, 1)
            
            # Encabezado de tabla
            st.markdown("---")
            h1, h2, h3, h4 = st.columns([1, 4, 1.5, 2])
            h1.write("**Foto**")
            h2.write("**Producto / Descripción**")
            h3.write("**Precio**")
            h4.write("**Acción**")
            st.markdown("---")

            for row in df.iloc[(p_sel-1)*items_pag : p_sel*items_pag].itertuples():
                r1, r2, r3, r4 = st.columns([1, 4, 1.5, 2])
                with r1:
                    img = row.foto_path if row.foto_path and os.path.exists(row.foto_path) else "https://via.placeholder.com/60"
                    st.image(img)
                with r2:
                    st.markdown(f'<p class="sku-text">{row.sku}</p>', unsafe_allow_html=True)
                    st.markdown(f'<p class="desc-text">{row.descripcion[:80]}</p>', unsafe_allow_html=True)
                r3.markdown(f"#### ${row.precio:.2f}")
                
                # Controles compactos
                b1, b2, b3 = r4.columns([1, 1, 1])
                if b1.button("➖", key=f"t_m_{row.sku}"):
                    if row.sku in carrito_usuario:
                        if carrito_usuario[row.sku]['c'] > 1: carrito_usuario[row.sku]['c'] -= 1
                        else: del carrito_usuario[row.sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                
                val = carrito_usuario[row.sku]['c'] if row.sku in carrito_usuario else 0
                b2.write(f"**{val}**")
                
                if b3.button("➕", key=f"t_p_{row.sku}"):
                    if row.sku in carrito_usuario: carrito_usuario[row.sku]['c'] += 1
                    else: carrito_usuario[row.sku] = {"desc": row.descripcion, "p": row.precio, "c": 1}
                    guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO CARRITO (CORREGIDO) ---
    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Mi Carrito")
        if not carrito_usuario:
            st.info("El carrito está vacío.")
        else:
            for sku, data in list(carrito_usuario.items()):
                with st.container(border=True):
                    cr1, cr2, cr3, cr4 = st.columns([4, 2, 2, 1])
                    cr1.write(f"**{sku}**\n{data['desc']}")
                    cr2.write(f"Precio: ${data['p']:.2f}")
                    
                    # Controles de edición sin redirección a tienda
                    cb1, cb2, cb3 = cr3.columns([1, 1, 1])
                    if cb1.button("➖", key=f"c_m_{sku}"):
                        if data['c'] > 1:
                            carrito_usuario[sku]['c'] -= 1
                            guardar_carrito_db(uid, carrito_usuario)
                        else:
                            del carrito_usuario[sku]
                            guardar_carrito_db(uid, carrito_usuario)
                        st.rerun() # Esto refresca la pestaña actual (Carrito)

                    cb2.write(f"**{data['c']}**")

                    if cb3.button("➕", key=f"c_p_{sku}"):
                        carrito_usuario[sku]['c'] += 1
                        guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()

                    if cr4.button("🗑️", key=f"c_d_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()

            st.divider()
            metodo = st.radio("Método de Pago:", ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            
            # Reglas de Descuento
            desc = 0.0
            if metodo == "Divisas / Zelle": desc = subtotal_v * 0.30
            elif metodo == "Bolívares (BCV)" and subtotal_v >= 100: desc = subtotal_v * 0.10
            
            total_f = subtotal_v - desc
            st.write(f"Subtotal: ${subtotal_v:.2f} | Descuento: -${desc:.2f}")
            st.header(f"Total: ${total_f:.2f}")
            
            if st.button("🏁 Finalizar y Generar Recibo", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(carrito_usuario), metodo, subtotal_v, desc, total_f, "Pendiente"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("¡Pedido procesado!")
                st.balloons()

    # --- OTROS MÓDULOS (MANTENIDOS) ---
    elif menu == "📊 Ventas":
        st.title("📊 Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in df_p.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['cliente_nombre']}"):
                st.write(f"Fecha: {p['fecha']} | Total: ${p['total']:.2f}")
                st.download_button("Descargar PDF", generar_pdf_recibo(p), f"Recibo_{p['id']}.pdf")

    elif menu == "📁 Carga":
        st.title("📁 Importar PDF")
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Extraer"):
            doc = fitz.open(stream=f.read(), filetype="pdf")
            conn = get_connection()
            for page in doc:
                for tab in page.find_tables():
                    for _, r in tab.to_pandas().iterrows():
                        sku, desc = str(r.iloc[0]).strip(), str(r.iloc[2]).strip()
                        pre = limpiar_precio(r.iloc[4])
                        if len(sku) > 2:
                            conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, categoria=excluded.categoria", (sku, desc, pre, auto_categorizar(desc)))
            conn.commit(); st.success("Cargado")

    elif menu == "🖼️ Fotos":
        st.title("🖼️ Sincronizar Imágenes")
        if st.button("Vincular"):
            n = vincular_imagenes_locales()
            st.success(f"Vinculadas {n} fotos.")

    elif menu == "👥 Usuarios":
        st.title("👥 Usuarios")
        df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
        st.table(df_u)