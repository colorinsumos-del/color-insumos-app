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

def borrar_catalogo_completo():
    conn = get_connection()
    conn.execute("DELETE FROM productos")
    conn.commit()
    st.cache_data.clear()

# --- INICIALIZACIÓN DE BASE DE DATOS (CON MIGRACIÓN AUTOMÁTICA) ---
def init_db():
    conn = get_connection()
    # 1. Crear tablas si no existen
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT DEFAULT '', telefono TEXT DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')
    
    # 2. MIGRACIÓN: Verificar si faltan columnas en tablas existentes
    cursor = conn.cursor()
    # Check productos
    cursor.execute("PRAGMA table_info(productos)")
    cols = [column[1] for column in cursor.fetchall()]
    if "precio_divisa" not in cols:
        conn.execute("ALTER TABLE productos ADD COLUMN precio_divisa REAL DEFAULT 0.0")
    if "precio_bcv" not in cols:
        conn.execute("ALTER TABLE productos ADD COLUMN precio_bcv REAL DEFAULT 0.0")
        
    # Check carrito_items
    cursor.execute("PRAGMA table_info(carrito_items)")
    cols_cart = [column[1] for column in cursor.fetchall()]
    if "precio_divisa" not in cols_cart:
        conn.execute("ALTER TABLE carrito_items ADD COLUMN precio_divisa REAL DEFAULT 0.0")
    if "precio_bcv" not in cols_cart:
        conn.execute("ALTER TABLE carrito_items ADD COLUMN precio_bcv REAL DEFAULT 0.0")

    # Usuario Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- FUNCIÓN DE EXTRACCIÓN DUAL (DIVISA Y BCV) ---
def procesar_pdf_dual(file):
    conn = get_connection()
    productos_cargados = 0
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                col_divisa = -1
                col_bcv = -1
                
                # Buscador de encabezados
                for row_idx in range(min(5, len(table))):
                    row_cells = [str(c).upper() if c else "" for c in table[row_idx]]
                    for i, cell in enumerate(row_cells):
                        if "DIVISA" in cell or "DOLARES" in cell or "USD" in cell: col_divisa = i
                        if "BCV" in cell or "PRECIO BCV" in cell: col_bcv = i
                    if col_divisa != -1 or col_bcv != -1: break

                if col_divisa != -1 or col_bcv != -1:
                    for row in table:
                        if not row or len(row) < 2: continue
                        sku = str(row[0]).strip() if row[0] else ""
                        if not sku or sku.upper() in ["SKU", "CODIGO", "ITEM", "PRODUCTO"]: continue
                        
                        descripcion = str(row[1]).strip() if row[1] else ""
                        
                        # Extraer Precio Divisas
                        p_divisa = 0.0
                        if col_divisa != -1 and len(row) > col_divisa:
                            val = re.sub(r'[^\d,.]', '', str(row[col_divisa]))
                            try: p_divisa = float(val.replace(',', '.')) if val else 0.0
                            except: p_divisa = 0.0

                        # Extraer Precio BCV
                        p_bcv = 0.0
                        if col_bcv != -1 and len(row) > col_bcv:
                            val = re.sub(r'[^\d,.]', '', str(row[col_bcv]))
                            try: p_bcv = float(val.replace(',', '.')) if val else 0.0
                            except: p_bcv = 0.0

                        conn.execute("""
                            INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                            VALUES (?, ?, ?, ?, 'General')
                            ON CONFLICT(sku) DO UPDATE SET 
                                precio_divisa=excluded.precio_divisa,
                                precio_bcv=excluded.precio_bcv,
                                descripcion=excluded.descripcion
                        """, (sku, descripcion, p_divisa, p_bcv))
                        productos_cargados += 1
    
    conn.commit()
    st.cache_data.clear() 
    return productos_cargados

# --- GENERADOR DE PDF ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(190, 10, "COLOR INSUMOS - REPORTE DE PEDIDO", ln=True, align="C")
    pdf.set_font("helvetica", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("helvetica", "B", 9)
    pdf.cell(25, 10, "SKU", 1); pdf.cell(85, 10, "Descripcion", 1)
    pdf.cell(15, 10, "Cant.", 1); pdf.cell(30, 10, "Precio Unit.", 1); pdf.cell(35, 10, "Subtotal", 1); pdf.ln()
    pdf.set_font("helvetica", "", 8)
    for item in items:
        pdf.cell(25, 8, str(item.get('SKU', 'N/A')), 1)
        pdf.cell(85, 8, str(item.get('Desc', ''))[:45], 1)
        pdf.cell(15, 8, str(item.get('Cant', '0')), 1)
        pdf.cell(30, 8, f"${item.get('P_Unit', 0):.2f}", 1)
        pdf.cell(35, 8, f"${item.get('Subtotal', 0):.2f}", 1); pdf.ln()
    pdf.ln(5); pdf.set_font("helvetica", "B", 12)
    pdf.cell(190, 10, f"TOTAL: ${total:.2f}", ln=True, align="R")
    return bytes(pdf.output())

# --- FUNCIONES DE CARRITO ---
def guardar_item_carrito(username, row, cant):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carrito_items (username, sku, descripcion, precio_divisa, precio_bcv, cantidad) VALUES (?,?,?,?,?,?)", 
                 (username, row['sku'], row['descripcion'], row['precio_divisa'], row['precio_bcv'], cant))
    conn.commit()

