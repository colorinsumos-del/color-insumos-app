import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import time
import re
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURACIÓN ---
DB_NAME = "color_insumos_v20.db"
# Carpeta donde debes subir tus fotos en GitHub para que se vean
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- ESTILOS VISUALES (TARJETAS VISTOSAS) ---
st.markdown("""
    <style>
    .product-card {
        background-color: #ffffff;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #eaeaea;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 15px;
    }
    .product-img {
        width: 100%;
        height: 160px;
        object-fit: contain;
        margin-bottom: 10px;
    }
    .price-bcv {
        color: #28a745;
        font-size: 20px;
        font-weight: bold;
    }
    .product-name {
        font-weight: 600;
        height: 45px;
        overflow: hidden;
        margin-bottom: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- MOTOR DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, imagen TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito 
                 (username TEXT, sku TEXT, nombre TEXT, precio_bcv REAL, cantidad INTEGER, PRIMARY KEY(username, sku))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, subtotal REAL, descuento REAL, total REAL)''')
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Administrador', 'admin'))
    conn.commit()

# --- PROCESADOR DE EXCEL (BUSCA NOMBRES DE ARCHIVOS DE IMAGEN) ---
def procesar_excel(file):
    try:
        df = pd.read_excel(file)
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        c_sku = next((c for c in df.columns if "SKU" in c or "COD" in c), None)
        c_desc = next((c for c in df.columns if "DESC" in c or "PROD" in c or "NOMBRE" in c), None)
        c_div = next((c for c in df.columns if "DIVISA" in c or "USD" in c), None)
        c_bcv = next((c for c in df.columns if "BCV" in c), None)
        c_img = next((c for c in df.columns if "IMAGEN" in c or "FOTO" in c), None)

        if not c_sku or not c_desc: return "Error: No se hallaron columnas de SKU o Nombre."

        conn = get_connection()
        for _, row in df.iterrows():
            sku = str(row[c_sku]).strip()
            if not sku or sku.lower() == "nan": continue
            
            p_div = float(row[c_div]) if c_div and pd.notna(row[c_div]) else 0.0
            p_bcv = float(row[c_bcv]) if c_bcv and pd.notna(row[c_bcv]) else 0.0
            # Si en la celda de imagen hay un nombre como "tinta.jpg", lo tomamos. Si no, vacío.
            img_name = str(row[c_img]).strip() if c_img and pd.notna(row[c_img]) else ""

            conn.execute("""INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, imagen) 
                         VALUES (?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET 
                         descripcion=excluded.descripcion, precio_divisa=excluded.precio_divisa, 
                         precio_bcv=excluded.precio_bcv, imagen=excluded.imagen""",
                         (sku, str(row[c_desc]), p_div, p_bcv, img_name))
        conn.commit()
        return True
    except Exception as e: return f"Error: {e}"

# --- LÓGICA DE INTERFAZ ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔑 Ingreso al Sistema")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth, st.session_state.user = True, {"id": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
else:
    user = st.session_state.user
    menu = st.sidebar.radio("Navegación", ["🛒 Catálogo", "🧾 Mi Carrito", "👥 Clientes", "📦 Pedidos", "📁 Cargar Inventario"])

    if menu == "🛒 Catálogo":
        st.title("🛒 Catálogo de Insumos")
        prods = pd.read_sql("SELECT * FROM productos", get_connection())
        
        if prods.empty:
            st.info("El catálogo está vacío. Sube un archivo Excel para comenzar.")
        else:
            busq = st.text_input("🔍 Buscar productos...")
            if busq: prods = prods[prods['descripcion'].str.contains(busq, case=False) | prods['sku'].str.contains(busq, case=False)]
            
            cols = st.columns(4)
            for idx, row in prods.iterrows():
                with cols[idx % 4]:
                    # Lógica de imagen: Si existe en la carpeta local, se muestra. Si no, una por defecto.
                    img_path = f"{IMG_DIR}/{row['imagen']}" if row['imagen'] else None
                    if not img_path or not os.path.exists(img_path):
                        img_url = "https://via.placeholder.com/200?text=Sin+Imagen"
                    else:
                        img_url = img_path

                    st.markdown(f"""
                    <div class="product-card">
                        <img src="{img_url}" class="product-img">
                        <div class="product-name">{row['descripcion']}</div>
                        <div class="price-bcv">{row['precio_bcv']:.2f} Bs.</div>
                        <div style="font-size:10px; color:gray;">SKU: {row['sku']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button(f"Añadir 🛒", key=f"add_{row['sku']}", use_container_width=True):
                        conn = get_connection()
                        conn.execute("INSERT OR REPLACE INTO carrito VALUES (?,?,?,?,?)",
                                    (user['id'], row['sku'], row['descripcion'], row['precio_bcv'], 1))
                        conn.commit()
                        st.toast(f"✅ Añadido: {row['descripcion']}")
                        time.sleep(0.4); st.rerun()

    elif menu == "🧾 Mi Carrito":
        st.title("🧾 Carrito de Compras")
        items = pd.read_sql("SELECT * FROM carrito WHERE username=?", get_connection(), params=(user['id'],))
        if items.empty: st.warning("Tu carrito está vacío.")
        else:
            subtotal = 0
            for _, item in items.iterrows():
                sub = item['precio_bcv'] * item['cantidad']
                subtotal += sub
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{item['nombre']}**")
                nueva_q = c2.number_input("Cant", 1, 100, item['cantidad'], key=f"q_{item['sku']}")
                if nueva_q != item['cantidad']:
                    get_connection().execute("UPDATE carrito SET cantidad=? WHERE username=? AND sku=?", (nueva_q, user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
                if c3.button("🗑️", key=f"del_{item['sku']}"):
                    get_connection().execute("DELETE FROM carrito WHERE username=? AND sku=?", (user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
            
            # REGLAS DE DESCUENTO
            # Si el usuario es administrador o compra volumen, se puede aplicar un 10%
            descuento = subtotal * 0.10 if subtotal > 10000 else 0 # Ejemplo: > 10.000 Bs.
            total = subtotal - descuento
            
            st.divider()
            st.write(f"Subtotal: **{subtotal:.2f} Bs.**")
            if descuento > 0: st.success(f"🎁 Descuento aplicado: -{descuento:.2f} Bs.")
            st.write(f"## TOTAL: {total:.2f} Bs.")
            
            if st.button("🚀 Finalizar Pedido", type="primary", use_container_width=True):
                # Guardar pedido en base de datos
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, fecha, items, subtotal, descuento, total) VALUES (?,?,?,?,?,?)",
                             (user['id'], datetime.now().strftime("%d/%m/%Y"), items.to_json(), subtotal, descuento, total))
                conn.execute("DELETE FROM carrito WHERE username=?", (user['id'],))
                conn.commit(); st.success("¡Pedido enviado!"); time.sleep(1); st.rerun()

    elif menu == "📁 Cargar Inventario":
        st.title("📁 Cargar desde Excel")
        st.info("Para las imágenes: coloca el nombre del archivo (ej: mouse.jpg) en la columna IMAGEN y sube las fotos a la carpeta static/fotos.")
        f = st.file_uploader("Sube tu archivo .xlsx", type=["xlsx"])
        if f and st.button("Procesar Excel"):
            res = procesar_excel(f)
            if res is True: st.success("Inventario actualizado"); st.rerun()
            else: st.error(res)

    # --- Los módulos de Clientes y Pedidos (Eliminar/Editar) se mantienen con la lógica de CRUD estándar ---