import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import shutil
import pdfplumber
import fitz  # PyMuPDF
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Sistema Color Insumos", layout="wide", initial_sidebar_state="expanded")

# --- RUTAS Y BASE DE DATOS ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    # Tabla de productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de ventas local
    conn.execute('''CREATE TABLE IF NOT EXISTS ventas 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                  cliente TEXT, total REAL)''')
    conn.close()

# --- FUNCIONES DE SOPORTE ---
def cargar_datos_locales():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM productos", conn)
    conn.close()
    return df

def procesar_excel(file):
    df = pd.read_excel(file)
    # Aquí puedes seleccionar columnas específicas si el Excel varía
    return df

# --- INTERFAZ DE NAVEGACIÓN (EL MENÚ QUE BUSCAS) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3081/3081840.png", width=120)
    st.title("Color Insumos")
    
    # Navegación principal
    menu_principal = st.radio("MENÚ PRINCIPAL", [
        "🛒 Catálogo / Ventas",
        "📂 Gestión de Pedidos",
        "⚙️ Configuración Admin"
    ])
    
    st.divider()
    
    # Estado del carrito
    if 'carrito' not in st.session_state: st.session_state.carrito = {}
    if st.session_state.carrito:
        st.subheader("🛒 Carrito Actual")
        for k, v in st.session_state.carrito.items():
            st.caption(f"{v['cant']}x {k}")

# --- LÓGICA DE PÁGINAS ---

# 1. MÓDULO DE CATÁLOGO Y VENTAS
if menu_principal == "🛒 Catálogo / Ventas":
    st.title("🛍️ Punto de Venta / Catálogo")
    df_prods = cargar_datos_locales()
    
    if df_prods.empty:
        st.warning("No hay productos. Ve a Configuración para cargar datos.")
    else:
        busqueda = st.text_input("Buscar producto (Nombre o SKU)")
        df_f = df_prods[df_prods['descripcion'].str.contains(busqueda, case=False) | df_prods['sku'].str.contains(busqueda, case=False)]
        
        cols = st.columns(4)
        for idx, row in df_f.reset_index().iterrows():
            with cols[idx % 4]:
                with st.container(border=True):
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], use_column_width=True)
                    st.write(f"**{row['sku']}**")
                    st.caption(row['descripcion'])
                    st.info(f"${row['precio']:.2f}")
                    cant = st.number_input("Cantidad", min_value=0, key=f"v_{row['sku']}", step=1)
                    if cant > 0:
                        st.session_state.carrito[row['sku']] = {"precio": row['precio'], "cant": cant}
                    elif row['sku'] in st.session_state.carrito:
                        del st.session_state.carrito[row['sku']]

# 2. MÓDULO DE PEDIDOS (CONEXIÓN GOOGLE SHEETS)
elif menu_principal == "📂 Gestión de Pedidos":
    st.title("☁️ Pedidos en la Nube")
    try:
        conn_gs = st.connection("gsheets", type=GSheetsConnection)
        df_pedidos = conn_gs.read(worksheet="Pedidos")
        st.subheader("Historial de Clientes")
        st.dataframe(df_pedidos, use_container_width=True)
        
        if st.button("🔄 Refrescar Nube"):
            st.rerun()
    except:
        st.error("Error de conexión a Google Sheets. Verifica tus Secrets.")

# 3. MÓDULO DE CONFIGURACIÓN / ADMIN (TU MENÚ COMPLETO)
elif menu_principal == "⚙️ Configuración Admin":
    st.title("⚙️ Panel de Control Administrativo")
    
    user_log = st.text_input("Usuario / Correo")
    pass_log = st.text_input("Contraseña", type="password")
    
    if user_log and pass_log == "20880157":
        st.success(f"Bienvenido Administrador: {user_log}")
        
        # Pestañas para organizar los módulos
        tab_carga, tab_usuarios, tab_respaldo = st.tabs([
            "📤 Carga de Artículos (Excel/PDF)", 
            "👥 Usuarios y Ventas", 
            "💾 Respaldos"
        ])
        
        with tab_carga:
            st.subheader("Importar Inventario")
            metodo = st.radio("Método de carga:", ["Excel (Masivo)", "PDF (Con Fotos)"])
            
            if metodo == "Excel (Masivo)":
                archivo_ex = st.file_uploader("Subir Archivo Excel (.xlsx)", type="xlsx")
                if archivo_ex:
                    df_ex = pd.read_excel(archivo_ex)
                    st.write("Vista previa de los datos:")
                    st.dataframe(df_ex.head())
                    if st.button("💾 Guardar en Base de Datos"):
                        conn = sqlite3.connect(DB_NAME)
                        df_ex.to_sql('productos', conn, if_exists='replace', index=False)
                        conn.close()
                        st.success("¡Base de datos actualizada desde Excel!")
            
            else:
                archivo_pdf = st.file_uploader("Subir Catálogo PDF", type="pdf")
                st.info("El sistema extraerá descripciones y fotos automáticamente.")
                # (Aquí iría tu función de procesamiento de PDF que ya tenemos)

        with tab_usuarios:
            st.subheader("Gestión de Usuarios y Ventas Local")
            st.info("Módulo para administrar personal de Color Insumos y ver cierres de caja.")
            # Mostrar tabla de ventas local
            conn = sqlite3.connect(DB_NAME)
            ventas_df = pd.read_sql("SELECT * FROM ventas", conn)
            st.dataframe(ventas_df)
            conn.close()

        with tab_respaldo:
            st.subheader("Módulo de Respaldo")
            if st.button("📦 Generar Backup de la Base de Datos"):
                with open(DB_NAME, "rb") as f:
                    st.download_button("Descargar Archivo .DB", f, file_name="backup_color_insumos.db")
    else:
        st.warning("Por favor, identifícate para acceder a los módulos de administración.")

init_db()