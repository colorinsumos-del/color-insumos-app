import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import time
import re
import pdfplumber
from datetime import datetime

# --- CONFIGURACIÓN ---
DB_NAME = "color_insumos_v27.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- ESTILOS VISUALES MEJORADOS ---
st.markdown("""
    <style>
    .product-card {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 15px;
        border: 1px solid #e1e4e8;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        margin-bottom: 20px;
    }
    .product-img {
        width: 100%;
        height: 140px;
        object-fit: contain;
        margin-bottom: 10px;
    }
    .price-tag {
        color: #1a73e8;
        font-size: 22px;
        font-weight: bold;
        margin: 5px 0;
    }
    .product-name {
        font-weight: 600;
        font-size: 14px;
        height: 45px;
        overflow: hidden;
        color: #333;
    }
    </style>
    """, unsafe_allow_html=True)

# --- MOTOR DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_bcv REAL, categoria TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito 
                 (username TEXT, sku TEXT, nombre TEXT, precio REAL, cantidad INTEGER, PRIMARY KEY(username, sku))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL)''')
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin', 'admin'))
    conn.commit()

# --- EXTRACCIÓN DE PDF (ENFOCADA EN PRECIO BCV) ---
def procesar_pdf(file):
    conn = get_connection()
    count = 0
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            
            # Buscar columna BCV
            col_bcv = -1
            header = [str(c).upper() if c else "" for c in table[0]]
            for i, cell in enumerate(header):
                if "BCV" in cell: col_bcv = i

            for row in table[1:]:
                if not row or len(row) < 2: continue
                sku = str(row[0]).strip()
                if not sku or sku.upper() in ["SKU", "CODIGO"]: continue
                
                desc = str(row[1]).strip()
                
                # Limpiar el monto de la columna BCV
                val_raw = str(row[col_bcv]) if col_bcv != -1 else "0"
                monto = re.sub(r'[^\d,.]', '', val_raw).replace(',', '.')
                try:
                    precio = float(monto)
                except:
                    precio = 0.0

                conn.execute("""INSERT INTO productos (sku, descripcion, precio_bcv, categoria) 
                             VALUES (?, ?, ?, 'General')
                             ON CONFLICT(sku) DO UPDATE SET 
                             descripcion=excluded.descripcion, precio_bcv=excluded.precio_bcv""",
                             (sku, desc, precio))
                count += 1
    conn.commit()
    return count

# --- APLICACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔑 Sistema Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth, st.session_state.user = True, {"id": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
else:
    user = st.session_state.user
    menu = st.sidebar.radio("Menú", ["🛒 Tienda", "🧾 Carrito", "👥 Clientes", "📦 Pedidos", "📁 Cargar PDF"])

    if menu == "🛒 Tienda":
        st.title("🛍️ Catálogo ($ BCV)")
        prods = pd.read_sql("SELECT * FROM productos", get_connection())
        
        if prods.empty:
            st.warning("No hay productos cargados.")
        else:
            cols = st.columns(4)
            for idx, row in prods.iterrows():
                with cols[idx % 4]:
                    # Lógica de imagen: busca archivo local con nombre del SKU (ej: 101.jpg)
                    img_file = f"{row['sku']}.jpg"
                    img_path = os.path.join(IMG_DIR, img_file)
                    img_display = img_path if os.path.exists(img_path) else "https://via.placeholder.com/150?text=Insumo"

                    st.markdown(f"""
                    <div class="product-card">
                        <img src="{img_display}" class="product-img">
                        <div class="product-name">{row['descripcion']}</div>
                        <div class="price-tag">$ {row['precio_bcv']:.2f}</div>
                        <div style="font-size:11px; color:gray;">REF: {row['sku']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button("Añadir 🛒", key=f"add_{row['sku']}", use_container_width=True):
                        conn = get_connection()
                        conn.execute("INSERT OR REPLACE INTO carrito VALUES (?,?,?,?,?)",
                                    (user['id'], row['sku'], row['descripcion'], row['precio_bcv'], 1))
                        conn.commit()
                        st.toast(f"Añadido: {row['sku']}")

    elif menu == "🧾 Carrito":
        st.title("🧾 Tu Pedido")
        items = pd.read_sql("SELECT * FROM carrito WHERE username=?", get_connection(), params=(user['id'],))
        if items.empty:
            st.info("Carrito vacío.")
        else:
            total = 0
            for _, item in items.iterrows():
                sub = item['precio'] * item['cantidad']
                total += sub
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{item['nombre']}**")
                nueva_q = c2.number_input("Cant", 1, 100, item['cantidad'], key=f"q_{item['sku']}")
                if nueva_q != item['cantidad']:
                    get_connection().execute("UPDATE carrito SET cantidad=? WHERE username=? AND sku=?", (nueva_q, user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
                if c3.button("🗑️", key=f"del_{item['sku']}"):
                    get_connection().execute("DELETE FROM carrito WHERE username=? AND sku=?", (user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
            
            st.divider()
            st.write(f"### TOTAL PEDIDO: $ {total:.2f}")
            if st.button("Finalizar Compra", type="primary"):
                st.success("Pedido procesado exitosamente.")

    elif menu == "📁 Cargar PDF" and user['rol'] == 'admin':
        st.title("📁 Cargar Inventario")
        f = st.file_uploader("Sube el PDF", type="pdf")
        if f and st.button("Procesar"):
            res = procesar_pdf(f)
            st.success(f"Se cargaron {res} productos.")
            st.rerun()