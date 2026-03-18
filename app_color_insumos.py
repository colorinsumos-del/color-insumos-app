import streamlit as st
import pandas as pd
import sqlite3
import os
import time
import re

# --- CONFIGURACIÓN ---
DB_NAME = "color_excel_v12.db"

st.set_page_config(page_title="Color Insumos - Excel Master", layout="wide")

# --- MOTOR DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

# --- PROCESADOR DE EXCEL ULTRA-FLEXIBLE ---
def procesar_excel_dual(file):
    try:
        # Cargamos el excel
        df = pd.read_excel(file)
        
        # Limpiamos los nombres de las columnas: quitar espacios y poner en mayúsculas
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # --- BUSCADOR FLEXIBLE DE COLUMNAS ---
        # Busca SKU o algo que se le parezca
        col_sku = next((c for c in df.columns if any(x in c for x in ["SKU", "COD", "REF", "ARTICULO"])), None)
        # Busca Descripción
        col_desc = next((c for c in df.columns if any(x in c for x in ["DESC", "PROD", "NOMBRE", "DETALLE"])), None)
        # Busca Precio Divisa
        col_divisa = next((c for c in df.columns if any(x in c for x in ["DIVISA", "USD", "$", "DOLAR", "DOLARES"])), None)
        # Busca Precio BCV
        col_bcv = next((c for c in df.columns if "BCV" in c), None)

        # Validación crítica
        if not col_sku or not col_desc:
            return f"❌ Error: No encontré las columnas. Tu Excel tiene: {', '.join(df.columns)}"

        conn = get_connection()
        count = 0

        for _, row in df.iterrows():
            sku = str(row[col_sku]).strip()
            # Ignorar filas vacías
            if not sku or sku.lower() in ["nan", "none", ""]: continue
            
            descripcion = str(row[col_desc]).strip() if pd.notna(row[col_desc]) else ""
            
            # Limpieza de precios (por si vienen como texto con $)
            def forzar_float(val):
                if pd.isna(val): return 0.0
                if isinstance(val, (int, float)): return float(val)
                res = re.sub(r'[^\d,.]', '', str(val)).replace(',', '.')
                try: return float(res)
                except: return 0.0

            p_div = forzar_float(row[col_divisa]) if col_divisa else 0.0
            p_bcv = forzar_float(row[col_bcv]) if col_bcv else 0.0

            conn.execute("""
                INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                VALUES (?, ?, ?, ?, 'General')
                ON CONFLICT(sku) DO UPDATE SET 
                    descripcion=excluded.descripcion,
                    precio_divisa=excluded.precio_divisa,
                    precio_bcv=excluded.precio_bcv
            """, (sku, descripcion, p_div, p_bcv))
            count += 1
            
        conn.commit()
        st.cache_data.clear()
        return count

    except Exception as e:
        return f"❌ Error al leer el archivo: {str(e)}"

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
    st.sidebar.title(f"Bienvenido")
    menu = st.sidebar.radio("Navegación", ["🛒 Tienda", "📁 Cargar Excel", "👥 Clientes"])

    if menu == "📁 Cargar Excel":
        st.title("📁 Importar Inventario desde Excel")
        st.write("El sistema reconocerá automáticamente columnas como: **SKU, Descripción, USD y BCV**.")
        
        file = st.file_uploader("Sube tu archivo .xlsx", type=["xlsx"])
        if file and st.button("🚀 Procesar Excel", type="primary"):
            resultado = procesar_excel_dual(file)
            if isinstance(resultado, int):
                st.success(f"✅ ¡Éxito! Se actualizaron {resultado} productos.")
                time.sleep(1)
                st.rerun()
            else:
                st.error(resultado)

    elif menu == "🛒 Tienda":
        st.title("🛍️ Catálogo Disponible")
        try:
            df_view = pd.read_sql("SELECT sku, descripcion, precio_divisa, precio_bcv FROM productos", get_connection())
            if not df_view.empty:
                st.dataframe(df_view, use_container_width=True)
            else:
                st.info("Catálogo vacío. Carga un Excel para ver productos.")
        except:
            st.error("Error al cargar la tabla. Intenta subir un Excel primero.")