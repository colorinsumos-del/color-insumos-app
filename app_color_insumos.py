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
# Cambiamos el nombre a v3 para forzar la creación de una base de datos limpia
DB_NAME = "catalogo_color_v3.db"
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

# --- INICIALIZACIÓN COMPLETA ---
def init_db():
    conn = get_connection()
    # Productos con soporte dual (Divisa y BCV)
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT, foto_path TEXT)''')
    
    # Usuarios con todos los campos de la v4.3
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    
    # Historial de Pedidos
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Carrito de Compras
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito_items 
                 (username TEXT, sku TEXT, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, cantidad INTEGER, 
                  PRIMARY KEY (username, sku))''')

    # Usuario Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

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
                
                # Identificación dinámica de columnas
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
                        
                        def limpiar_monto(val):
                            if not val: return 0.0
                            v = re.sub(r'[^\d,.]', '', str(val))
                            try: return float(v.replace(',', '.'))
                            except: return 0.0

                        p_div = limpiar_monto(row[col_divisa]) if col_divisa != -1 else 0.0
                        p_bcv = limpiar_monto(row[col_bcv]) if col_bcv != -1 else 0.0

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

# --- GENERADOR DE REPORTE PDF ---
def generar_pdf_pedido(id_pedido, fecha, usuario, items, total):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(190, 10, "COLOR INSUMOS - COMPROBANTE DE PEDIDO", ln=True, align="C")
    pdf.set_font("helvetica", "", 12)
    pdf.cell(190, 10, f"Pedido #: {id_pedido} | Fecha: {fecha}", ln=True, align="C")
    pdf.cell(190, 10, f"Cliente: {usuario}", ln=True, align="C")
    pdf.ln(10)
    
    # Encabezados de tabla
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
    pdf.cell(190, 10, f"TOTAL A PAGAR: ${total:.2f}", ln=True, align="R")
    return bytes(pdf.output())

