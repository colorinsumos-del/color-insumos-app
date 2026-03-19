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
from streamlit_js_eval import streamlit_js_eval

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")
CARPETAS_IMPORTAR = [os.path.join(BASE_DIR, "importar_fotos"), os.path.join(BASE_DIR, "importar_fotos2")]

os.makedirs(IMG_DIR, exist_ok=True)
for carpeta in CARPETAS_IMPORTAR: os.makedirs(carpeta, exist_ok=True)

st.set_page_config(page_title="Color Insumos - ERP Maestro", layout="wide")

# --- FUNCIONES DE PERSISTENCIA (NUEVO) ---
def set_persistent_user(user_data):
    """Guarda los datos del usuario en el localStorage del navegador."""
    val = json.dumps(user_data)
    streamlit_js_eval(js_expressions=f"localStorage.setItem('user_color_insumos', '{val}')", key="set_ls")

def get_persistent_user():
    """Recupera los datos del usuario del localStorage."""
    return streamlit_js_eval(js_expressions="localStorage.getItem('user_color_insumos')", key="get_ls")

def logout_persistent():
    """Elimina la sesión del localStorage y del estado de Streamlit."""
    streamlit_js_eval(js_expressions="localStorage.removeItem('user_color_insumos')", key="del_ls")
    st.session_state.auth = False
    st.session_state.user_data = None
    st.rerun()

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
    
    /* Estilos para tablas de pedidos */
    .pedido-header {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #1f77b4;
        margin-bottom: 10px;
    }
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
    # Usuario Administrador por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- LÓGICA DE CATEGORIZACIÓN TÉCNICA ---
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

