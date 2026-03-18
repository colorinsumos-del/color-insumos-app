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
# Cambiamos el nombre a v10 para forzar una base de datos totalmente limpia y evitar errores de columnas
DB_NAME = "color_insumos_v10.db"

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    try:
        conn = get_connection()
        return pd.read_sql("SELECT * FROM productos", conn)
    except:
        return pd.DataFrame(columns=['sku', 'descripcion', 'precio_divisa', 'precio_bcv', 'categoria'])

# --- INICIALIZACIÓN ROBUSTA ---
def init_db():
    conn = get_connection()
    # Aseguramos que la tabla exista con todas las columnas desde el inicio
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, 
                  descripcion TEXT, 
                  precio_divisa REAL, 
                  precio_bcv REAL, 
                  categoria TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- NUEVA FUNCIÓN DE PROCESAMIENTO DE PDF (MÁS ROBUSTA) ---
def procesar_pdf_dual(file):
    conn = get_connection()
    # Intento de reparación de emergencia: Agregar columnas si no existen
    try:
        conn.execute("ALTER TABLE productos ADD COLUMN precio_divisa REAL")
        conn.execute("ALTER TABLE productos ADD COLUMN precio_bcv REAL")
    except:
        pass # Si ya existen, no hace nada
        
    productos_cargados = 0
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if not table: continue
            
            # Buscamos encabezados de columna
            header = [str(c).upper() if c else "" for c in table[0]]
            col_sku, col_desc, col_divisa, col_bcv = -1, -1, -1, -1
            
            for i, cell in enumerate(header):
                if any(x in cell for x in ["SKU", "CODIGO"]): col_sku = i
                if any(x in cell for x in ["DESC", "PRODUCTO"]): col_desc = i
                if any(x in cell for x in ["DIVISA", "USD", "$"]): col_divisa = i
                if "BCV" in cell: col_bcv = i
            
            # Si no detecta columnas por nombre, usamos posiciones fijas estándar
            if col_sku == -1: col_sku = 0
            if col_desc == -1: col_desc = 1
            
            for row in table[1:]: # Omitir encabezado
                if not row or len(row) < 2: continue
                
                sku = str(row[col_sku]).strip() if row[col_sku] else None
                if not sku or sku.upper() in ["SKU", "None"]: continue
                
                desc = str(row[col_desc]).strip() if row[col_desc] else ""
                
                def limpiar_precio(val):
                    if not val: return 0.0
                    res = re.sub(r'[^\d,.]', '', str(val))
                    try: return float(res.replace(',', '.'))
                    except: return 0.0

                p_div = limpiar_precio(row[col_divisa]) if col_divisa != -1 else 0.0
                p_bcv = limpiar_precio(row[col_bcv]) if col_bcv != -1 else 0.0

                try:
                    conn.execute("""
                        INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                        VALUES (?, ?, ?, ?, 'General')
                        ON CONFLICT(sku) DO UPDATE SET 
                            descripcion=excluded.descripcion,
                            precio_divisa=excluded.precio_divisa,
                            precio_bcv=excluded.precio_bcv
                    """, (sku, desc, p_div, p_bcv))
                    productos_cargados += 1
                except Exception as e:
                    st.error(f"Error en SKU {sku}: {e}")
                    
    conn.commit()
    st.cache_data.clear()
    return productos_cargados

# --- INTERFAZ SIMPLIFICADA ---
init_db()

if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    with st.form("login"):
        u = st.text_input("Usuario")
        p = st.text_input("Clave", type="password")
        if st.form_submit_button("Entrar"):
            res = get_connection().execute("SELECT username, password, nombre, rol FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
            if res and res[1] == p:
                st.session_state.auth = True
                st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
                st.rerun()
            else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    st.sidebar.title(f"Hola, {user['nombre']}")
    menu = st.sidebar.radio("Menú", ["🛒 Tienda", "👥 Clientes", "📊 Pedidos", "📁 Cargar PDF"])

    if menu == "📁 Cargar PDF":
        st.title("📁 Cargar Lista de Precios")
        st.write("Sube tu PDF para actualizar precios en Divisa y BCV simultáneamente.")
        archivo = st.file_uploader("Subir PDF", type="pdf")
        if archivo and st.button("🚀 Procesar Ahora", type="primary"):
            num = procesar_pdf_dual(archivo)
            st.success(f"Se actualizaron {num} productos correctamente.")
            time.sleep(1)
            st.rerun()
            
    elif menu == "🛒 Tienda":
        st.title("🛒 Catálogo de Productos")
        df = obtener_catalogo_cache()
        if not df.empty:
            st.dataframe(df[['sku', 'descripcion', 'precio_divisa', 'precio_bcv']], use_container_width=True)
        else:
            st.info("No hay productos. Carga un PDF para empezar.")

    # (Aquí irían los demás módulos de clientes y pedidos que ya tenías)