# --- LÓGICA DE NAVEGACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u = st.text_input("Usuario (Email)")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        nav = ["🛒 Comprar", "📊 Historial Pedidos", "📁 Cargar PDF", "👥 Clientes"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Menú Principal", nav)

    # --- TIENDA Y CARRITO ---
    if menu == "🛒 Comprar":
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Carrito de Compras"])
        with t1:
            df = obtener_catalogo_cache()
            busq = st.text_input("🔍 Buscar por SKU o Nombre del producto...")
            if busq: df = df[df['sku'].str.contains(busq, case=False) | df['descripcion'].str.contains(busq, case=False)]
            
            cols = st.columns(3)
            for idx, row in df.reset_index().iterrows():
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.write(f"**{row['sku']}**")
                        st.write(f"{row['descripcion']}")
                        st.write(f"💵 Divisa: **${row['precio_divisa']:.2f}**")
                        st.write(f"🏦 BCV: **{row['precio_bcv']:.2f} Bs.**")
                        cant = st.number_input("Cantidad", 1, 500, 1, key=f"q_{row['sku']}")
                        if st.button("➕ Añadir", key=f"b_{row['sku']}", use_container_width=True):
                            conn = get_connection()
                            conn.execute("INSERT OR REPLACE INTO carrito_items VALUES (?,?,?,?,?,?)", 
                                         (user['user'], row['sku'], row['descripcion'], row['precio_divisa'], row['precio_bcv'], cant))
                            conn.commit()
                            st.toast(f"Añadido: {row['sku']}")

        with t2:
            cart = pd.read_sql("SELECT * FROM carrito_items WHERE username=?", get_connection(), params=(user['user'],))
            if cart.empty: st.info("Tu carrito está esperando productos.")
            else:
                total_usd = 0; resumen = []
                for _, item in cart.iterrows():
                    sub = item['precio_divisa'] * item['cantidad']
                    total_usd += sub
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"**{item['sku']}** - {item['cantidad']} und. | Sub: ${sub:.2f}")
                    if c2.button("🗑️", key=f"del_{item['sku']}"):
                        get_connection().execute("DELETE FROM carrito_items WHERE username=? AND sku=?", (user['user'], item['sku']))
                        get_connection().commit(); st.rerun()
                    resumen.append({"SKU": item['sku'], "Desc": item['descripcion'], "Cant": item['cantidad'], "Subtotal": sub})
                
                st.divider()
                st.write(f"### Total del Pedido: ${total_usd:.2f}")
                if st.button("🚀 Confirmar y Enviar Pedido", use_container_width=True, type="primary"):
                    conn = get_connection()
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(resumen), total_usd, "Pendiente"))
                    conn.execute("DELETE FROM carrito_items WHERE username=?", (user['user'],))
                    conn.commit(); st.success("¡Pedido procesado con éxito!"); time.sleep(1); st.rerun()

    # --- GESTIÓN DE CLIENTES (RESTAURADA) ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Cartera de Clientes")
        tab_l, tab_r = st.tabs(["📋 Listado Actual", "➕ Registrar Cliente"])
        
        with tab_l:
            clientes = pd.read_sql("SELECT username, nombre, telefono, direccion FROM usuarios WHERE rol='cliente'", get_connection())
            if clientes.empty: st.warning("No hay clientes registrados aún.")
            else:
                for _, c in clientes.iterrows():
                    with st.expander(f"🏢 {c['nombre']} ({c['username']})"):
                        st.write(f"📞 Teléfono: {c['telefono']}")
                        st.write(f"📍 Dirección: {c['direccion']}")
                        if st.button("Eliminar Cliente", key=f"dcli_{c['username']}"):
                            get_connection().execute("DELETE FROM usuarios WHERE username=?", (c['username'],))
                            get_connection().commit(); st.rerun()

        with tab_r:
            with st.form("registro_cliente"):
                nu = st.text_input("Usuario / Email")
                np = st.text_input("Contraseña Temporal")
                nn = st.text_input("Nombre de la Empresa / Cliente")
                nt = st.text_input("Teléfono de Contacto")
                nd = st.text_area("Dirección Fiscal/Despacho")
                if st.form_submit_button("Guardar Cliente"):
                    if nu and np and nn:
                        try:
                            get_connection().execute("INSERT INTO usuarios (username, password, nombre, rol, direccion, telefono) VALUES (?,?,?,?,?,?)", 
                                         (nu, np, nn, 'cliente', nd, nt))
                            get_connection().commit(); st.success("Cliente guardado correctamente."); st.rerun()
                        except: st.error("Ese usuario ya existe.")
                    else: st.warning("Por favor, llena los campos obligatorios.")

    # --- HISTORIAL DE PEDIDOS ---
    elif menu == "📊 Historial Pedidos":
        st.title("📊 Control de Ventas y Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['username']} ({p['fecha']})"):
                items_p = json.loads(p['items'])
                st.table(pd.DataFrame(items_p))
                st.write(f"**Total Pagado: ${p['total']:.2f}**")
                pdf_gen = generar_pdf_pedido(p['id'], p['fecha'], p['username'], items_p, p['total'])
                st.download_button("📄 Descargar Comprobante PDF", pdf_gen, f"Pedido_{p['id']}.pdf", key=f"pdf_{p['id']}")
                if st.button("🗑️ Eliminar Pedido", key=f"pdel_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- CARGA DE PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualización Masiva de Catálogo")
        st.info("Sube tu lista de precios en PDF. El sistema detectará automáticamente las columnas 'DIVISA' y 'BCV'.")
        f = st.file_uploader("Arrastra tu PDF aquí", type="pdf")
        if f and st.button("🚀 Procesar e Importar Precios", type="primary"):
            with st.spinner("Leyendo tablas y actualizando base de datos..."):
                cant = procesar_pdf_dual(f)
                if cant > 0:
                    st.success(f"Se han actualizado {cant} productos con éxito.")
                    time.sleep(1); st.rerun()
                else: st.error("No se encontraron columnas de precios válidas en el PDF.")