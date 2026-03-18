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
# Usamos v5 para garantizar que Streamlit cree un archivo desde cero con las columnas correctas
DB_NAME = "database_color_v5.db"
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

# --- INICIALIZACIÓN (TODAS LAS COLUMNAS) ---
def init_db():
    conn = get_connection()
    # Tabla de productos: SKU, Descripción, PRECIO DIVISA, PRECIO BCV
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT, foto_path TEXT)''')
    
    # Tabla de usuarios: Soporte para dirección y teléfono
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    
    # Tabla de pedidos
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Tabla de carrito
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')

    # Administrador por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- PROCESADOR PDF DUAL ---
def procesar_pdf_dual(file):
    conn = get_connection()
    productos_cargados = 0
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                col_divisa, col_bcv = -1, -1
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
                        
                        def limpiar(val):
                            if not val: return 0.0
                            v = re.sub(r'[^\d,.]', '', str(val))
                            try: return float(v.replace(',', '.'))
                            except: return 0.0

                        p_div = limpiar(row[col_divisa]) if col_divisa != -1 else 0.0
                        p_bcv = limpiar(row[col_bcv]) if col_bcv != -1 else 0.0

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

# --- GENERADOR PDF ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(190, 10, "COLOR INSUMOS - COMPROBANTE", ln=True, align="C")
    pdf.set_font("helvetica", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 10, "SKU", 1); pdf.cell(90, 10, "Descripcion", 1)
    pdf.cell(20, 10, "Cant.", 1); pdf.cell(50, 10, "Subtotal", 1); pdf.ln()
    pdf.set_font("helvetica", "", 9)
    for item in items:
        pdf.cell(30, 8, str(item['SKU']), 1)
        pdf.cell(90, 8, str(item['Desc'])[:45], 1)
        pdf.cell(20, 8, str(item['Cant']), 1)
        pdf.cell(50, 8, f"${item['Subtotal']:.2f}", 1); pdf.ln()
    pdf.ln(5); pdf.set_font("helvetica", "B", 12)
    pdf.cell(190, 10, f"TOTAL: ${total:.2f}", ln=True, align="R")
    return bytes(pdf.output())

# --- INICIO DE APP ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Error de acceso")
else:
    user = st.session_state.user_data
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Salir"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav = ["🛒 Tienda", "📊 Pedidos", "📁 Cargar PDF", "👥 Clientes"] if user['rol'] == 'admin' else ["🛒 Tienda", "📜 Mis Pedidos"]
        menu = st.radio("Menú", nav)

    # --- MÓDULO TIENDA ---
    if menu == "🛒 Tienda":
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            busq = st.text_input("🔍 Buscar...")
            if busq: df = df[df['sku'].str.contains(busq, case=False) | df['descripcion'].str.contains(busq, case=False)]
            cols = st.columns(3)
            for idx, row in df.reset_index().iterrows():
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.write(f"**{row['sku']}**")
                        st.write(f"💵: **${row['precio_divisa']:.2f}** | 🏦: **{row['precio_bcv']:.2f}**")
                        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                        if st.button("➕ Añadir", key=f"b_{row['sku']}"):
                            conn = get_connection()
                            conn.execute("INSERT OR REPLACE INTO carrito_items VALUES (?,?,?,?,?,?)", 
                                         (user['user'], row['sku'], row['descripcion'], row['precio_divisa'], row['precio_bcv'], cant))
                            conn.commit(); st.toast("Añadido")
        with t2:
            cart = pd.read_sql("SELECT * FROM carrito_items WHERE username=?", get_connection(), params=(user['user'],))
            if cart.empty: st.info("Carrito vacío")
            else:
                total = 0; resumen = []
                for _, item in cart.iterrows():
                    sub = item['precio_divisa'] * item['cantidad']
                    total += sub
                    st.write(f"{item['sku']} x{item['cantidad']} - ${sub:.2f}")
                    resumen.append({"SKU": item['sku'], "Desc": item['descripcion'], "Cant": item['cantidad'], "Subtotal": sub})
                if st.button("Confirmar Pedido"):
                    conn = get_connection()
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%Y"), json.dumps(resumen), total, "Pendiente"))
                    conn.execute("DELETE FROM carrito_items WHERE username=?", (user['user'],))
                    conn.commit(); st.success("Pedido enviado"); st.rerun()

    # --- MÓDULO CLIENTES ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        lista, nuevo = st.tabs(["Lista", "Registrar"])
        with lista:
            cl = pd.read_sql("SELECT * FROM usuarios WHERE rol='cliente'", get_connection())
            for _, c in cl.iterrows():
                with st.expander(f"🏢 {c['nombre']}"):
                    st.write(f"Usuario: {c['username']} | Clave: {c['password']}")
                    st.write(f"📞 {c['telefono']} | 📍 {c['direccion']}")
                    if st.button("Eliminar", key=f"d_{c['username']}"):
                        get_connection().execute("DELETE FROM usuarios WHERE username=?", (c['username'],))
                        get_connection().commit(); st.rerun()
        with nuevo:
            with st.form("f_cli"):
                nu = st.text_input("Usuario"); np = st.text_input("Clave")
                nn = st.text_input("Empresa"); nt = st.text_input("Tel"); nd = st.text_area("Dir")
                if st.form_submit_button("Guardar"):
                    get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol, direccion, telefono) VALUES (?,?,?,?,?,?)", 
                                 (nu, np, nn, 'cliente', nd, nt))
                    get_connection().commit(); st.success("Registrado")

    # --- MÓDULO PEDIDOS ---
    elif menu == "📊 Pedidos":
        st.title("📊 Historial")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 #{p['id']} - {p['username']}"):
                items = json.loads(p['items'])
                st.table(pd.DataFrame(items))
                st.write(f"**Total: ${p['total']:.2f}**")
                pdf = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items, p['total'])
                st.download_button("Descargar PDF", pdf, f"Pedido_{p['id']}.pdf", key=f"f_{p['id']}")
                if st.button("Eliminar", key=f"p_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Cargar Precios")
        f = st.file_uploader("PDF con DIVISA y BCV", type="pdf")
        if f and st.button("Procesar"):
            cant = procesar_pdf_dual(f)
            st.success(f"Actualizados {cant} productos"); time.sleep(1); st.rerun()