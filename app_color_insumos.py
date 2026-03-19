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
        padding: 15px;
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

# --- LÓGICA DE CATEGORIZACIÓN ---
def auto_categorizar(descripcion):
    desc = descripcion.lower()
    if any(kw in desc for kw in ["lapiz", "boligrafo", "pluma", "portamina", "marcador", "resaltador", "tiza", "mina"]):
        return "Escritura y Trazo"
    if any(kw in desc for kw in ["pega", "silicon", "cinta", "adhesivo", "clip", "grapa", "grapadora", "liga", "sujetador"]):
        return "Adhesivos y Sujeción"
    if any(kw in desc for kw in ["tijera", "exacto", "cutter", "regla", "escuadra", "compas", "escalimetro"]):
        return "Corte y Medición"
    if any(kw in desc for kw in ["color", "pintura", "tempera", "acuarela", "pincel", "plastilina", "acrilico", "frio", "lienzo"]):
        return "Expresión Artística"
    if any(kw in desc for kw in ["resma", "papel", "cartulina", "foami", "block", "cuaderno", "libreta", "sobre", "carpeta"]):
        return "Soportes y Papelería"
    if any(kw in desc for kw in ["borrador", "sacapunta", "corrector", "funda", "estuche", "morral", "archivo", "etiqueta"]):
        return "Organización y Accesorios"
    return "Misceláneos Pointer"

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

# --- GENERACIÓN DE REPORTES PROFESIONALES ---
def generar_pdf_recibo(pedido, conn):
    # Extraer datos completos del cliente
    u_data = conn.execute("SELECT rif, telefono, direccion FROM usuarios WHERE username=?", (pedido['username'],)).fetchone()
    c_rif = u_data[0] if u_data and u_data[0] else "No registrado"
    c_tel = u_data[1] if u_data and u_data[1] else "No registrado"
    c_dir = u_data[2] if u_data and u_data[2] else "No registrada"

    pdf = FPDF()
    pdf.add_page()
    
    # Encabezado Corporativo Color Insumos
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(200, 8, "COLOR INSUMOS", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 5, "Servicio Técnico y Papelería al Mayor y Detal", ln=True, align='C')
    pdf.cell(200, 5, "Web: colorinsumos.com | Tel: 0412-6901346 / 0412-7757053", ln=True, align='C')
    pdf.ln(8)
    
    # Datos del Pedido
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(200, 8, f" RECIBO DE PEDIDO #{pedido['id']} - {pedido['status'].upper()}", ln=True, fill=True)
    
    # Datos del Cliente
    pdf.set_font("Arial", size=10)
    pdf.cell(100, 6, f" Cliente: {pedido['cliente_nombre']}", ln=False)
    pdf.cell(100, 6, f" Fecha: {pedido['fecha']}", ln=True)
    pdf.cell(100, 6, f" RIF/CI: {c_rif}", ln=False)
    pdf.cell(100, 6, f" Telefono: {c_tel}", ln=True)
    pdf.cell(200, 6, f" Direccion: {c_dir}", ln=True)
    pdf.cell(200, 6, f" Metodo de Pago: {pedido['metodo_pago']}", ln=True)
    pdf.ln(5)
    
    # Tabla de Artículos
    items = json.loads(pedido['items'])
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(30, 8, "SKU", 1, 0, 'C', True)
    pdf.cell(85, 8, "Descripcion", 1, 0, 'C', True)
    pdf.cell(15, 8, "Cant", 1, 0, 'C', True)
    pdf.cell(30, 8, "Precio U.", 1, 0, 'C', True)
    pdf.cell(30, 8, "Subtotal", 1, 1, 'C', True)
    
    pdf.set_font("Arial", size=9)
    for sku, d in items.items():
        desc_corta = d['desc'][:45] + "..." if len(d['desc']) > 45 else d['desc']
        pdf.cell(30, 8, f" {sku}", 1)
        pdf.cell(85, 8, f" {desc_corta}", 1)
        pdf.cell(15, 8, str(d['c']), 1, 0, 'C')
        pdf.cell(30, 8, f" ${d['p']:.2f}", 1, 0, 'R')
        pdf.cell(30, 8, f" ${(d['p']*d['c']):.2f}", 1, 1, 'R')
    
    # Totalizaciones
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(130, 8, "", 0, 0)
    pdf.cell(30, 8, "Subtotal:", 1, 0, 'R')
    pdf.cell(30, 8, f"${pedido['subtotal']:.2f}", 1, 1, 'R')
    
    pdf.cell(130, 8, "", 0, 0)
    pdf.cell(30, 8, "Descuento:", 1, 0, 'R')
    pdf.cell(30, 8, f"-${pedido['descuento']:.2f}", 1, 1, 'R')
    
    pdf.cell(130, 8, "", 0, 0)
    pdf.set_fill_color(200, 255, 200)
    pdf.cell(30, 8, "TOTAL FINAL:", 1, 0, 'R', True)
    pdf.cell(30, 8, f"${pedido['total']:.2f}", 1, 1, 'R', True)
    
    # CORRECCIÓN: fpdf2 ya genera un bytearray, solo lo aseguramos como bytes para Streamlit
    return bytes(pdf.output())