def obtener_carrito_db(username):
    conn = get_connection()
    # Ahora la consulta incluye los nuevos campos
    res = conn.execute("SELECT sku, descripcion, precio_divisa, precio_bcv, cantidad FROM carrito_items WHERE username=?", (username,)).fetchall()
    return {item[0]: {"desc": item[1], "p_div": item[2], "p_bcv": item[3], "c": item[4]} for item in res}

# --- INTERFAZ ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u = st.text_input("Usuario").strip()
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u,)).fetchone()
        if res and res[1] == p:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Error de acceso")
else:
    user = st.session_state.user_data
    carrito_actual = obtener_carrito_db(user['user'])
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav = ["🛒 Comprar", "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Gestión Clientes"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Menú", nav)

    if "Comprar" in menu or "🛒" in menu:
        t1, t2 = st.tabs(["🛍️ Catálogo Dual", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            busq = st.text_input("🔍 Buscar por SKU o Nombre...")
            if busq: df = df[df['sku'].str.contains(busq, case=False) | df['descripcion'].str.contains(busq, case=False)]
            
            cols = st.columns(3)
            for idx, row in df.reset_index().iterrows():
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.write(f"**{row['sku']}**")
                        st.write(f"{row['descripcion']}")
                        st.write(f"💵 **Divisa:** ${row['precio_divisa']:.2f}")
                        st.write(f"🏦 **BCV:** {row['precio_bcv']:.2f} Bs.")
                        cant = st.number_input("Cantidad", 1, 100, 1, key=f"q_{row['sku']}")
                        if st.button("➕ Añadir", key=f"b_{row['sku']}", use_container_width=True):
                            guardar_item_carrito(user['user'], row, cant)
                            st.toast("✅ Añadido")
                            time.sleep(0.5); st.rerun()
        with t2:
            if not carrito_actual: st.info("Carrito vacío")
            else:
                total = 0; resumen = []
                for sku, info in carrito_actual.items():
                    sub = info['p_div'] * info['c']; total += sub
                    st.write(f"**{sku}** - {info['desc']} | Cant: {info['c']} | Sub: ${sub:.2f}")
                    if st.button("🗑️", key=f"rm_{sku}"):
                        get_connection().execute("DELETE FROM carrito_items WHERE username=? AND sku=?", (user['user'], sku))
                        get_connection().commit(); st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "P_Unit": info['p_div'], "Subtotal": sub})
                st.write(f"### Total Pedido: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    get_connection().commit(); 
                    get_connection().execute("DELETE FROM carrito_items WHERE username=?", (user['user'],))
                    st.success("Pedido enviado con éxito"); time.sleep(1); st.rerun()

    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualización de Catálogo Dual")
        with st.expander("⚠️ ZONA DE LIMPIEZA"):
            if st.button("🗑️ Borrar Todo el Catálogo Actual"):
                borrar_catalogo_completo(); st.success("Catálogo vaciado."); time.sleep(1); st.rerun()
        
        st.info("Sube tu PDF. El sistema buscará las columnas de **DIVISA** (o Dólares) y **BCV**.")
        f = st.file_uploader("Seleccionar archivo PDF", type="pdf")
        if f and st.button("🚀 Procesar Precios"):
            with st.spinner("Escaneando tablas..."):
                cant = procesar_pdf_dual(f)
                if cant > 0:
                    st.success(f"✅ ¡Éxito! Se actualizaron {cant} productos.")
                    time.sleep(2); st.rerun()
                else:
                    st.error("No se detectaron las columnas de precios.")

    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['username']}"):
                items_list = json.loads(p['items'])
                st.table(pd.DataFrame(items_list))
                pdf_b = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items_list, p['total'])
                st.download_button("📄 Descargar PDF", data=pdf_b, file_name=f"Pedido_{p['id']}.pdf", key=f"pdf_{p['id']}")
                if st.button("🗑️ Eliminar Pedido", key=f"del_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    elif menu == "👥 Gestión Clientes":
        st.title("👥 Gestión de Usuarios")
        tab1, tab2 = st.tabs(["Lista de Clientes", "Registrar Nuevo"])
        with tab1:
            df_u = pd.read_sql("SELECT username, nombre, telefono, direccion FROM usuarios WHERE rol != 'admin'", get_connection())
            st.dataframe(df_u, use_container_width=True)
        with tab2:
            with st.form("nuevo_u"):
                u = st.text_input("Usuario (Email/ID)")
                p = st.text_input("Clave")
                n = st.text_input("Nombre de la Empresa")
                if st.form_submit_button("Registrar Cliente"):
                    try:
                        get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (u, p, n, 'cliente'))
                        get_connection().commit(); st.success("Registrado"); time.sleep(1); st.rerun()
                    except: st.error("El usuario ya existe.")