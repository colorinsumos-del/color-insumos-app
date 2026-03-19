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
from fpdf import FPDF # Asegúrate de instalar fpdf2

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
    # Tabla de productos (Incluye Categoría)
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de usuarios robusta
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, 
                  direccion TEXT, telefono TEXT, rif TEXT, ciudad TEXT, notas TEXT)''')
    # Tabla de pedidos detallada
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, cliente_nombre TEXT, fecha TEXT, 
                  items TEXT, metodo_pago TEXT, subtotal REAL, descuento REAL, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carritos (username TEXT PRIMARY KEY, data TEXT)''')
    
    # Usuario admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- FUNCIONES DE APOYO ---
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
    pdf.cell(200, 10, f"Cliente: {pedido['cliente_nombre']} ({pedido['username']})", ln=True)
    pdf.cell(200, 10, f"Fecha: {pedido['fecha']}", ln=True)
    pdf.ln(10)
    
    # Tabla de items
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

# --- LOGICA DE VINCULACIÓN (SIN MODIFICAR) ---
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
    # Pantalla de Login (Sin cambios mayores)
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

    # --- MÓDULO TIENDA MEJORADO ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        
        # Filtros Superiores
        c_bus, c_cat, c_clear = st.columns([3, 2, 1])
        busq = c_bus.text_input("🔍 Buscar por SKU o descripción...", key="busqueda_input")
        
        df_cats = pd.read_sql("SELECT DISTINCT categoria FROM productos", get_connection())
        categorias = ["Todas"] + df_cats['categoria'].tolist()
        cat_sel = c_cat.selectbox("📁 Categoría", categorias)
        
        if c_clear.button("✖️ Borrar"):
             st.rerun()

        # Cargar datos con filtros
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
            st.warning("No se encontraron productos. Intenta usar la barra de búsqueda superior.")
        else:
            # Paginación simple (Mostrar de 10 en 10)
            items_por_pag = 10
            pag = st.number_input("Página", 1, (len(df)//items_por_pag)+1, 1)
            start_idx = (pag-1) * items_por_pag
            end_idx = start_idx + items_por_pag

            for _, row in df.iloc[start_idx:end_idx].iterrows():
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([1, 3, 1, 1.2])
                    with c1:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            st.image(row['foto_path'], width=100)
                        else: st.image("https://via.placeholder.com/100?text=SIN+FOTO", width=100)
                    
                    c2.subheader(row['sku'])
                    c2.caption(f"Categoría: {row['categoria']}")
                    c2.write(row['descripcion'])
                    
                    # Indicador de producto en carrito
                    if row['sku'] in carrito_usuario:
                        c2.info(f"✅ En el carrito ({carrito_usuario[row['sku']]['c']})")

                    c3.metric("Precio", f"${row['precio']:.2f}")
                    
                    # Controles de cantidad +/-
                    col_sub, col_val, col_add = c4.columns([1, 2, 1])
                    if col_sub.button("➖", key=f"sub_{row['sku']}"):
                        if row['sku'] in carrito_usuario and carrito_usuario[row['sku']]['c'] > 1:
                            carrito_usuario[row['sku']]['c'] -= 1
                            guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    
                    cant_actual = carrito_usuario[row['sku']]['c'] if row['sku'] in carrito_usuario else 1
                    col_val.write(f"**{cant_actual}**")
                    
                    if col_add.button("➕", key=f"add_{row['sku']}"):
                        if row['sku'] in carrito_usuario:
                            carrito_usuario[row['sku']]['c'] += 1
                        else:
                            carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": 1}
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()

    # --- MÓDULO CARRITO ROBUSTO ---
    elif menu.startswith("🛒 Carrito"):
        st.title("🛒 Tu Carrito de Compras")
        if not carrito_usuario:
            st.info("Tu carrito está vacío.")
        else:
            subtotal = 0
            for sku, data in list(carrito_usuario.items()):
                with st.expander(f"{sku} - {data['desc']}", expanded=True):
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                    c1.write(f"Precio: ${data['p']:.2f}")
                    cant = c2.number_input("Cantidad", 1, 1000, data['c'], key=f"cart_q_{sku}")
                    if cant != data['c']:
                        carrito_usuario[sku]['c'] = cant
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
                    
                    item_total = data['p'] * cant
                    subtotal += item_total
                    c3.write(f"Subtotal: **${item_total:.2f}**")
                    if c4.button("🗑️ Quitar", key=f"del_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario); st.rerun()
            
            st.divider()
            # Lógica Financiera y Descuentos
            c_calc1, c_calc2 = st.columns(2)
            with c_calc1:
                descuento_pct = st.slider("Aplicar Descuento (%)", 0, 20, 0)
                monto_desc = subtotal * (descuento_pct / 100)
                total_final = subtotal - monto_desc
                st.write(f"Subtotal: ${subtotal:.2f}")
                st.write(f"Descuento ({descuento_pct}%): -${monto_desc:.2f}")
                st.header(f"Total: ${total_final:.2f}")
            
            with c_calc2:
                tasa_bcv = st.number_input("Tasa de Cambio (Bs/USD)", min_value=1.0, value=36.0)
                st.subheader(f"Total en Bs: {total_final * tasa_bcv:,.2f} Bs.")

            metodo = st.selectbox("Método de Pago", ["Transferencia USD", "Pago Móvil", "Zelle", "Efectivo"])
            if st.button("🏁 Finalizar Pedido y Generar Recibo", type="primary"):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                             (uid, user['nombre'], datetime.now().strftime("%Y-%m-%d %H:%M"), json.dumps(carrito_usuario), metodo, subtotal, monto_desc, total_final, "Pendiente"))
                conn.execute("DELETE FROM carritos WHERE username=?", (uid,))
                conn.commit()
                st.success("¡Pedido realizado con éxito!")
                st.balloons()

    # --- MÓDULO GESTIÓN DE USUARIOS (CRUD COMPLETO) ---
    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Usuarios")
        tab_list, tab_crear = st.tabs(["Lista de Usuarios", "➕ Crear Nuevo"])
        
        conn = get_connection()
        with tab_list:
            usuarios_df = pd.read_sql("SELECT * FROM usuarios", conn)
            for _, u_row in usuarios_df.iterrows():
                with st.expander(f"{u_row['nombre']} (@{u_row['username']}) - {u_row['rol']}"):
                    with st.form(f"edit_{u_row['username']}"):
                        c1, c2 = st.columns(2)
                        new_nom = c1.text_input("Nombre", u_row['nombre'])
                        new_rol = c2.selectbox("Rol", ["cliente", "admin"], index=0 if u_row['rol']=='cliente' else 1)
                        new_dir = st.text_input("Dirección", u_row['direccion'])
                        new_rif = c1.text_input("RIF/Cédula", u_row['rif'])
                        new_tel = c2.text_input("Teléfono", u_row['telefono'])
                        if st.form_submit_button("Actualizar Datos"):
                            conn.execute("UPDATE usuarios SET nombre=?, rol=?, direccion=?, rif=?, telefono=? WHERE username=?",
                                         (new_nom, new_rol, new_dir, new_rif, new_tel, u_row['username']))
                            conn.commit(); st.rerun()
                    if u_row['username'] != 'colorinsumos@gmail.com':
                        if st.button("❌ Eliminar Usuario", key=f"del_u_{u_row['username']}"):
                            conn.execute("DELETE FROM usuarios WHERE username=?", (u_row['username'],))
                            conn.commit(); st.rerun()

        with tab_crear:
            with st.form("nuevo_usuario"):
                nu_user = st.text_input("Correo/Usuario (ID)")
                nu_pass = st.text_input("Contraseña", type="password")
                nu_nom = st.text_input("Nombre Completo")
                nu_rol = st.selectbox("Rol", ["cliente", "admin"])
                if st.form_submit_button("Registrar Usuario"):
                    try:
                        conn.execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)",
                                     (nu_user, nu_pass, nu_nom, nu_rol))
                        conn.commit(); st.success("Usuario creado"); st.rerun()
                    except: st.error("El usuario ya existe")

    # --- MÓDULO GESTIÓN VENTAS ---
    elif menu == "📊 Gestión Ventas":
        st.title("📊 Control de Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        
        # Exportar a Excel
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_p.to_excel(writer, index=False, sheet_name='Pedidos')
        st.download_button("📥 Descargar Reporte Excel", buffer.getvalue(), "Reporte_Ventas.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        for _, p_row in df_p.iterrows():
            with st.container(border=True):
                col1, col2, col3 = st.columns([2, 1, 1])
                col1.write(f"**Pedido #{p_row['id']}** - {p_row['cliente_nombre']}")
                col1.caption(f"Fecha: {p_row['fecha']} | Pago: {p_row['metodo_pago']}")
                col2.metric("Total", f"${p_row['total']:.2f}")
                
                # Botón de PDF por pedido
                pdf_bytes = generar_pdf_recibo(p_row)
                col3.download_button(f"📄 Recibo PDF #{p_row['id']}", pdf_bytes, f"Recibo_{p_row['id']}.pdf", "application/pdf")
                
                with st.expander("Ver Detalles de Artículos"):
                    st.json(json.loads(p_row['items']))

    # --- MÓDULO CARGAR PDF / EXCEL (SIN CAMBIOS) ---
    elif menu == "📁 Cargar Catálogo":
        st.title("📁 Importar Datos")
        f = st.file_uploader("Subir PDF de Pointer", type="pdf")
        if f and st.button("🚀 Iniciar Extracción PDF"):
            doc = fitz.open(stream=f.read(), filetype="pdf")
            conn = get_connection()
            for page in doc:
                tabs = page.find_tables()
                for tab in tabs:
                    df_t = tab.to_pandas()
                    for _, row in df_t.iterrows():
                        try:
                            sku = str(row.iloc[0]).strip().replace('\n', '')
                            desc = str(row.iloc[2]).strip()
                            precio = limpiar_precio(row.iloc[4])
                            if len(sku) > 2 and precio > 0:
                                conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio, descripcion=excluded.descripcion", (sku, desc, precio, "General"))
                        except: continue
            conn.commit(); st.success("¡Datos cargados!")

    # --- MÓDULO VINCULAR FOTOS (SIN CAMBIOS) ---
    elif menu == "🖼️ Vincular Fotos":
        st.title("🖼️ Vinculación Masiva")
        if st.button("🔗 Cruzar Fotos con Productos"):
            total = vincular_imagenes_locales()
            st.success(f"✅ Se han vinculado {total} fotos exitosamente."); st.balloons()