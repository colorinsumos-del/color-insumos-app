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

def borrar_catalogo_completo():
    conn = get_connection()
    conn.execute("DELETE FROM productos")
    conn.commit()
    st.cache_data.clear()

# --- INICIALIZACIÓN ROBUSTA (MIGRACIÓN AUTOMÁTICA) ---
def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Crear tablas con estructura completa
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT, foto_path TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')

    # MIGRACIÓN: Verificar y añadir columnas faltantes para evitar el OperationalError
    cursor.execute("PRAGMA table_info(productos)")
    columnas = [col[1] for col in cursor.fetchall()]
    if "precio_divisa" not in columnas:
        try: conn.execute("ALTER TABLE productos ADD COLUMN precio_divisa REAL DEFAULT 0.0")
        except: pass
    if "precio_bcv" not in columnas:
        try: conn.execute("ALTER TABLE productos ADD COLUMN precio_bcv REAL DEFAULT 0.0")
        except: pass

    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- EXTRACCIÓN DUAL (DIVISA Y BCV) ---
def procesar_pdf_dual(file):
    conn = get_connection()
    productos_cargados = 0
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                col_divisa, col_bcv = -1, -1
                
                # Buscar encabezados de precio
                for row_idx in range(min(5, len(table))):
                    row_cells = [str(c).upper() if c else "" for c in table[row_idx]]
                    for i, cell in enumerate(row_cells):
                        if any(x in cell for x in ["DIVISA", "DOLARES", "USD", "$"]): col_divisa = i
                        if "BCV" in cell: col_bcv = i
                    if col_divisa != -1 or col_bcv != -1: break

                if col_divisa != -1 or col_bcv != -1:
                    for row in table:
                        if not row or len(row) < 2: continue
                        sku = str(row[0]).strip() if row[0] else ""
                        if not sku or sku.upper() in ["SKU", "CODIGO", "ITEM", "PRODUCTO"]: continue
                        
                        descripcion = str(row[1]).strip() if row[1] else ""
                        
                        def limpiar_num(val):
                            if not val: return 0.0
                            v = re.sub(r'[^\d,.]', '', str(val))
                            try: return float(v.replace(',', '.'))
                            except: return 0.0

                        p_div = limpiar_num(row[col_divisa]) if col_divisa != -1 else 0.0
                        p_bcv = limpiar_num(row[col_bcv]) if col_bcv != -1 else 0.0

                        conn.execute("""
                            INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                            VALUES (?, ?, ?, ?, 'General')
                            ON CONFLICT(sku) DO UPDATE SET 
                                precio_divisa=excluded.precio_divisa,
                                precio_bcv=excluded.precio_bcv,
                                descripcion=excluded.descripcion
                        """, (sku, descripcion, p_div, p_bcv))
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
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 10, "SKU", 1); pdf.cell(90, 10, "Descripcion", 1)
    pdf.cell(20, 10, "Cant.", 1); pdf.cell(50, 10, "Subtotal $", 1); pdf.ln()
    pdf.set_font("helvetica", "", 9)
    for item in items:
        pdf.cell(30, 8, str(item.get('SKU', 'N/A')), 1)
        pdf.cell(90, 8, str(item.get('Desc', ''))[:45], 1)
        pdf.cell(20, 8, str(item.get('Cant', '0')), 1)
        pdf.cell(50, 8, f"${item.get('Subtotal', 0):.2f}", 1); pdf.ln()
    pdf.ln(5); pdf.set_font("helvetica", "B", 12)
    pdf.cell(190, 10, f"TOTAL FINAL: ${total:.2f}", ln=True, align="R")
    return bytes(pdf.output())

# --- INTERFAZ PRINCIPAL ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u,)).fetchone()
        if res and res[1] == p:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Acceso incorrecto")
