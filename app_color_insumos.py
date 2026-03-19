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

# --- ESTILOS CSS ACTUALIZADOS ---
st.markdown("""
    <style>
    .stImage > img {
        object-fit: cover;
        height: 50px !important;
        width: 50px !important;
        border-radius: 5px;
    }
    .floating-totalizer {
        background-color: #ffffff;
        padding: 15 padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
        color: #000000 !important;
    }
    .floating-totalizer p, .floating-totalizer b, .floating-totalizer span {
        color: #000000 !important;
        margin: 0;
    }
    .sku-text { font-weight: bold; color: #1f77b4; margin-bottom: 0; font-size: 0.85rem; }
    .desc-text { font-size: 0.8rem; color: #444; margin-bottom: 0; line-height: 1.1; }
    .in-cart-indicator { color: #28a745; font-weight: bold; font-size: 0.8rem; }
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
    
    # 1. Escritura y Corrección
    if any(kw in desc for kw in ["lapiz", "boligrafo", "marcador", "resaltador", "corrector", "sacapunta", "borrador", "mina"]):
        return "Escritura y Corrección"
    
    # 2. Arte y Color
    if any(kw in desc for kw in ["color", "pintura", "tempera", "acuarela", "pincel", "plastilina", "frio", "acrilico"]):
        return "Arte y Color"
        
    # 3. Papelería y Oficina
    if any(kw in desc for kw in ["resma", "clip", "carpeta", "grapadora", "grapa", "liga", "sobre", "cinta", "pega", "silicon"]):
        return "Papelería y Oficina"
        
    # 4. Escolar y Didáctico
    if any(kw in desc for kw in ["cuaderno", "libreta", "morral", "regla", "compas", "tijera", "juego", "didactico", "block"]):
        return "Escolar y Didáctico"
            
    return "Varios Pointer"

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

    # --- VENTANA FLOTANTE EN SIDEBAR (DETALLADA) ---
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({cant_v})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Ventas", "📁 Carga", "🖼️ Fotos", "👥 Usuarios"]
        menu = st.radio("Navegación", opc)
        
        st.markdown("### 💳 Resumen de Cuenta")
        with st.container():
            dcto_bcv = (subtotal_v * 0.10 if subtotal_v >= 100 else 0)
            dcto_zelle = (subtotal_v * 0.30)
            st.markdown(f"""
                <div class="floating-totalizer">
                    <p>Items: <b>{cant_v}</b></p>
                    <p>Subtotal: <b>${subtotal_v:.2f}</b></p>
                    <hr style='margin:10px 0; border-color:#eee'>
                    <p style='font-size:0.8rem; font-weight:bold'>Dctos. según pago:</p>
                    <p style='font-size:0.85rem'>🔹 BCV: <span style='color:#d9534f'>-${dcto_bcv:.2f}</span></p>
                    <p style='font-size:0.85rem'>🔹 Zelle: <span style='color:#5cb85c'>-${dcto_zelle:.2f}</span></p>
                    <hr style='margin:10px 0; border-color:#eee'>
                    <p style='font-size:0.9rem'>Total BCV: <b>${(subtotal_v - dcto_bcv):.2f}</b></p>
                </div>
            """, unsafe_allow_html=True)
            
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO TIENDA HORIZONTAL ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        
        c1, c2, c3 = st.columns([3, 2, 1])
        busq = c1.text_input("🔍 ¿Qué buscas hoy? (SKU o nombre)", key="tienda_search")
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", get_connection())
        cat_sel = c2.selectbox("📂 Explorar por Segmento", ["Todos los artículos"] + df_cats['categoria'].tolist())
        if c3.button("✖️ Limpiar Vista", use_container_width=True): st.rerun()

        query = "SELECT * FROM productos WHERE 1=1"
        params = []
        if cat_sel != "Todos los artículos": query += " AND categoria = ?"; params.append(cat_sel)
        if busq: query += " AND (descripcion LIKE ? OR sku LIKE ?)"; params.extend([f"%{busq}%", f"%{busq}%"])
        
        df = pd.read_sql(query, get_connection(), params=params)

        if df.empty:
            st.info("No se encontraron productos en este segmento.")
        else:
            items_pag = 20
            total_p = (len(df) // items_pag) + (1 if len(df) % items_pag > 0 else 0)
            p_sel = st.number_input(f"Página (Total: {total_p})", 1, total_p, 1)
            
            st.markdown("---")
            for row in df.iloc[(p_sel-1)*items_pag : p_sel*items_pag].itertuples():
                r1, r2, r3, r4 = st.columns([0.8, 4.5, 1.2, 2.5])
                with r1:
                    img = row.foto_path if row.foto_path and os.path.exists(row.foto_path) else "https://via.placeholder.com/60"
                    st.image(img)
                with r2:
                    st.markdown(f'<p class="sku-text">{row.sku} <span style="color:#888; font-weight:normal">| {row.categoria}</span></p>', unsafe_allow_html=True)
                    st.markdown(f'<p class="desc-text">{row.descripcion}</p>', unsafe_allow_html=True)
                    if row.sku in carrito_usuario:
                        st.markdown('<span class="in-cart-indicator">✅ Ya en carrito</span>', unsafe_allow_html=True)
                r3.markdown(f"#### ${row.precio:.2f}")
                
                b1, b2, b3, b4 = r4.columns([0.8, 1, 0.8, 1.2])
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
                
                if b4.button("🗑️", key=f"t_del_{row.sku}", help="Remover"):
                    if row.sku in carrito_usuario:
                        del carrito_usuario[row.sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                st.markdown("<hr style='margin:5px 0; border-color:#f9f9f9'>", unsafe_allow_html=True)

    # --- MÓDULO CARRITO ---
    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Revisión de Pedido")
        if not carrito_usuario:
            st.info("No has agregado artículos aún.")
        else:
            for sku, data in list(carrito_usuario.items()):
                with st.container():
                    cr1, cr2, cr3, cr4 = st.columns([4, 2, 2, 1])
                    cr1.write(f"**{sku}**\n{data['desc']}")
                    cr2.write(f"Unitario: ${data['p']:.2f}")
                    
                    cb1, cb2, cb3 = cr3.columns([1, 1, 1])
                    if cb1.button("➖", key=f"c_m_{sku}"):
                        if data['c'] > 1:
                            carrito_usuario[sku]['c'] -= 1
                            guardar_carrito_db(uid, carrito_usuario)
                        else:
                            del carrito_usuario[sku]
                            guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()

                    cb2.write(f"**{data['c']}**")

                    if cb3.button("➕", key=f"c_p_{sku}"):
                        carrito_usuario[sku]['c'] += 1
                        guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()

                    if cr4.button("🗑️", key=f"c_d_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()
                st.markdown("---")

            metodo = st.radio("Método de Pago:", ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            desc = 0.0
            if metodo == "Divisas / Zelle": desc = subtotal_v * 0.30
            elif metodo == "Bolívares (BCV)" and subtotal_v >= 100: desc = subtotal_v * 0.10
            
            total_f = subtotal_v - desc
            st.write(f"Subtotal: ${subtotal_v:.2f} | Descuento: -${desc:.2f}")
            st.header(f"Total Final: ${total_f:.2f}")
            
            if st.button("🏁 Confirmar Pedido", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(carrito_usuario), metodo, subtotal_v, desc, total_f, "Pendiente"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("Pedido registrado exitosamente.")
                st.balloons()

    # --- GESTIÓN ---
    elif menu == "📊 Ventas":
        st.title("📊 Control de Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        st.dataframe(df_p)

    elif menu == "📁 Carga":
        st.title("📁 Importar Catálogo PDF")
        
        # 1. Botón de Re-organización
        if st.button("🔄 Re-organizar Inventario Pointer"):
            conn = get_connection()
            productos = conn.execute("SELECT sku, descripcion FROM productos").fetchall()
            for sku, desc in productos:
                nueva_cat = auto_categorizar(desc)
                conn.execute("UPDATE productos SET categoria = ? WHERE sku = ?", (nueva_cat, sku))
            conn.commit()
            st.success("¡Catálogo Pointer organizado con éxito!")
            st.rerun()

        # 2. Subida de archivo (PROCESADO ÚNICO)
        f = st.file_uploader("Archivo PDF Maestro", type="pdf")
        if f and st.button("Procesar Inventario"):
            doc = fitz.open(stream=f.read(), filetype="pdf")
            conn = get_connection()
            for page in doc:
                for tab in page.find_tables():
                    for _, r in tab.to_pandas().iterrows():
                        try:
                            sku, desc = str(r.iloc[0]).strip(), str(r.iloc[2]).strip()
                            pre = limpiar_precio(r.iloc[4])
                            if len(sku) > 2:
                                cat = auto_categorizar(desc)
                                conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, categoria=excluded.categoria", (sku, desc, pre, cat))
                        except: continue
            conn.commit()
            st.success("Inventario actualizado y segmentado automáticamente.")

    elif menu == "🖼️ Fotos":
        st.title("🖼️ Sincronización")
        if st.button("Vincular"):
            n = vincular_imagenes_locales()
            st.success(f"Vinculadas {n} fotos.")

    elif menu == "👥 Usuarios":
        st.title("👥 Usuarios")
        df_u = pd.read_sql("SELECT * FROM usuarios", get_connection())
        st.table(df_u)