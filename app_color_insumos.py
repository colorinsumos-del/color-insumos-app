import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import time
import re
import pdfplumber
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURACIÓN ---
DB_NAME = "color_insumos_v25.db" # Nueva base de datos limpia
st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- ESTILOS VISUALES ---
st.markdown("""
    <style>
    .product-card {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #e1e4e8;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 15px;
        transition: transform 0.2s;
    }
    .product-card:hover { transform: scale(1.02); }
    .price-bcv { color: #2e7d32; font-size: 22px; font-weight: bold; margin: 10px 0; }
    .product-name { font-weight: 600; font-size: 14px; height: 40px; overflow: hidden; color: #333; }
    .sku-label { font-size: 11px; color: #888; margin-top: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- MOTOR DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito 
                 (username TEXT, sku TEXT, nombre TEXT, precio_bcv REAL, cantidad INTEGER, PRIMARY KEY(username, sku))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Usuario Administrador por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- PROCESADOR PDF (RETORNO AL MOTOR ORIGINAL) ---
def procesar_pdf_dual(file):
    conn = get_connection()
    productos_cargados = 0
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2: continue
                
                # Identificar columnas
                col_div, col_bcv = -1, -1
                header = [str(c).upper() if c else "" for c in table[0]]
                for i, cell in enumerate(header):
                    if any(x in cell for x in ["DIVISA", "USD", "$"]): col_div = i
                    if "BCV" in cell: col_bcv = i

                for row in table[1:]:
                    if not row or len(row) < 2: continue
                    sku = str(row[0]).strip()
                    if not sku or sku.upper() in ["SKU", "None", "CODIGO"]: continue
                    
                    desc = str(row[1]).strip()
                    
                    def limpiar(val):
                        if not val: return 0.0
                        v = re.sub(r'[^\d,.]', '', str(val))
                        try: return float(v.replace(',', '.'))
                        except: return 0.0

                    p_div = limpiar(row[col_div]) if col_div != -1 else 0.0
                    p_bcv = limpiar(row[col_bcv]) if col_bcv != -1 else 0.0

                    conn.execute("""INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                                 VALUES (?, ?, ?, ?, 'General')
                                 ON CONFLICT(sku) DO UPDATE SET 
                                 descripcion=excluded.descripcion, precio_divisa=excluded.precio_divisa, precio_bcv=excluded.precio_bcv""",
                                 (sku, desc, p_div, p_bcv))
                    productos_cargados += 1
    conn.commit()
    return productos_cargados

# --- LÓGICA DE APLICACIÓN ---
init_db()

if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    with st.form("login"):
        u = st.text_input("Usuario")
        p = st.text_input("Clave", type="password")
        if st.form_submit_button("Entrar"):
            res = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
            if res and res[1] == p:
                st.session_state.auth, st.session_state.user = True, {"id": res[0], "nombre": res[2], "rol": res[3]}
                st.rerun()
            else: st.error("Acceso incorrecto")
else:
    user = st.session_state.user
    menu = st.sidebar.radio("Navegación", ["🛒 Tienda", "🧾 Mi Carrito", "📊 Pedidos", "👥 Clientes", "📁 Cargar PDF"])

    if menu == "🛒 Tienda":
        st.title("🛍️ Catálogo de Productos")
        prods = pd.read_sql("SELECT * FROM productos", get_connection())
        
        busq = st.text_input("🔍 Buscar por SKU o Nombre...")
        if busq: prods = prods[prods['descripcion'].str.contains(busq, case=False) | prods['sku'].str.contains(busq, case=False)]
        
        if prods.empty: st.info("Sube un PDF para ver los productos.")
        else:
            cols = st.columns(4)
            for idx, row in prods.iterrows():
                with cols[idx % 4]:
                    st.markdown(f"""
                    <div class="product-card">
                        <div class="product-name">{row['descripcion']}</div>
                        <div class="price-bcv">{row['precio_bcv']:.2f} Bs.</div>
                        <div class="sku-label">SKU: {row['sku']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button("Añadir 🛒", key=f"add_{row['sku']}", use_container_width=True):
                        conn = get_connection()
                        conn.execute("INSERT OR REPLACE INTO carrito VALUES (?,?,?,?,?)",
                                    (user['id'], row['sku'], row['descripcion'], row['precio_bcv'], 1))
                        conn.commit()
                        st.toast(f"✅ Añadido: {row['sku']}")

    elif menu == "🧾 Mi Carrito":
        st.title("🧾 Tu Pedido")
        items = pd.read_sql("SELECT * FROM carrito WHERE username=?", get_connection(), params=(user['id'],))
        if items.empty: st.warning("El carrito está vacío.")
        else:
            total = 0
            for _, item in items.iterrows():
                sub = item['precio_bcv'] * item['cantidad']
                total += sub
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{item['nombre']}**")
                nueva_q = c2.number_input("Cant.", 1, 100, item['cantidad'], key=f"q_{item['sku']}")
                if nueva_q != item['cantidad']:
                    get_connection().execute("UPDATE carrito SET cantidad=? WHERE username=? AND sku=?", (nueva_q, user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
                if c3.button("🗑️", key=f"del_{item['sku']}"):
                    get_connection().execute("DELETE FROM carrito WHERE username=? AND sku=?", (user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
            
            # REGLA DE DESCUENTO: 10% si supera los 5000 Bs (puedes ajustar)
            desc = total * 0.10 if total > 5000 else 0
            neto = total - desc
            
            st.divider()
            st.write(f"Subtotal: {total:.2f} Bs.")
            if desc > 0: st.success(f"🎁 Descuento (10%): -{desc:.2f} Bs.")
            st.write(f"### TOTAL: {neto:.2f} Bs.")
            
            if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                             (user['id'], datetime.now().strftime("%d/%m/%Y"), items.to_json(), neto, "Pendiente"))
                conn.execute("DELETE FROM carrito WHERE username=?", (user['id'],))
                conn.commit(); st.success("Pedido enviado con éxito"); time.sleep(1); st.rerun()

    elif menu == "📁 Cargar PDF" and user['rol'] == 'admin':
        st.title("📁 Cargar Lista de Precios")
        f = st.file_uploader("Sube el PDF de inventario", type=["pdf"])
        if f and st.button("Procesar PDF"):
            num = procesar_pdf_dual(f)
            st.success(f"✅ Se actualizaron {num} productos."); st.rerun()

    elif menu == "👥 Clientes" and user['rol'] == 'admin':
        st.title("👥 Gestión de Clientes")
        with st.expander("➕ Registrar Nuevo Cliente"):
            with st.form("reg"):
                nu = st.text_input("Usuario (Email)"); np = st.text_input("Clave")
                nn = st.text_input("Nombre"); nt = st.text_input("Teléfono"); nd = st.text_area("Dirección")
                if st.form_submit_button("Guardar"):
                    get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (nu, np, nn, 'cliente', nd, nt))
                    get_connection().commit(); st.success("Cliente creado")
        
        clis = pd.read_sql("SELECT * FROM usuarios WHERE rol='cliente'", get_connection())
        st.dataframe(clis, use_container_width=True)

    elif menu == "📊 Pedidos":
        st.title("📊 Historial de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{user['id']}'"
        peds = pd.read_sql(query, get_connection())
        st.dataframe(peds, use_container_width=True)