def generar_pdf_recibo(pedido, conn):
    u_data = conn.execute("SELECT rif, telefono, direccion FROM usuarios WHERE username=?", (pedido['username'],)).fetchone()
    c_rif = u_data[0] if u_data and u_data[0] else "N/A"
    c_tel = u_data[1] if u_data and u_data[1] else "N/A"
    c_dir = u_data[2] if u_data and u_data[2] else "No registrada"

    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Arial", 'B', 18)
    pdf.cell(190, 10, "COLOR INSUMOS", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(190, 5, "Servicio Técnico y Papelería al Mayor y Detal", ln=True, align='C')
    pdf.cell(190, 5, "Web: colorinsumos.com | Contacto: 0412-6901346 / 0412-7757053", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 8, f" RECIBO DE PEDIDO #{pedido['id']} - {pedido['fecha']}", ln=True, fill=True)
    
    pdf.set_font("Arial", size=10)
    pdf.cell(95, 7, f" Cliente: {pedido['cliente_nombre']}", ln=0)
    pdf.cell(95, 7, f" RIF/CI: {c_rif}", ln=1)
    pdf.cell(95, 7, f" Telefono: {c_tel}", ln=0)
    pdf.cell(95, 7, f" Metodo de Pago: {pedido['metodo_pago']}", ln=1)
    pdf.multi_cell(190, 7, f" Direccion: {c_dir}")
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(110, 8, " Descripcion del Articulo", 1, 0, 'L', True)
    pdf.cell(20, 8, "Cant", 1, 0, 'C', True)
    pdf.cell(30, 8, "Precio", 1, 0, 'C', True)
    pdf.cell(30, 8, "Subtotal", 1, 1, 'C', True)
    
    pdf.set_font("Arial", size=9)
    items = json.loads(pedido['items'])
    for sku, d in items.items():
        desc_txt = f"{sku} - {d['desc']}"
        pdf.cell(110, 8, f" {desc_txt[:55]}", 1)
        pdf.cell(20, 8, str(d['c']), 1, 0, 'C')
        pdf.cell(30, 8, f" ${d['p']:.2f}", 1, 0, 'R')
        pdf.cell(30, 8, f" ${(d['p']*d['c']):.2f}", 1, 1, 'R')
    
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(130, 8, "", 0, 0)
    pdf.cell(30, 8, "TOTAL FINAL:", 1, 0, 'R', True)
    pdf.cell(30, 8, f" ${pedido['total']:.2f}", 1, 1, 'R')
    
    return bytes(pdf.output())

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

# Lógica de Recuperación de Sesión al refrescar
if 'auth' not in st.session_state:
    st.session_state.auth = False
    ls_user = get_persistent_user()
    if ls_user:
        try:
            st.session_state.user_data = json.loads(ls_user)
            st.session_state.auth = True
        except:
            pass

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            # Guardar en navegador
            set_persistent_user(st.session_state.user_data)
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    uid = user['user']
    conn = get_connection()
    carrito_usuario = cargar_carrito_db(uid)
    subtotal_v = sum(d['p'] * d['c'] for d in carrito_usuario.values())
    cant_v = sum(d['c'] for d in carrito_usuario.values())

    # --- NAVEGACIÓN LATERAL ---
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
                    <p style='font-size:0.8rem; font-weight:bold'>Dctos. sugeridos:</p>
                    <p style='font-size:0.85rem'>🔹 BCV (>100$): <span style='color:#d9534f'>-${dcto_bcv:.2f}</span></p>
                    <p style='font-size:0.85rem'>🔹 Divisas: <span style='color:#5cb85c'>-${dcto_zelle:.2f}</span></p>
                </div>
            """, unsafe_allow_html=True)
            
        if st.button("Cerrar Sesión"): 
            logout_persistent()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo Pointer")
        c1, c2, c3 = st.columns([3, 2, 1])
        busq = c1.text_input("🔍 Buscar SKU o descripción")
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", conn)
        cat_sel = c2.selectbox("📂 Filtrar Categoría", ["Todos"] + df_cats['categoria'].tolist())
        
        query = "SELECT * FROM productos WHERE 1=1"
        params = []
        if cat_sel != "Todos": query += " AND categoria = ?"; params.append(cat_sel)
        if busq: query += " AND (descripcion LIKE ? OR sku LIKE ?)"; params.extend([f"%{busq}%", f"%{busq}%"])
        
        df = pd.read_sql(query, conn, params=params)

        if df.empty:
            st.info("No se encontraron productos.")
        else:
            items_pag = 20
            total_p = (len(df) // items_pag) + (1 if len(df) % items_pag > 0 else 0)
            p_sel = st.number_input(f"Página", 1, total_p, 1)
            
            for row in df.iloc[(p_sel-1)*items_pag : p_sel*items_pag].itertuples():
                r1, r2, r3, r4 = st.columns([0.8, 4.5, 1.2, 2.5])
                with r1:
                    img = row.foto_path if row.foto_path and os.path.exists(row.foto_path) else "https://via.placeholder.com/60"
                    st.image(img)
                with r2:
                    st.markdown(f'<p class="sku-text">{row.sku} | {row.categoria}</p>', unsafe_allow_html=True)
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
                b2.write(f"**{carrito_usuario[row.sku]['c'] if row.sku in carrito_usuario else 0}**")
                if b3.button("➕", key=f"t_p_{row.sku}"):
                    if row.sku in carrito_usuario: carrito_usuario[row.sku]['c'] += 1
                    else: carrito_usuario[row.sku] = {"desc": row.descripcion, "p": row.precio, "c": 1}
                    guardar_carrito_db(uid, carrito_usuario); st.rerun()
                if b4.button("🗑️", key=f"t_del_{row.sku}"):
                    if row.sku in carrito_usuario:
                        del carrito_usuario[row.sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                st.markdown("<hr style='margin:5px 0; border-color:#f5f5f5'>", unsafe_allow_html=True)

    # --- MÓDULO CARRITO ---
    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Carrito de Compras")
        if not carrito_usuario:
            st.info("Tu carrito está vacío.")
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
            metodo = st.radio("Seleccione Método de Pago:", ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            desc = (subtotal_v * 0.30) if metodo == "Divisas / Zelle" else ((subtotal_v * 0.10) if subtotal_v >= 100 else 0)
            total_f = subtotal_v - desc
            
            st.write(f"Subtotal: ${subtotal_v:.2f}")
            st.write(f"Descuento Aplicado: -${desc:.2f}")
            st.header(f"Total a Pagar: ${total_f:.2f}")
            
            if st.button("🏁 Confirmar y Enviar Pedido", type="primary", use_container_width=True):
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(carrito_usuario), metodo, subtotal_v, desc, total_f, "Pendiente"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("¡Pedido registrado con éxito!")
                st.balloons()

    # --- MÓDULO MIS PEDIDOS ---
    elif menu == "📜 Mis Pedidos":
        st.title("📜 Historial de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        pedidos_df = pd.read_sql(query, conn)

        if pedidos_df.empty:
            st.info("No hay pedidos registrados aún.")
        else:
            for _, p_row in pedidos_df.iterrows():
                with st.expander(f"📦 Pedido #{p_row['id']} | {p_row['fecha']} | Total: ${p_row['total']:.2f}"):
                    c1, c2, c3 = st.columns(3)
                    status_color = "orange" if p_row['status'] == "Pendiente" else "green"
                    c1.markdown(f"**Estado:** :{status_color}[{p_row['status']}]")
                    c2.markdown(f"**Método:** {p_row['metodo_pago']}")
                    c3.markdown(f"**Cliente:** {p_row['cliente_nombre']}")
                    
                    st.markdown("---")
                    items_dict = json.loads(p_row['items'])
                    tabla_lista = []
                    for sku, d in items_dict.items():
                        tabla_lista.append({
                            "Artículo": f"{sku} - {d['desc']}",
                            "Cant": d['c'],
                            "Precio Unit.": f"${d['p']:.2f}",
                            "Subtotal": f"${(d['c']*d['p']):.2f}"
                        })
                    st.table(pd.DataFrame(tabla_lista))
                    
                    col_b1, col_b2 = st.columns([2, 1])
                    with col_b2:
                        st.markdown(f"**Subtotal:** ${p_row['subtotal']:.2f}")
                        st.markdown(f"**Descuento:** -${p_row['descuento']:.2f}")
                        st.markdown(f"### Total: ${p_row['total']:.2f}")
                    
                    try:
                        pdf_bytes = generar_pdf_recibo(p_row, conn)
                        st.download_button(
                            label="📄 Descargar Recibo PDF",
                            data=pdf_bytes,
                            file_name=f"recibo_color_insumos_{p_row['id']}.pdf",
                            mime="application/pdf",
                            key=f"pdf_{p_row['id']}"
                        )
                    except Exception as e:
                        st.error(f"Error al generar PDF: {e}")

                    if user['rol'] == 'admin':
                        if st.button(f"🗑️ Eliminar Pedido #{p_row['id']}", key=f"del_{p_row['id']}"):
                            conn.execute("DELETE FROM pedidos WHERE id=?", (p_row['id'],))
                            conn.commit()
                            st.rerun()

    # --- ADMINISTRACIÓN ---
    elif menu == "📊 Ventas":
        st.title("📊 Control Administrativo de Ventas")
        df_ventas = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn)
        st.dataframe(df_ventas, use_container_width=True)

    elif menu == "📁 Carga":
        st.title("📁 Carga masiva de Catálogo")
        if st.button("🔄 Ejecutar Re-categorización Automática"):
            prods = conn.execute("SELECT sku, descripcion FROM productos").fetchall()
            for sku, d in prods:
                conn.execute("UPDATE productos SET categoria = ? WHERE sku = ?", (auto_categorizar(d), sku))
            conn.commit()
            st.success("Categorías actualizadas correctamente.")

        f = st.file_uploader("Subir PDF del Catálogo Pointer", type="pdf")
        if f and st.button("🚀 Iniciar Extracción de Datos"):
            doc = fitz.open(stream=f.read(), filetype="pdf")
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
            st.success("Catálogo procesado y actualizado.")

    elif menu == "🖼️ Fotos":
        st.title("🖼️ Sincronización de Galería")
        st.info("Coloque las imágenes en la carpeta 'importar_fotos' con el nombre del SKU.")
        if st.button("Vincular Imágenes con Productos"):
            n = vincular_imagenes_locales()
            st.success(f"Se actualizaron {n} productos con sus fotos.")

    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Usuarios")
        # Obtenemos todos los campos necesarios de la DB
        df_u = pd.read_sql("SELECT username, password, nombre, rol, telefono, rif, direccion, ciudad FROM usuarios", conn)
        
        # --- LISTADO Y EDICIÓN DE USUARIOS ---
        for i, row in df_u.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                c1.write(f"**{row['nombre']}** ({row['username']})")
                c2.write(f"Rol: {row['rol']} | RIF: {row['rif'] or 'N/A'}")
                c3.write(f"📍 {row['ciudad'] or 'No definida'}")
                
                # Botón para activar el modo edición de este usuario específico
                if c4.button("📝 Editar", key=f"btn_edit_{row['username']}"):
                    st.session_state[f"edit_mode_{row['username']}"] = True
                
                # Si el modo edición está activo para este usuario, mostrar formulario
                if st.session_state.get(f"edit_mode_{row['username']}", False):
                    with st.form(key=f"form_edit_{row['username']}"):
                        st.info(f"Editando perfil de: {row['username']}")
                        f1, f2 = st.columns(2)
                        
                        # Campos de edición
                        new_pass = f1.text_input("Cambiar Clave", value=row['password'], type="password")
                        new_nom = f2.text_input("Nombre Completo", value=row['nombre'])
                        new_tel = f1.text_input("Teléfono", value=row['telefono'] or "")
                        new_rif = f2.text_input("RIF / CI", value=row['rif'] or "")
                        new_ciu = f1.text_input("Ciudad", value=row['ciudad'] or "")
                        new_dir = st.text_area("Dirección Exacta", value=row['direccion'] or "")
                        
                        b1, b2 = st.columns(2)
                        if b1.form_submit_button("💾 Guardar Cambios"):
                            conn.execute("""
                                UPDATE usuarios 
                                SET password=?, nombre=?, telefono=?, rif=?, direccion=?, ciudad=? 
                                WHERE username=?""", 
                                (new_pass, new_nom, new_tel, new_rif, new_dir, new_ciu, row['username']))
                            conn.commit()
                            st.session_state[f"edit_mode_{row['username']}"] = False
                            st.success("Datos actualizados correctamente")
                            st.rerun()
                            
                        if b2.form_submit_button("❌ Cancelar"):
                            st.session_state[f"edit_mode_{row['username']}"] = False
                            st.rerun()
                st.markdown("<hr style='margin:10px 0; border-color:#eee'>", unsafe_allow_html=True)

        # --- REGISTRO DE NUEVOS USUARIOS (MANTENIDO) ---
        with st.expander("➕ Registrar Nuevo Usuario"):
            nu = st.text_input("Correo/Usuario (Nuevo)")
            np = st.text_input("Clave (Nueva)", type="password")
            nn = st.text_input("Nombre Completo (Nuevo)")
            nr = st.selectbox("Rol del nuevo usuario", ["cliente", "admin"])
            if st.button("Guardar Nuevo Usuario"):
                conn.execute("INSERT OR REPLACE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                             (nu, np, nn, nr))
                conn.commit()
                st.success("Usuario creado")
                st.rerun()