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
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, f"Cliente: {pedido['cliente_nombre']}", ln=True)
    pdf.cell(200, 10, f"Metodo: {pedido['metodo_pago']}", ln=True)
    pdf.ln(10)
    
    items = json.loads(pedido['items'])
    pdf.set_fill_color(200, 220, 255)
    pdf.cell(80, 10, "Producto", 1, 0, 'C', True)
    pdf.cell(30, 10, "Cant", 1, 0, 'C', True)
    pdf.cell(40, 10, "Precio U.", 1, 0, 'C', True)
    pdf.cell(40, 10, "Subtotal", 1, 1, 'C', True)
    
    for sku, d in items.items():
        pdf.cell(80, 10, f"{sku}", 1)
        pdf.cell(30, 10, str(d['c']), 1)
        pdf.cell(40, 10, f"${d['p']:.2f}", 1)
        pdf.cell(40, 10, f"${(d['p']*d['c']):.2f}", 1, 1)
    
    pdf.ln(5)
    pdf.cell(200, 10, f"Total a Pagar: ${pedido['total']:.2f}", ln=True, align='R')
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

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Gestión Ventas", "📁 Cargar Catálogo", "🖼️ Vincular Fotos", "👥 Usuarios"]
        menu = st.radio("Menú Principal", opc)
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo Color Insumos")
        
        c_bus, c_cat, c_clear = st.columns([3, 2, 1])
        busq = c_bus.text_input("🔍 Buscar SKU o nombre...", key="busqueda_input")
        
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", get_connection())
        categorias = ["Todas"] + df_cats['categoria'].tolist()
        cat_sel = c_cat.selectbox("📂 Rubro", categorias)
        
        if c_clear.button("✖️ Limpiar Filtros"):
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
            st.info("💡 Usa la barra de búsqueda o selecciona una categoría para ver productos.")
        else:
            items_por_pag = 12
            total_paginas = (len(df) // items_por_pag) + (1 if len(df) % items_por_pag > 0 else 0)
            
            c_pag1, c_pag2 = st.columns([1, 5])
            pag = c_pag1.number_input(f"Página (de {total_paginas})", 1, total_paginas, 1)
            
            start_idx = (pag-1) * items_por_pag
            end_idx = start_idx + items_por_pag

            # Grid de productos
            cols = st.columns(3)
            for i, row in enumerate(df.iloc[start_idx:end_idx].itertuples()):
                with cols[i % 3].container(border=True):
                    if row.foto_path and os.path.exists(row.foto_path):
                        st.image(row.foto_path, use_container_width=True)
                    else:
                        st.image("https://via.placeholder.com/150?text=No+Image", use_container_width=True)
                    
                    st.subheader(row.sku)
                    st.caption(f"📦 {row.categoria}")
                    st.write(f"**{row.descripcion}**")
                    st.markdown(f"### ${row.precio:.2f}")

                    # Controles +/- optimizados
                    c_btn1, c_btn2, c_btn3 = st.columns([1, 2, 1])
                    if c_btn1.button("➖", key=f"sub_{row.sku}"):
                        if row.sku in carrito_usuario:
                            if carrito_usuario[row.sku]['c'] > 1:
                                carrito_usuario[row.sku]['c'] -= 1
                            else:
                                del carrito_usuario[row.sku]
                            guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    
                    cant = carrito_usuario[row.sku]['c'] if row.sku in carrito_usuario else 0
                    c_btn2.markdown(f"<h3 style='text-align: center;'>{cant}</h3>", unsafe_allow_html=True)
                    
                    if c_btn3.button("➕", key=f"add_{row.sku}"):
                        if row.sku in carrito_usuario:
                            carrito_usuario[row.sku]['c'] += 1
                        else:
                            carrito_usuario[row.sku] = {"desc": row.descripcion, "p": row.precio, "c": 1}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Resumen de Compra")
        if not carrito_usuario:
            st.info("Tu carrito está esperando por artículos.")
        else:
            subtotal = sum(d['p'] * d['c'] for d in carrito_usuario.values())
            
            for sku, data in list(carrito_usuario.items()):
                with st.expander(f"{sku} - {data['c']} unidad(es)", expanded=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"**{data['desc']}**")
                    c2.write(f"${data['p']:.2f} c/u")
                    if c3.button("🗑️", key=f"del_cart_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

            st.divider()
            st.subheader("Configuración de Pago y Descuento")
            
            metodo = st.radio("Selecciona tu método de pago:", 
                              ["Bolívares (BCV)", "Divisas / Zelle"], horizontal=True)
            
            # --- LÓGICA DE REGLAS FINANCIERAS ---
            descuento_aplicado = 0.0
            tipo_desc = "Ninguno"

            if metodo == "Divisas / Zelle":
                descuento_aplicado = subtotal * 0.30
                tipo_desc = "Especial Divisas (30%)"
            elif metodo == "Bolívares (BCV)" and subtotal >= 100:
                descuento_aplicado = subtotal * 0.10
                tipo_desc = "Promo BCV > $100 (10%)"

            total_final = subtotal - descuento_aplicado

            c_fin1, c_fin2 = st.columns(2)
            with c_fin1:
                st.write(f"Subtotal Artículos: **${subtotal:.2f}**")
                st.write(f"Descuento Aplicado: **-${descuento_aplicado:.2f}** ({tipo_desc})")
                st.header(f"Total a Pagar: ${total_final:.2f}")
            
            if st.button("✅ Confirmar Pedido y Generar PDF", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(carrito_usuario), metodo, subtotal, descuento_aplicado, total_final, "Procesando"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("¡Pedido registrado!")
                st.balloons()

    elif menu == "👥 Usuarios":
        st.title("👥 Panel de Usuarios")
        t1, t2 = st.tabs(["Listado", "Nuevo Usuario"])
        conn = get_connection()
        with t1:
            u_df = pd.read_sql("SELECT * FROM usuarios", conn)
            for idx, u_row in u_df.iterrows():
                with st.expander(f"{u_row['nombre']} (@{u_row['username']})"):
                    with st.form(f"f_edit_{u_row['username']}"):
                        n_nom = st.text_input("Nombre", u_row['nombre'])
                        n_dir = st.text_input("Dirección", u_row['direccion'])
                        n_tel = st.text_input("Teléfono", u_row['telefono'])
                        n_rif = st.text_input("RIF", u_row['rif'])
                        if st.form_submit_button("Guardar Cambios"):
                            conn.execute("UPDATE usuarios SET nombre=?, direccion=?, telefono=?, rif=? WHERE username=?", 
                                         (n_nom, n_dir, n_tel, n_rif, u_row['username']))
                            conn.commit(); st.rerun()
                    if u_row['username'] != 'colorinsumos@gmail.com':
                        if st.button("Eliminar", key=f"del_u_{idx}"):
                            conn.execute("DELETE FROM usuarios WHERE username=?", (u_row['username'],))
                            conn.commit(); st.rerun()
        with t2:
            with st.form("crear_u"):
                nu_u = st.text_input("Email/User")
                nu_p = st.text_input("Clave", type="password")
                nu_n = st.text_input("Nombre")
                nu_r = st.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("Crear"):
                    conn.execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (nu_u, nu_p, nu_n, nu_r))
                    conn.commit(); st.success("Creado"); st.rerun()

    elif menu == "📊 Gestión Ventas":
        st.title("📊 Panel Administrativo")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        
        # Exportación Excel
        towrite = BytesIO()
        df_p.to_excel(towrite, index=False, engine='openpyxl')
        st.download_button("📊 Exportar Todo a Excel", towrite.getvalue(), "Ventas_ColorInsumos.xlsx")

        for _, p_row in df_p.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**ID: #{p_row['id']}** | Cliente: {p_row['cliente_nombre']}")
                c1.caption(f"Fecha: {p_row['fecha']} | Pago: {p_row['metodo_pago']}")
                c2.subheader(f"${p_row['total']:.2f}")
                
                pdf_bytes = generar_pdf_recibo(p_row)
                c3.download_button(f"📄 Recibo PDF", pdf_bytes, f"Pedido_{p_row['id']}.pdf")

    elif menu == "📁 Cargar Catálogo":
        st.title("📁 Importar Inventario")
        f = st.file_uploader("Subir PDF Maestro", type="pdf")
        if f and st.button("Procesar Archivo"):
            doc = fitz.open(stream=f.read(), filetype="pdf")
            conn = get_connection()
            for page in doc:
                for tab in page.find_tables():
                    for _, row in tab.to_pandas().iterrows():
                        try:
                            sku = str(row.iloc[0]).strip()
                            desc = str(row.iloc[2]).strip()
                            pre = limpiar_precio(row.iloc[4])
                            cat = auto_categorizar(desc)
                            if len(sku) > 2:
                                conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, categoria=excluded.categoria", (sku, desc, pre, cat))
                        except: continue
            conn.commit(); st.success("Catálogo Actualizado y Categorizado")

    elif menu == "🖼️ Vincular Fotos":
        st.title("🖼️ Vinculación de Imágenes")
        if st.button("Sincronizar Galería Local"):
            total = vincular_imagenes_locales()
            st.success(f"Se vincularon {total} imágenes a la base de datos.")