def generar_excel_recibo(pedido):
    items = json.loads(pedido['items'])
    datos = []
    for sku, d in items.items():
        datos.append({
            "SKU": sku,
            "Descripción": d['desc'],
            "Precio Unitario ($)": d['p'],
            "Cantidad": d['c'],
            "Subtotal ($)": d['p'] * d['c']
        })
    df = pd.DataFrame(datos)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=f"Pedido_{pedido['id']}")
    return output.getvalue()

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

    # --- VENTANA FLOTANTE EN SIDEBAR ---
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

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo Pointer por Funcionalidad")
        
        c1, c2, c3 = st.columns([3, 2, 1])
        busq = c1.text_input("🔍 Buscar (SKU o descripción)", key="tienda_search")
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", get_connection())
        cat_sel = c2.selectbox("📂 Filtrar por Tipo de Artículo", ["Todos"] + df_cats['categoria'].tolist())
        if c3.button("✖️ Reset", use_container_width=True): st.rerun()

        query = "SELECT * FROM productos WHERE 1=1"
        params = []
        if cat_sel != "Todos": query += " AND categoria = ?"; params.append(cat_sel)
        if busq: query += " AND (descripcion LIKE ? OR sku LIKE ?)"; params.extend([f"%{busq}%", f"%{busq}%"])
        
        df = pd.read_sql(query, get_connection(), params=params)

        if df.empty:
            st.info("No se encontraron productos.")
        else:
            items_pag = 20
            total_p = (len(df) // items_pag) + (1 if len(df) % items_pag > 0 else 0)
            p_sel = st.number_input(f"Página", 1, total_p, 1)
            
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
                        st.markdown('<span class="in-cart-indicator">✅ En carrito</span>', unsafe_allow_html=True)
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
                
                if b4.button("🗑️", key=f"t_del_{row.sku}"):
                    if row.sku in carrito_usuario:
                        del carrito_usuario[row.sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                st.markdown("<hr style='margin:5px 0; border-color:#f9f9f9'>", unsafe_allow_html=True)

    # --- MÓDULO CARRITO ---
    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Carrito de Compras")
        if not carrito_usuario:
            st.info("El carrito está vacío.")
        else:
            for sku, data in list(carrito_usuario.items()):
                with st.container():
                    cr1, cr2, cr3, cr4 = st.columns([4, 2, 2, 1])
                    cr1.write(f"**{sku}**\n{data['desc']}")
                    cr2.write(f"${data['p']:.2f}")
                    cb1, cb2, cb3 = cr3.columns([1, 1, 1])
                    if cb1.button("➖", key=f"c_m_{sku}"):
                        if data['c'] > 1: carrito_usuario[sku]['c'] -= 1
                        else: del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    cb2.write(f"**{data['c']}**")
                    if cb3.button("➕", key=f"c_p_{sku}"):
                        carrito_usuario[sku]['c'] += 1
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    if cr4.button("🗑️", key=f"c_d_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                st.markdown("---")

            metodo = st.radio("Método de Pago:", ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            desc = (subtotal_v * 0.30) if metodo == "Divisas / Zelle" else ((subtotal_v * 0.10) if subtotal_v >= 100 else 0)
            total_f = subtotal_v - desc
            st.write(f"Subtotal: ${subtotal_v:.2f} | Descuento: -${desc:.2f}")
            st.header(f"Total Final: ${total_f:.2f}")
            
            if st.button("🏁 Confirmar Pedido", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(carrito_usuario), metodo, subtotal_v, desc, total_f, "Pendiente"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("Pedido enviado con éxito.")
                st.balloons()

    # --- HISTORIAL Y GESTIÓN DE MIS PEDIDOS ---
    elif menu == "📜 Mis Pedidos":
        st.title("📜 Mis Pedidos")
        st.write("Gestiona, visualiza y descarga los soportes de tus pedidos realizados.")
        conn = get_connection()
        df_mis = pd.read_sql("SELECT * FROM pedidos WHERE username=? ORDER BY id DESC", conn, params=(uid,))
        
        if df_mis.empty:
            st.info("Aún no tienes pedidos registrados en el sistema.")
        else:
            for _, p_row in df_mis.iterrows():
                with st.expander(f"📦 Pedido #{p_row['id']} | Fecha: {p_row['fecha']} | Total: ${p_row['total']:.2f}"):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Estado:** {p_row['status']}")
                    c1.write(f"**Método de Pago:** {p_row['metodo_pago']}")
                    c2.write(f"**Subtotal:** ${p_row['subtotal']:.2f}")
                    c2.write(f"**Descuento:** -${p_row['descuento']:.2f}")
                    
                    st.markdown("**Artículos del pedido:**")
                    st.json(json.loads(p_row['items']))
                    
                    st.divider()
                    col_pdf, col_xls, col_del = st.columns(3)
                    
                    # Generación de reportes
                    pdf_bytes = generar_pdf_recibo(p_row, conn)
                    xls_bytes = generar_excel_recibo(p_row)
                    
                    col_pdf.download_button("📄 Descargar Recibo PDF", pdf_bytes, f"Recibo_ColorInsumos_P{p_row['id']}.pdf")
                    col_xls.download_button("📊 Exportar Detalles Excel", xls_bytes, f"Detalle_Pedido_{p_row['id']}.xlsx")
                    
                    if col_del.button("🗑️ Eliminar Pedido", key=f"del_mi_p_{p_row['id']}"):
                        conn.execute("DELETE FROM pedidos WHERE id=?", (p_row['id'],))
                        conn.commit()
                        st.success("Pedido eliminado correctamente."); st.rerun()

    # --- ADMINISTRACIÓN DE VENTAS ---
    elif menu == "📊 Ventas":
        st.title("📊 Control de Ventas General")
        conn = get_connection()
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn)
        st.dataframe(df_p)
        # Opcional: Podrías añadir la exportación general aquí también en el futuro.

    elif menu == "📁 Carga":
        st.title("📁 Gestión de Catálogo")
        
        if st.button("🔄 Aplicar Categorización Técnica Pointer"):
            conn = get_connection()
            productos = conn.execute("SELECT sku, descripcion FROM productos").fetchall()
            for sku, desc in productos:
                nueva_cat = auto_categorizar(desc)
                conn.execute("UPDATE productos SET categoria = ? WHERE sku = ?", (nueva_cat, sku))
            conn.commit()
            st.success("Inventario reclasificado por funcionalidad técnica.")
            st.rerun()

        f = st.file_uploader("Cargar Catálogo PDF Pointer", type="pdf")
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
                                conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, categoria=excluded.categoria", (sku, desc, pre, auto_categorizar(desc)))
                        except: continue
            conn.commit()
            st.success("Catálogo cargado y categorizado.")

    elif menu == "🖼️ Fotos":
        st.title("🖼️ Vinculación de Fotos")
        if st.button("Sincronizar Galería Local"):
            n = vincular_imagenes_locales()
            st.success(f"Se vincularon {n} imágenes.")

    # --- ADMINISTRACIÓN DE USUARIOS (CRUD COMPLETO) ---
    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Clientes y Usuarios")
        t_lista, t_nuevo = st.tabs(["📋 Directorio y Edición", "➕ Registrar Nuevo Cliente"])
        conn = get_connection()
        
        with t_lista:
            df_u = pd.read_sql("SELECT * FROM usuarios", conn)
            st.write("Selecciona un usuario para ver, editar sus detalles o eliminarlo de la base de datos.")
            for _, u_row in df_u.iterrows():
                with st.expander(f"👤 {u_row['nombre']} | ID: {u_row['username']} | Rol: {u_row['rol'].upper()}"):
                    with st.form(f"form_edit_{u_row['username']}"):
                        st.markdown("### Modificar Datos")
                        c1, c2, c3 = st.columns(3)
                        n_nom = c1.text_input("Nombre / Razón Social", u_row['nombre'])
                        n_rif = c2.text_input("RIF / Cédula", u_row['rif'] if u_row['rif'] else "")
                        n_tel = c3.text_input("Teléfono", u_row['telefono'] if u_row['telefono'] else "")
                        
                        c4, c5 = st.columns([2, 1])
                        n_dir = c4.text_input("Dirección de Despacho", u_row['direccion'] if u_row['direccion'] else "")
                        n_ciu = c5.text_input("Ciudad", u_row['ciudad'] if u_row['ciudad'] else "")
                        
                        c6, c7 = st.columns([2, 1])
                        n_not = c6.text_area("Notas Especiales (Descuentos, horarios, etc.)", u_row['notas'] if u_row['notas'] else "")
                        n_rol = c7.selectbox("Nivel de Acceso", ["cliente", "admin"], index=0 if u_row['rol']=="cliente" else 1)
                        
                        col_btn1, col_btn2 = st.columns([1, 1])
                        if col_btn1.form_submit_button("💾 Guardar Cambios", use_container_width=True):
                            conn.execute("UPDATE usuarios SET nombre=?, rif=?, telefono=?, direccion=?, ciudad=?, notas=?, rol=? WHERE username=?", 
                                         (n_nom, n_rif, n_tel, n_dir, n_ciu, n_not, n_rol, u_row['username']))
                            conn.commit()
                            st.success("Perfil actualizado con éxito."); st.rerun()
                    
                    if u_row['username'] != 'colorinsumos@gmail.com':
                        if st.button("❌ Eliminar Permanentemente", key=f"del_user_{u_row['username']}"):
                            conn.execute("DELETE FROM usuarios WHERE username=?", (u_row['username'],))
                            conn.commit()
                            st.warning("Cliente eliminado."); st.rerun()

        with t_nuevo:
            with st.form("form_crear_usuario"):
                st.markdown("### Datos del Nuevo Cliente")
                c1, c2 = st.columns(2)
                nu_usr = c1.text_input("Correo / ID de Usuario *")
                nu_pwd = c2.text_input("Contraseña de Acceso *", type="password")
                
                c3, c4, c5 = st.columns([2, 1, 1])
                nu_nom = c3.text_input("Nombre Completo o Empresa *")
                nu_rif = c4.text_input("RIF / CI")
                nu_tel = c5.text_input("Teléfono")
                
                c6, c7 = st.columns([3, 1])
                nu_dir = c6.text_input("Dirección Exacta")
                nu_ciu = c7.text_input("Ciudad")
                
                nu_not = st.text_area("Notas u Observaciones del Cliente")
                nu_rol = st.selectbox("Asignar Rol", ["cliente", "admin"])
                
                st.markdown("*Campos obligatorios*")
                if st.form_submit_button("✅ Registrar en el Sistema", type="primary"):
                    if nu_usr and nu_pwd and nu_nom:
                        try:
                            conn.execute("INSERT INTO usuarios (username, password, nombre, rol, direccion, telefono, rif, ciudad, notas) VALUES (?,?,?,?,?,?,?,?,?)",
                                         (nu_usr, nu_pwd, nu_nom, nu_rol, nu_dir, nu_tel, nu_rif, nu_ciu, nu_not))
                            conn.commit()
                            st.success(f"El cliente {nu_nom} ha sido registrado correctamente.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Error: Ese ID de usuario o correo ya está en uso.")
                    else:
                        st.warning("Por favor, completa los campos marcados con asterisco (*).")