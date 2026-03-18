import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import time
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURACIÓN ---
# Nueva versión para asegurar una estructura limpia
DB_NAME = "color_excel_v11.db"

st.set_page_config(page_title="Color Insumos - Excel Edition", layout="wide")

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

# --- INICIALIZACIÓN ---
def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- NUEVA FUNCIÓN: PROCESAR EXCEL ---
def procesar_excel_dual(file):
    try:
        # Leemos el excel
        df_excel = pd.read_excel(file)
        
        # Normalizamos nombres de columnas para que no importe si están en mayúsculas o minúsculas
        df_excel.columns = [str(c).strip().upper() for c in df_excel.columns]
        
        # Mapeo inteligente de columnas
        col_sku = next((c for c in df_excel.columns if "SKU" in c or "CODIGO" in c), None)
        col_desc = next((c for c in df_excel.columns if "DESC" in c or "PRODUCTO" in c), None)
        col_divisa = next((c for c in df_excel.columns if "DIVISA" in c or "USD" in c or "$" in c), None)
        col_bcv = next((c for c in df_excel.columns if "BCV" in c), None)

        if not col_sku or not col_desc:
            return "Error: No se encontraron columnas SKU o Descripción."

        conn = get_connection()
        productos_actualizados = 0

        for _, row in df_excel.iterrows():
            sku = str(row[col_sku]).strip()
            if pd.isna(sku) or sku == "" or sku.upper() == "NAN": continue
            
            desc = str(row[col_desc]) if pd.notna(row[col_desc]) else ""
            p_div = float(row[col_divisa]) if col_divisa and pd.notna(row[col_divisa]) else 0.0
            p_bcv = float(row[col_bcv]) if col_bcv and pd.notna(row[col_bcv]) else 0.0

            conn.execute("""
                INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                VALUES (?, ?, ?, ?, 'General')
                ON CONFLICT(sku) DO UPDATE SET 
                    descripcion=excluded.descripcion,
                    precio_divisa=excluded.precio_divisa,
                    precio_bcv=excluded.precio_bcv
            """, (sku, desc, p_div, p_bcv))
            productos_actualizados += 1
            
        conn.commit()
        st.cache_data.clear()
        return productos_actualizados
    except Exception as e:
        return f"Error crítico: {str(e)}"

# --- INTERFAZ ---
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
else:
    user = st.session_state.user_data
    menu = st.sidebar.radio("Menú", ["🛒 Tienda", "👥 Clientes", "📊 Pedidos", "📁 Cargar Excel"])

    if menu == "📁 Cargar Excel":
        st.title("📁 Actualización vía Excel")
        st.info("Sube un archivo .xlsx o .xls. Asegúrate de que las columnas tengan títulos como: SKU, DESCRIPCION, DIVISA, BCV.")
        archivo = st.file_uploader("Subir Excel", type=["xlsx", "xls"])
        
        if archivo and st.button("🚀 Cargar Datos"):
            resultado = procesar_excel_dual(archivo)
            if isinstance(resultado, int):
                st.success(f"✅ Se han procesado {resultado} productos correctamente.")
                time.sleep(1)
                st.rerun()
            else:
                st.error(resultado)

    elif menu == "🛒 Tienda":
        st.title("🛒 Catálogo Actualizado")
        df = obtener_catalogo_cache()
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("El catálogo está vacío. Por favor carga un Excel.")

    # ... (Resto de funciones de clientes y pedidos se mantienen igual)