else:
    user = st.session_state.user_data
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav_options = ["🛒 Comprar", "📊 Pedidos", "📁 Cargar PDF", "👥 Clientes"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav_options)

    # --- MÓDULO TIENDA/CARRITO ---
    if menu == "🛒 Comprar":
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            busq = st.text_input("🔍 Buscar por SKU o Descripción...")
            if busq: df = df[df['sku'].str.contains(busq, case=False) | df['descripcion'].str.contains(busq, case=False)]
            
            cols = st.columns(3)
            for idx, row in df.reset_index().iterrows():
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.write(f"**{row['sku']}**")
                        st.write(f"💵 Divisa: **${row['precio_divisa']:.2f}**")
                        st.write(f"🏦 BCV: **{row['precio_bcv']:.2f} Bs.**")
                        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                        if st.button("➕ Añadir", key=f"b_{row['sku']}", use_container_width=True):
                            conn = get_connection()
                            conn.execute("INSERT OR REPLACE INTO carrito_items VALUES (?,?,?,?,?,?)", 
                                         (user['user'], row['sku'], row['descripcion'], row['precio_divisa'], row['precio_bcv'], cant))
                            conn.commit()
                            st.toast("✅ Añadido")

        with t2:
            cart_data = pd.read_sql("SELECT * FROM carrito_items WHERE username=?", get_connection(), params=(user['user'],))
            if cart_data.empty: st.info("Carrito vacío")
            else:
                total = 0; resumen_items = []
                for _, item in cart_data.iterrows():
                    sub = item['precio_divisa'] * item['cantidad']
                    total += sub
                    st.write(f"**{item['sku']}** - {item['cantidad']} und. (${sub:.2f})")
                    resumen_items.append({"SKU": item['sku'], "Desc": item['descripcion'], "Cant": item['cantidad'], "Subtotal": sub})
                
                st.write(f"### Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", use_container_width=True, type="primary"):
                    conn = get_connection()
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen_items), total, "Pendiente"))
                    conn.execute("DELETE FROM carrito_items WHERE username=?", (user['user'],))
                    conn.commit(); st.success("Pedido enviado"); time.sleep(1); st.rerun()

    # --- MÓDULO CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo")
        with st.expander("⚠️ LIMPIEZA TOTAL"):
            if st.button("🗑️ Borrar Productos Actuales"):
                borrar_catalogo_completo(); st.success("Base de datos limpia"); st.rerun()
        
        f = st.file_uploader("Subir PDF de Precios", type="pdf")
        if f and st.button("🚀 Procesar Precios BCV y Divisa"):
            with st.spinner("Procesando..."):
                cant = procesar_pdf_dual(f)
                st.success(f"✅ Se actualizaron {cant} productos."); time.sleep(1); st.rerun()

    # --- MÓDULO PEDIDOS ---
    elif menu == "📊 Pedidos":
        st.title("📊 Control de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['username']} - {p['fecha']}"):
                items = json.loads(p['items'])
                st.table(pd.DataFrame(items))
                st.write(f"**Total: ${p['total']:.2f}**")
                pdf_b = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items, p['total'])
                st.download_button("📄 Bajar PDF", pdf_b, f"Pedido_{p['id']}.pdf", key=f"pdf_{p['id']}")
                if st.button("🗑️ Eliminar", key=f"del_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- MÓDULO CLIENTES ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        with st.form("nuevo_u"):
            st.write("### Registrar Nuevo")
            new_u = st.text_input("Usuario (Email)"); new_p = st.text_input("Clave")
            new_n = st.text_input("Nombre de Empresa")
            if st.form_submit_button("Registrar"):
                try:
                    get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", (new_u, new_p, new_n, 'cliente'))
                    get_connection().commit(); st.success("Registrado"); st.rerun()
                except: st.error("El usuario ya existe")
        
        st.write("### Lista de Clientes")
        df_u = pd.read_sql("SELECT username, nombre, rol FROM usuarios WHERE rol='cliente'", get_connection())
        st.dataframe(df_u, use_container_width=True)