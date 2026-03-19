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

# --- ESTILOS CSS PARA UNIFORMIDAD ---
st.markdown("""
    <style>
    .product-card {
        height: 450px;
        padding: 10px;
        border-radius: 10px;
        border: 1px solid #ddd;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .stImage > img {
        object-fit: contain;
        height: 180px !important;
        width: 100% !important;
    }
    .totalizer-bar {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
        border-left: 5px solid #ff4b4b;
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
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- FUNCIONES DE APOYO ---
def auto_categorizar(descripcion):
    desc = descripcion.lower()
    if any(x in desc for x in ['papel', 'lapiz', 'boligrafo', 'cuaderno', 'resma', 'sacapunta']): return "Papelería"
    if any(x in desc for x in ['tinta', 'toner', 'cartucho', 'ink']): return "Consumibles"
    if any(x in desc for x in ['impresora', 'pc', 'mouse', 'teclado', 'usb']): return "Tecnología"
    if any(x in desc for x in ['limpieza', 'mantenimiento', 'quimico']): return "Servicio Técnico"
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
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, f"Recibo de Pedido #{pedido['id']}", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 7, f"Cliente: {pedido['cliente_nombre']}", ln=True)
    pdf.cell(200, 7, f"Fecha: {pedido['fecha']}", ln=True)
    pdf.cell(200, 7, f"Metodo de Pago: {pedido['metodo_pago']}", ln=True)
    pdf.ln(5)
    
    items = json.loads(pedido['items'])
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(70, 8, "Producto/SKU", 1, 0, 'C', True)
    pdf.cell(25, 8, "Cant", 1, 0, 'C', True)
    pdf.cell(35, 8, "Precio U.", 1, 0, 'C', True)
    pdf.cell(35, 8, "Subtotal", 1, 1, 'C', True)
    
    for sku, d in items.items():
        pdf.cell(70, 8, f" {sku}", 1)
        pdf.cell(25, 8, str(d['c']), 1, 0, 'C')
        pdf.cell(35, 8, f" ${d['p']:.2f}", 1, 0, 'R')
        pdf.cell(35, 8, f" ${(d['p']*d['c']):.2f}", 1, 1, 'R')
    
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(130, 8, "Subtotal General:", 0, 0, 'R')
    pdf.cell(35, 8, f"${pedido['subtotal']:.2f}", 1, 1, 'R')
    pdf.cell(130, 8, "Descuento Aplicado:", 0, 0, 'R')
    pdf.cell(35, 8, f"-${pedido['descuento']:.2f}", 1, 1, 'R')
    pdf.cell(130, 10, "TOTAL FINAL:", 0, 0, 'R')
    pdf.cell(35, 10, f"${pedido['total']:.2f}", 1, 1, 'R', True)
    
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

# --- INTERFAZ ---
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

    # --- BARRA DE TOTALIZACIÓN EN TIEMPO REAL ---
    items_totales = sum(d['c'] for d in carrito_usuario.values())
    subtotal_en_vivo = sum(d['p'] * d['c'] for d in carrito_usuario.values())

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({items_totales})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Gestión Ventas", "📁 Cargar Catálogo", "🖼️ Vincular Fotos", "👥 Usuarios"]
        menu = st.radio("Menú Principal", opc)
        st.divider()
        st.metric("Total Carrito", f"${subtotal_en_vivo:.2f}")
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo Color Insumos")
        
        # Panel superior de información
        st.markdown(f"""
            <div class="totalizer-bar">
                <strong>Resumen Actual:</strong> {items_totales} artículos seleccionados | 
                <strong>Subtotal:</strong> ${subtotal_en_vivo:.2f}
            </div>
        """, unsafe_allow_html=True)

        c_bus, c_cat, c_clear = st.columns([3, 2, 1])
        busq = c_bus.text_input("🔍 Buscar SKU o nombre...", key="busqueda_input")
        
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", get_connection())
        categorias = ["Todas"] + df_cats['categoria'].tolist()
        cat_sel = c_cat.selectbox("📂 Seleccionar Rubro", categorias)
        
        if c_clear.button("✖️ Limpiar Búsqueda", use_container_width=True):
             st.rerun()

        query = "SELECT * FROM productos WHERE 1=1"
        params = []
        if cat_sel != "Todas":
            query += " AND categoria = ?"
            params.append(cat_sel)
        if busq:
            query += " AND (descripcion LIKE ? OR sku LIKE ?)"
            params.extend([f"%{busq}%", f"%{busq}%"])
        
        df = pd.read_sql(query, get_connection(), params=params)

        if df.empty:
            st.info("💡 No hay productos que coincidan. Usa la barra de búsqueda o cambia el rubro.")
        else:
            items_por_pag = 12
            total_paginas = (len(df) // items_por_pag) + (1 if len(df) % items_por_pag > 0 else 0)
            
            c_pag_nav, c_pag_info = st.columns([2, 4])
            pag = c_pag_nav.number_input(f"Página (Total: {total_paginas})", 1, total_paginas, 1)
            c_pag_info.write(f"### Mostrando productos { (pag-1)*items_por_pag + 1 } al { min(pag*items_por_pag, len(df)) } de {len(df)}")
            
            start_idx = (pag-1) * items_por_pag
            end_idx = start_idx + items_por_pag

            # Cuadrícula Uniforme de Productos
            rows_data = df.iloc[start_idx:end_idx]
            cols = st.columns(3)
            for i, row in enumerate(rows_data.itertuples()):
                with cols[i % 3]:
                    st.markdown('<div class="product-card">', unsafe_allow_html=True)
                    if row.foto_path and os.path.exists(row.foto_path):
                        st.image(row.foto_path)
                    else:
                        st.image("https://via.placeholder.com/200?text=Color+Insumos")
                    
                    st.subheader(row.sku)
                    st.caption(f"📁 {row.categoria}")
                    # Limitar descripción para mantener altura
                    desc_corta = (row.descripcion[:65] + '...') if len(row.descripcion) > 65 else row.descripcion
                    st.write(desc_corta)
                    st.markdown(f"## ${row.precio:.2f}")

                    c_btn1, c_btn2, c_btn3 = st.columns([1, 1, 1])
                    if c_btn1.button("➖", key=f"tienda_sub_{row.sku}"):
                        if row.sku in carrito_usuario:
                            if carrito_usuario[row.sku]['c'] > 1:
                                carrito_usuario[row.sku]['c'] -= 1
                            else:
                                del carrito_usuario[row.sku]
                            guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    
                    cant = carrito_usuario[row.sku]['c'] if row.sku in carrito_usuario else 0
                    c_btn2.markdown(f"<h3 style='text-align: center; margin:0;'>{cant}</h3>", unsafe_allow_html=True)
                    
                    if c_btn3.button("➕", key=f"tienda_add_{row.sku}"):
                        if row.sku in carrito_usuario:
                            carrito_usuario[row.sku]['c'] += 1
                        else:
                            carrito_usuario[row.sku] = {"desc": row.descripcion, "p": row.precio, "c": 1}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Carrito de Compras")
        if not carrito_usuario:
            st.warning("El carrito está vacío. ¡Ve a la tienda a buscar artículos!")
        else:
            st.subheader("Artículos en tu pedido")
            for sku, data in list(carrito_usuario.items()):
                with st.container(border=True):
                    c_img, c_info, c_ctrl, c_subt = st.columns([1, 3, 2, 1.5])
                    
                    # Imagen pequeña en carrito
                    prod_info = get_connection().execute("SELECT foto_path FROM productos WHERE sku=?", (sku,)).fetchone()
                    if prod_info and prod_info[0] and os.path.exists(prod_info[0]):
                        c_img.image(prod_info[0], width=70)
                    
                    c_info.write(f"**{sku}**")
                    c_info.caption(data['desc'])
                    
                    # Controles +/- también en el carrito
                    cb1, cb2, cb3 = c_ctrl.columns([1, 1, 1])
                    if cb1.button("➖", key=f"cart_sub_{sku}"):
                        if data['c'] > 1:
                            carrito_usuario[sku]['c'] -= 1
                        else:
                            del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    
                    cb2.markdown(f"<h4 style='text-align: center;'>{data['c']}</h4>", unsafe_allow_html=True)
                    
                    if cb3.button("➕", key=f"cart_add_{sku}"):
                        carrito_usuario[sku]['c'] += 1
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    
                    item_total = data['p'] * data['c']
                    c_subt.markdown(f"**Subtotal:**\n### ${item_total:.2f}")
                    if c_subt.button("Eliminar", key=f"del_i_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

            st.divider()
            
            # --- LÓGICA DE REGLAS DE DESCUENTO ---
            metodo = st.radio("Método de Pago (Reglas de Descuento Aplicadas):", 
                              ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            
            desc_valor = 0.0
            msj_desc = "Ninguno"

            if metodo == "Divisas / Zelle":
                desc_valor = subtotal_en_vivo * 0.30
                msj_desc = "Descuento 30% por Pago en Divisas"
            elif metodo == "Bolívares (BCV)" and subtotal_en_vivo >= 100:
                desc_valor = subtotal_en_vivo * 0.10
                msj_desc = "Descuento 10% (Compra BCV > $100)"

            total_con_desc = subtotal_en_vivo - desc_valor

            c_tot1, c_tot2 = st.columns(2)
            with c_tot1:
                st.write(f"Subtotal de productos: ${subtotal_en_vivo:.2f}")
                st.info(f"💡 {msj_desc}: -${desc_valor:.2f}")
            
            with c_tot2:
                st.markdown(f"<h1 style='text-align: right;'>TOTAL: ${total_con_desc:.2f}</h1>", unsafe_allow_html=True)
            
            if st.button("🚀 PROCESAR PEDIDO Y GENERAR RECIBO", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(carrito_usuario), metodo, subtotal_en_vivo, desc_valor, total_con_desc, "Pendiente"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("¡Pedido Guardado Exitosamente!")
                st.balloons()

    elif menu == "📊 Gestión Ventas":
        st.title("📊 Control de Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        
        # Reporte Excel
        towrite = BytesIO()
        df_p.to_excel(towrite, index=False, engine='openpyxl')
        st.download_button("📥 Descargar Reporte de Ventas (Excel)", towrite.getvalue(), "Ventas_ColorInsumos.xlsx")

        for _, p_row in df_p.iterrows():
            with st.expander(f"Pedido #{p_row['id']} - {p_row['cliente_nombre']} ({p_row['fecha']})"):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**Método:** {p_row['metodo_pago']} | **Items:** {len(json.loads(p_row['items']))}")
                c2.write(f"**Subtotal:** ${p_row['subtotal']:.2f} | **Desc:** -${p_row['descuento']:.2f}")
                c2.markdown(f"### Total: ${p_row['total']:.2f}")
                
                pdf_gen = generar_pdf_recibo(p_row)
                c3.download_button(f"📄 Descargar PDF #{p_row['id']}", pdf_gen, f"Recibo_CI_{p_row['id']}.pdf")
                st.json(json.loads(p_row['items']))

    elif menu == "👥 Usuarios":
        st.title("👥 Administración de Usuarios")
        tab1, tab2 = st.tabs(["Listado de Usuarios", "Crear Nuevo"])
        conn = get_connection()
        with tab1:
            u_df = pd.read_sql("SELECT * FROM usuarios", conn)
            for _, u_row in u_df.iterrows():
                with st.expander(f"{u_row['nombre']} (@{u_row['username']}) - {u_row['rol']}"):
                    with st.form(f"form_user_{u_row['username']}"):
                        col1, col2 = st.columns(2)
                        n_nom = col1.text_input("Nombre Completo", u_row['nombre'])
                        n_tel = col2.text_input("Teléfono", u_row['telefono'])
                        n_dir = st.text_input("Dirección", u_row['direccion'])
                        if st.form_submit_button("Actualizar Usuario"):
                            conn.execute("UPDATE usuarios SET nombre=?, telefono=?, direccion=? WHERE username=?", 
                                         (n_nom, n_tel, n_dir, u_row['username']))
                            conn.commit(); st.rerun()
                    if u_row['username'] != 'colorinsumos@gmail.com':
                        if st.button("Eliminar permanentemente", key=f"del_user_{u_row['username']}"):
                            conn.execute("DELETE FROM usuarios WHERE username=?", (u_row['username'],))
                            conn.commit(); st.rerun()
        with tab2:
            with st.form("new_user_form"):
                n_u = st.text_input("Correo o ID Usuario")
                n_p = st.text_input("Clave de acceso", type="password")
                n_n = st.text_input("Nombre")
                n_r = st.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("Registrar en Sistema"):
                    conn.execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (n_u, n_p, n_n, n_r))
                    conn.commit(); st.success("Usuario registrado"); st.rerun()

    elif menu == "📁 Cargar Catálogo":
        st.title("📁 Importación de Inventario")
        f = st.file_uploader("Subir Archivo PDF", type="pdf")
        if f and st.button("Ejecutar Extracción Inteligente"):
            doc = fitz.open(stream=f.read(), filetype="pdf")
            conn = get_connection()
            for page in doc:
                for tab in page.find_tables():
                    for _, row in tab.to_pandas().iterrows():
                        try:
                            sku = str(row.iloc[0]).strip().replace('\n', '')
                            desc = str(row.iloc[2]).strip()
                            pre = limpiar_precio(row.iloc[4])
                            cat = auto_categorizar(desc)
                            if len(sku) > 2:
                                conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, categoria=excluded.categoria", (sku, desc, pre, cat))
                        except: continue
            conn.commit(); st.success("Inventario cargado y categorizado automáticamente."); st.balloons()

    elif menu == "🖼️ Vincular Fotos":
        st.title("🖼️ Vinculador de Imágenes")
        st.write("Esta función busca imágenes en las carpetas `importar_fotos` e `importar_fotos2` que coincidan con el SKU.")
        if st.button("🔗 Sincronizar Fotos"):
            total = vincular_imagenes_locales()
            st.success(f"Se vincularon exitosamente {total} productos con sus fotos.")