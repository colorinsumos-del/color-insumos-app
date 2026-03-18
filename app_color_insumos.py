import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import json
import time
import re
import pdfplumber
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- FUNCIÓN DE EXTRACCIÓN BCV (NUEVA LÓGICA) ---
def procesar_pdf_bcv(file):
    conn = get_connection()
    productos_cargados = 0
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split('\n')
            for line in lines:
                # Buscamos solo líneas que contengan explícitamente "BCV" para evitar tablas ocultas
                if "BCV" in line.upper():
                    try:
                        # Capturamos SKU, Descripción (hasta antes de BCV) y el precio después de BCV
                        match_sku_desc = re.match(r'^(\S+)\s+(.+?)(?=BCV)', line, re.IGNORECASE)
                        match_precio = re.search(r'BCV\s*[:$]?\s*([\d.,]+)', line, re.IGNORECASE)
                        
                        if match_sku_desc and match_precio:
                            sku = match_sku_desc.group(1).strip()
                            descripcion = match_sku_desc.group(2).strip()
                            precio_raw = match_precio.group(1)
                            
                            # Limpieza de formato: 1.250,50 -> 1250.50
                            precio_clean = precio_raw.replace('.', '').replace(',', '.')
                            precio_final = float(precio_clean)
                            
                            conn.execute("""
                                INSERT OR REPLACE INTO productos (sku, descripcion, precio, categoria) 
                                VALUES (?, ?, ?, ?)
                            """, (sku, descripcion, precio_final, "General"))
                            productos_cargados += 1
                    except:
                        continue
    
    conn.commit()
    st.cache_data.clear() 
    return productos_cargados

# --- GENERADOR DE PDF CORREGIDO ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    
    pdf.cell(190, 10, "COLOR INSUMOS - REPORTE DE PEDIDO", ln=True, align="C")
    pdf.set_font("helvetica", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 10, "SKU", 1)
    pdf.cell(90, 10, "Descripcion", 1)
    pdf.cell(20, 10, "Cant.", 1)
    pdf.cell(50, 10, "Subtotal", 1)
    pdf.ln()
    
    pdf.set_font("helvetica", "", 9)
    for item in items:
        sku = str(item.get('SKU', 'N/A'))
        desc = str(item.get('Desc', ''))[:45]
        cant = str(item.get('Cant', '0'))
        sub = f"${item.get('Subtotal', 0):.2f}"
        
        pdf.cell(30, 8, sku, 1)
        pdf.cell(90, 8, desc, 1)
        pdf.cell(20, 8, cant, 1)
        pdf.cell(50, 8, sub, 1)
        pdf.ln()
    
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(190, 10, f"TOTAL FINAL: ${total:.2f}", ln=True, align="R")
    
    return bytes(pdf.output())

# --- BASE DE DATOS E INICIALIZACIÓN ---
def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT DEFAULT '', telefono TEXT DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

def guardar_item_carrito(username, row, cant):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carrito_items VALUES (?,?,?,?,?)", 
                 (username, row['sku'], row['descripcion'], row['precio'], cant))
    conn.commit()

def eliminar_item_carrito(username, sku):
    conn = get_connection()
    conn.execute("DELETE FROM carrito_items WHERE username=? AND sku=?", (username, sku))
    conn.commit()

def obtener_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT sku, descripcion, precio, cantidad FROM carrito_items WHERE username=?", (username,)).fetchall()
    return {item[0]: {"desc": item[1], "p": item[2], "c": item[3]} for item in res}

def limpiar_carrito(username):
    conn = get_connection()
    conn.execute("DELETE FROM carrito_items WHERE username=?", (username,))
    conn.commit()

