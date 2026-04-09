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
# --- NUEVO: CONEXIÓN NUBE ---
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")
CARPETAS_IMPORTAR = [os.path.join(BASE_DIR, "importar_fotos"), os.path.join(BASE_DIR, "importar_fotos2")]

os.makedirs(IMG_DIR, exist_ok=True)
for carpeta in CARPETAS_IMPORTAR:
    os.makedirs(carpeta, exist_ok=True)

st.set_page_config(page_title="Color Insumos - ERP Maestro", layout="wide")

# --- INICIALIZACIÓN DE CONEXIÓN A GOOGLE SHEETS ---
try:
    conn_gs = st.connection("gsheets", type=GSheetsConnection)
except Exception:
    conn_gs = None

# --- FUNCIONES DE PERSISTENCIA ---
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

# --- ESTILOS CSS ---
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
    .sku-text { font-weight: bold; color: #1f77b4; font-size: 0.9rem; margin-bottom: 0px; }
    .cat-text { color: #888; font-size: 0.75rem; margin-top: -5px; display: block; }
    .desc-text { font-size: 0.8rem; color: #444; margin-bottom: 0; line-height: 1.1; }
    .desc-text-main { font-size: 1.1rem; font-weight: bold; color: #1f77b4; margin-bottom: 2px; line-height: 1.2; }
    .in-cart-indicator { color: #28a745; font-weight: bold; font-size: 0.8rem; }
    .stNumberInput div div input { text-align: center; } 
    .pedido-header {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #1f77b4;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- MOTOR DE DATOS LOCAL ---
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
    try: 
        return float(clean)
    except: 
        return 0.0

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

if 'auth' not in st.session_state:
    st.session_state.auth = False
    ls_user = get_persistent_user()
    if ls_user:
        try:
            st.session_state.user_data = json.loads(ls_user)
            st.session_state.auth = True
        except: pass

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
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
        opc_base = ["🛍️ Tienda", "🛒 Carrito", "📜 Mis Pedidos"]
        opc_admin = ["📊 Ventas", "📁 Carga", "🖼️ Fotos", "👥 Usuarios", "💾 Respaldo"]
        opc = opc_base + opc_admin if user['rol'] == 'admin' else opc_base
        menu = st.radio("Navegación", opc, key="main_menu")
        
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
        if st.button("Cerrar Sesión"): logout_persistent()

    # --- MÓDULO TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo y Tienda")
        df_tienda = pd.read_sql_query("SELECT * FROM productos", conn)
        if df_tienda.empty:
            st.info("No hay productos registrados.")
        else:
            c1, c2, c3 = st.columns([3, 4, 1])
            f_cat = c1.selectbox("Filtrar por Categoría", ["Todos"] + list(df_tienda['categoria'].unique()))
            f_bus = c2.text_input("Buscar producto...")
            c3.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True) 
            if c3.button("🔍 Buscar", use_container_width=True):
                st.session_state.pag_actual = 1
                st.rerun()

            df_f = df_tienda.copy()
            if f_cat != "Todos": df_f = df_f[df_f['categoria'] == f_cat]
            if f_bus: df_f = df_f[df_f['descripcion'].str.contains(f_bus, case=False) | df_f['sku'].str.contains(f_bus, case=False)]
            
            items_pag = 15
            total_p = max(1, (len(df_f) // items_pag) + (1 if len(df_f) % items_pag > 0 else 0))
            if 'pag_actual' not in st.session_state: st.session_state.pag_actual = 1
            if st.session_state.pag_actual > total_p: st.session_state.pag_actual = total_p

            col_espacio, col_sel = st.columns([6, 2])
            p_ir = col_sel.number_input("Ir a la página:", min_value=1, max_value=total_p, value=st.session_state.pag_actual)
            if p_ir != st.session_state.pag_actual:
                st.session_state.pag_actual = p_ir
                st.rerun()

            def barra_navegacion(ubicacion):
                col_nav = st.columns([1, 1, 2, 1, 1])
                if col_nav[0].button("⏪", key=f"first_{ubicacion}"): st.session_state.pag_actual = 1; st.rerun()
                if col_nav[1].button("◀️", key=f"prev_{ubicacion}", disabled=(st.session_state.pag_actual <= 1)): st.session_state.pag_actual -= 1; st.rerun()
                col_nav[2].markdown(f"<h3 style='text-align: center;'>Pág. {st.session_state.pag_actual}</h3>", unsafe_allow_html=True)
                if col_nav[3].button("▶️", key=f"next_{ubicacion}", disabled=(st.session_state.pag_actual >= total_p)): st.session_state.pag_actual += 1; st.rerun()
                if col_nav[4].button("⏩", key=f"last_{ubicacion}"): st.session_state.pag_actual = total_p; st.rerun()

            barra_navegacion("top")
            for row in df_f.iloc[(st.session_state.pag_actual-1)*items_pag : st.session_state.pag_actual*items_pag].itertuples():
                r1, r2, r3, r4 = st.columns([1.2, 3.6, 1.2, 2.5]) 
                with r1:
                    img = row.foto_path if hasattr(row, 'foto_path') and row.foto_path and os.path.exists(row.foto_path) else "https://via.placeholder.com/100"
                    st.image(img, use_container_width=True)
                with r2:
                    st.markdown(f'<p class="desc-text-main">{row.descripcion}</p>', unsafe_allow_html=True)
                    st.markdown(f'<span class="cat-text">{row.sku} | {row.categoria}</span>', unsafe_allow_html=True)
                    if row.sku in carrito_usuario: st.markdown(f'<span class="in-cart-indicator">✅ En carrito</span>', unsafe_allow_html=True)
                with r3: st.markdown(f"### ${row.precio:.2f}")
                with r4:
                    c_input, c_add, c_del = st.columns([1.2, 1, 0.8])
                    nueva_q = c_input.number_input("Cant", 1, 999, carrito_usuario[row.sku]['c'] if row.sku in carrito_usuario else 1, key=f"t_q_{row.sku}")
                    if c_add.button("💾", key=f"t_s_{row.sku}"):
                        carrito_usuario[row.sku] = {"desc": row.descripcion, "p": row.precio, "c": nueva_q, "f": row.foto_path if hasattr(row, 'foto_path') else None}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    if c_del.button("🗑️", key=f"t_d_{row.sku}"):
                        if row.sku in carrito_usuario: del carrito_usuario[row.sku]; guardar_carrito_db(uid, carrito_usuario); st.rerun()
                st.markdown("---")
            barra_navegacion("bottom")
                
    # --- MÓDULO CARRITO ---
    elif menu == "🛒 Carrito":
        st.title("🛒 Carrito de Compras")
        if not carrito_usuario:
            st.info("Tu carrito está vacío.")
        else:
            for sku, data in list(carrito_usuario.items()):
                cr0, cr1, cr2, cr3, cr4 = st.columns([1, 3.5, 1.5, 2.5, 1.2])
                with cr0:
                    foto = data.get('f')
                    st.image(foto if foto and os.path.exists(foto) else "https://via.placeholder.com/80", use_container_width=True)
                with cr1: st.markdown(f"**{sku}**\n<small>{data['desc']}</small>", unsafe_allow_html=True)
                cr2.write(f"${data['p']:.2f}")
                ci_q, ci_s, ci_d = cr3.columns([1.2, 1, 1])
                q_edit = ci_q.number_input("Cant", 1, 999, data['c'], key=f"c_q_{sku}")
                if ci_s.button("💾", key=f"c_save_{sku}"):
                    carrito_usuario[sku]['c'] = q_edit; guardar_carrito_db(uid, carrito_usuario); st.rerun()
                if ci_d.button("🗑️", key=f"c_del_{sku}"):
                    del carrito_usuario[sku]; guardar_carrito_db(uid, carrito_usuario); st.rerun()
                cr4.write(f"**${(data['p'] * data['c']):.2f}**")
            
            st.markdown("### Resumen")
            subtotal_v = sum(item['p'] * item['c'] for item in carrito_usuario.values())
            metodo = st.radio("Pago:", ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            desc = (subtotal_v * 0.30) if metodo == "Divisas / Zelle" else ((subtotal_v * 0.10) if subtotal_v >= 100 else 0)
            total_f = subtotal_v - desc
            st.header(f"Total: ${total_f:.2f}")
            
            if st.button("🏁 Confirmar y Enviar Pedido", type="primary", use_container_width=True):
                fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
                # 1. Guardar Local
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)", 
                             (uid, user['nombre'], fecha_hoy, json.dumps(carrito_usuario), metodo, subtotal_v, desc, total_f, "Pendiente"))
                
                # 2. Guardar Nube (Google Sheets)
                if conn_gs:
                    try:
                        df_nube = conn_gs.read(worksheet="Pedidos")
                        # Crear filas planas para el Excel de la nube
                        nuevas_filas = []
                        for s, d in carrito_usuario.items():
                            nuevas_filas.append({
                                "Fecha": fecha_hoy, "Cliente": user['nombre'], "SKU": s, 
                                "Cantidad": d['c'], "Total_USD": total_f, "Metodo": metodo, "Status": "Pendiente"
                            })
                        df_final = pd.concat([df_nube, pd.DataFrame(nuevas_filas)], ignore_index=True)
                        conn_gs.update(worksheet="Pedidos", data=df_final)
                    except: pass

                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("¡Pedido registrado!"); st.balloons(); st.rerun()

    # --- MÓDULO MIS PEDIDOS ---
    elif menu == "📜 Mis Pedidos":
        st.title("📜 Historial")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        pedidos_df = pd.read_sql(query, conn)
        if pedidos_df.empty: st.info("Sin pedidos.")
        else:
            for _, p_row in pedidos_df.iterrows():
                with st.expander(f"📦 #{p_row['id']} | {p_row['fecha']} | ${p_row['total']:.2f}"):
                    st.write(f"**Estado:** {p_row['status']} | **Pago:** {p_row['metodo_pago']}")
                    items_dict = json.loads(p_row['items'])
                    st.table(pd.DataFrame([{"Art": f"{s}-{d['desc']}", "Cant": d['c'], "Sub": d['c']*d['p']} for s, d in items_dict.items()]))
                    if st.button(f"🗑️ Eliminar #{p_row['id']}", key=f"del_p_{p_row['id']}"):
                        conn.execute("DELETE FROM pedidos WHERE id=?", (p_row['id'],)); conn.commit(); st.rerun()

    # --- MÓDULO VENTAS (ADMIN) ---
    elif menu == "📊 Ventas" and user['rol'] == 'admin':
        st.title("📊 Panel de Ventas")
        tab_local, tab_nube = st.tabs(["🏠 Ventas Locales", "☁️ Ventas en la Nube (GSheets)"])
        
        with tab_local:
            df_v = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn)
            st.metric("Total Ventas", f"${df_v['total'].sum():,.2f}")
            st.dataframe(df_v, use_container_width=True)
        
        with tab_nube:
            if conn_gs:
                try:
                    df_cloud = conn_gs.read(worksheet="Pedidos")
                    st.dataframe(df_cloud, use_container_width=True)
                    if st.button("🔄 Sincronizar con Nube"): st.rerun()
                except: st.error("Configura los Secrets de Google Sheets.")
            else: st.warning("Conexión a GSheets no disponible.")

    # --- MÓDULO CARGA (ADMIN) ---
    elif menu == "📁 Carga" and user['rol'] == 'admin':
        st.title("📁 Carga de Catálogo")
        tab_p, tab_e = st.tabs(["📄 PDF", "📊 Excel"])
        
        with tab_p:
            f_pdf = st.file_uploader("Subir PDF", type="pdf")
            if f_pdf and st.button("🚀 Procesar PDF"):
                doc = fitz.open(stream=f_pdf.read(), filetype="pdf")
                count = 0
                for page in doc:
                    for tab in page.find_tables():
                        for _, r in tab.to_pandas().iterrows():
                            try:
                                sku, desc = str(r.iloc[0]).strip(), str(r.iloc[2]).strip()
                                pre = limpiar_precio(r.iloc[4])
                                if len(sku) > 1:
                                    conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio", 
                                                 (sku, desc, pre, auto_categorizar(desc)))
                                    count += 1
                            except: continue
                conn.commit(); st.success(f"Procesados {count} items.")
        
        with tab_e:
            f_xl = st.file_uploader("Excel/CSV", type=["xlsx", "csv"])
            if f_xl:
                df_imp = pd.read_csv(f_xl) if f_xl.name.endswith('.csv') else pd.read_excel(f_xl)
                st.dataframe(df_imp.head())
                if st.button("📥 Importar Excel"):
                    for _, row in df_imp.iterrows():
                        conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio", 
                                     (str(row[0]), str(row[1]), limpiar_precio(row[2]), auto_categorizar(str(row[1]))))
                    conn.commit(); st.success("Importación terminada.")

    # --- MÓDULO FOTOS ---
    elif menu == "🖼️ Fotos" and user['rol'] == 'admin':
        st.title("🖼️ Sincronizar Fotos")
        if st.button("Vincular"):
            n = vincular_imagenes_locales(); st.success(f"Vinculadas {n} fotos.")

    # --- MÓDULO USUARIOS ---
    elif menu == "👥 Usuarios" and user['rol'] == 'admin':
        st.title("👥 Gestión de Usuarios")
        df_u = pd.read_sql("SELECT * FROM usuarios", conn)
        st.dataframe(df_u)
        with st.expander("➕ Nuevo Usuario"):
            with st.form("nu"):
                nu, np, nn = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
                nr = st.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("Guardar"):
                    conn.execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (nu, np, nn, nr))
                    conn.commit(); st.rerun()

    # --- MÓDULO RESPALDO ---
    elif menu == "💾 Respaldo" and user['rol'] == 'admin':
        st.title("💾 Backups")
        tablas = ["usuarios", "productos", "pedidos", "carritos"]
        backup = {t: pd.read_sql(f"SELECT * FROM {t}", conn).to_dict(orient="records") for t in tablas}
        st.download_button("📥 Bajar JSON", json.dumps(backup), "backup.json", "application/json")