# --- ESTILOS CSS ---
st.markdown("""
    <style>
        .main .block-container { padding-top: 2rem !important; }
        header[data-testid="stHeader"] { z-index: 99; background: rgba(255,255,255,0.8); backdrop-filter: blur(10px); }
        .stButton button { border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.write(f"### ${row['precio']:.2f}")
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            guardar_item_carrito(st.session_state.user_data['user'], row, cant)
            st.toast("✅ Añadido al carrito")
            time.sleep(0.5); st.rerun()

# --- LÓGICA DE NAVEGACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u = st.text_input("Usuario (Email)").strip()
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u,)).fetchone()
        if res and res[1] == p:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Usuario o clave incorrectos")
else:
    user = st.session_state.user_data
    carrito_actual = obtener_carrito_db(user['user'])
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav = [f"🛒 Carrito ({len(carrito_actual)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin':
            nav = ["🛒 Comprar", "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Gestión Clientes"]
        menu = st.radio("Menú", nav)

    # --- TIENDA ---
    if "🛒" in menu or "Comprar" in menu:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar SKU...")
            cat_sel = c2.selectbox("Categoría", ["Seleccionar"] + sorted(df['categoria'].unique().tolist()))
            
            if busq or cat_sel != "Seleccionar":
                df_v = df.copy()
                if busq: df_v = df_v[df_v['sku'].str.contains(busq, case=False)]
                if cat_sel != "Seleccionar": df_v = df_v[df_v['categoria'] == cat_sel]
                cols = st.columns(4)
                for idx, row in df_v.reset_index().iterrows():
                    with cols[idx % 4]: card_producto(row, idx)
            else:
                st.info("👋 Selecciona una categoría o busca un SKU para empezar.")

        with t2:
            if not carrito_actual: st.info("Carrito vacío.")
            else:
                total = 0
                resumen = []
                for sku, info in carrito_actual.items():
                    sub = info['p'] * info['c']
                    total += sub
                    st.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']}) = **${sub:.2f}**")
                    if st.button("🗑️", key=f"rm_{sku}"):
                        eliminar_item_carrito(user['user'], sku); st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                st.divider()
                st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", use_container_width=True, type="primary"):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    get_connection().commit()
                    limpiar_carrito(user['user'])
                    st.success("¡Pedido enviado con éxito!"); time.sleep(1); st.rerun()

    # --- MIS PEDIDOS (CLIENTE) ---
    elif menu == "📜 Mis Pedidos":
        st.title("📜 Historial de Pedidos")
        mis_peds = pd.read_sql("SELECT * FROM pedidos WHERE username=? ORDER BY id DESC", get_connection(), params=(user['user'],))
        if mis_peds.empty:
            st.info("No has realizado pedidos aún.")
        else:
            for _, p in mis_peds.iterrows():
                with st.expander(f"Pedido #{p['id']} - {p['fecha']} - Total: ${p['total']:.2f}"):
                    st.table(pd.DataFrame(json.loads(p['items'])))

    # --- PEDIDOS TOTALES (ADMIN) ---
    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control Global de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['username']} ({p['fecha']})"):
                items_list = json.loads(p['items'])
                st.table(pd.DataFrame(items_list))
                st.write(f"### Total: ${p['total']:.2f}")
                
                c1, c2, c3 = st.columns(3)
                try:
                    pdf_bytes = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items_list, p['total'])
                    c1.download_button("📄 Descargar PDF", data=pdf_bytes, file_name=f"Pedido_{p['id']}.pdf", key=f"pdf_btn_{p['id']}", mime="application/pdf")
                except:
                    c1.error("Error al crear PDF")
                
                output_xl = io.BytesIO()
                with pd.ExcelWriter(output_xl, engine='openpyxl') as writer:
                    pd.DataFrame(items_list).to_excel(writer, index=False)
                c2.download_button("📈 Descargar Excel", data=output_xl.getvalue(), file_name=f"Pedido_{p['id']}.xlsx", key=f"xl_btn_{p['id']}")

                if c3.button("🗑️ Eliminar Pedido", key=f"del_adm_{p['id']}", type="secondary"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- GESTIÓN DE CLIENTES ---
    elif menu == "👥 Gestión Clientes":
        st.title("👥 Control Maestro de Clientes")
        tab_list, tab_new = st.tabs(["📝 Listado y Edición", "➕ Registrar Nuevo Cliente"])
        
        with tab_list:
            conn = get_connection()
            df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin' ORDER BY nombre ASC", conn)
            
            if df_u.empty:
                st.info("No hay clientes registrados.")
            else:
                for idx, row in df_u.iterrows():
                    u_id = row['username']
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        with c1:
                            st.subheader(f"🏢 {row['nombre']}")
                            st.write(f"**Usuario/ID:** `{u_id}`")
                            st.write(f"🔑 **Contraseña:** `{row['password']}`")
                            st.write(f"📞 **Teléfono:** {row['telefono'] if row['telefono'] else 'No asignado'}")
                            st.write(f"📍 **Dirección:** {row['direccion'] if row['direccion'] else 'No asignada'}")
                        
                        if c2.button("✏️ Editar Datos", key=f"btn_ed_{u_id}", use_container_width=True):
                            st.session_state[f"edit_active_{u_id}"] = True

                        if st.session_state.get(f"edit_active_{u_id}", False):
                            with st.form(f"form_edit_{u_id}"):
                                st.write(f"### Modificando cuenta: {u_id}")
                                new_nom = st.text_input("Nombre Completo / Razón Social", value=row['nombre'])
                                new_tel = st.text_input("Teléfono de Contacto", value=row['telefono'])
                                new_dir = st.text_area("Dirección Fiscal o de Despacho", value=row['direccion'])
                                new_pass = st.text_input("Nueva Contraseña", value=row['password'])
                                
                                col_f1, col_f2 = st.columns(2)
                                if col_f1.form_submit_button("💾 Guardar Cambios", use_container_width=True):
                                    conn.execute("""UPDATE usuarios SET nombre=?, telefono=?, direccion=?, password=? 
                                                 WHERE username=?""", (new_nom, new_tel, new_dir, new_pass, u_id))
                                    conn.commit()
                                    st.session_state[f"edit_active_{u_id}"] = False
                                    st.success(f"✅ Datos de {u_id} actualizados.")
                                    time.sleep(1); st.rerun()
                                
                                if col_f2.form_submit_button("❌ Cancelar", use_container_width=True):
                                    st.session_state[f"edit_active_{u_id}"] = False
                                    st.rerun()

        with tab_new:
            with st.form("nuevo_cliente_completo"):
                st.subheader("Crear Nueva Cuenta de Cliente")
                new_u = st.text_input("ID de Usuario o Email (Para el Login)")
                new_p = st.text_input("Contraseña de Acceso")
                new_n = st.text_input("Nombre de la Empresa o Cliente")
                new_t = st.text_input("Teléfono (Opcional)")
                new_d = st.text_area("Dirección (Opcional)")
                
                if st.form_submit_button("🚀 Registrar Cliente en el Sistema", use_container_width=True):
                    if new_u and new_p and new_n:
                        try:
                            conn = get_connection()
                            conn.execute(
                                "INSERT INTO usuarios (username, password, nombre, rol, direccion, telefono) VALUES (?,?,?,?,?,?)", 
                                (new_u, new_p, new_n, 'cliente', new_d, new_t)
                            )
                            conn.commit()
                            st.success(f"✅ Cliente '{new_n}' registrado con éxito.")
                            time.sleep(1); st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("❌ Error: Ese nombre de usuario ya está registrado.")
                    else:
                        st.warning("⚠️ Los campos Usuario, Clave y Nombre son obligatorios.")

    # --- CARGA PDF (CON BOTÓN DE PROCESAR Y LÓGICA BCV) ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo (Precio BCV)")
        st.info("Sube el PDF. El sistema extraerá el nombre y el precio exclusivamente de la columna **BCV**.")
        
        f = st.file_uploader("Seleccionar archivo PDF", type="pdf")
        
        if f is not None:
            # BOTÓN DE PROCESAR AÑADIDO E INTEGRADO
            if st.button("🚀 Iniciar Procesamiento de PDF", use_container_width=True, type="primary"):
                with st.spinner("Extrayendo precios BCV e ignorando tablas ocultas..."):
                    cantidad = procesar_pdf_bcv(f)
                    if cantidad > 0:
                        st.success(f"✅ ¡Éxito! Se cargaron/actualizaron {cantidad} productos con el precio BCV.")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error("No se detectaron productos. Verifica que el PDF contenga la palabra 'BCV'.")