import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import json
import shutil
from datetime import datetime

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    # Tabla de Productos
    conn.execute('CREATE TABLE IF NOT EXISTS productos (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)')
    # Tabla de Usuarios (Añadimos columna ROL)
    conn.execute('CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)')
    # Tabla de Pedidos
    conn.execute('CREATE TABLE IF NOT EXISTS pedidos (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)')
    
    # CREAR USUARIO MAESTRO POR DEFECTO SI NO EXISTE
    cursor = conn.execute("SELECT * FROM usuarios WHERE username='colorinsumos@gmail.com'")
    if not cursor.fetchone():
        conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", 
                     ('colorinsumos@gmail.com', '20880157', 'Administrador Maestro', 'admin'))
    conn.commit()
    conn.close()

# --- LOGICA DE SESIÓN ---
if 'auth' not in st.session_state: st.session_state.auth = False
if 'user_data' not in st.session_state: st.session_state.user_data = None
if 'carrito' not in st.session_state: st.session_state.carrito = {}

init_db()

# --- FUNCIONES DE APOYO ---
def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA"]): return "✂️ OFICINA / ESCOLAR"
    return "📦 VARIOS"

def procesar_pdf(pdf_file):
    with open("temp.pdf", "wb") as f: f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)
    with pdfplumber.open("temp.pdf") as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.find_tables()
            if not tables: continue
            imgs_pag = [{'bbox': img['bbox'], 'xref': x[0]} for img, x in zip(doc[i].get_image_info(), doc[i].get_images(full=True))]
            for row in tables[0].rows:
                try:
                    sku = page.within_bbox(row.cells[0]).extract_text().strip().split('\n')[0]
                    if "REFERENCIA" in sku or not sku: continue
                    desc = page.within_bbox(row.cells[2]).extract_text().replace('\n', ' ').strip()
                    precio = float(page.within_bbox(row.cells[3]).extract_text().replace(',', '.').strip())
                    y_mid = (row.bbox[1] + row.bbox[3]) / 2
                    f_path = ""
                    for img in imgs_pag:
                        if img['bbox'][1] <= y_mid <= img['bbox'][3]:
                            pix = fitz.Pixmap(doc, img['xref'])
                            if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                            f_path = os.path.join(IMG_DIR, f"{sku}.png"); pix.save(f_path); break
                    productos.append({"sku": sku, "descripcion": desc, "precio": precio, "categoria": obtener_categoria(sku, desc), "foto_path": f_path})
                except: continue
    df = pd.DataFrame(productos)
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM productos"); df.to_sql('productos', conn, if_exists='append', index=False); conn.close()

# --- PANTALLA DE LOGIN (Si no está autenticado) ---
if not st.session_state.auth:
    st.title("🚀 Sistema Color Insumos")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🔐 Iniciar Sesión")
        u = st.text_input("Correo / Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.button("Entrar"):
            conn = sqlite3.connect(DB_NAME)
            res = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
            conn.close()
            if res:
                st.session_state.auth = True
                st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
                st.rerun()
            else: st.error("Usuario o clave incorrecta")
    with col2:
        st.info("Bienvenido al sistema de pedidos mayoristas. Inicie sesión para ver precios y existencias.")

else:
    # --- INTERFAZ SEGÚN ROL ---
    user = st.session_state.user_data
    
    with st.sidebar:
        st.write(f"👤 **{user['nombre']}** ({user['rol'].upper()})")
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False; st.rerun()
        st.divider()
        
        if user['rol'] == 'admin':
            menu = st.radio("Panel Maestro:", ["🛒 Ver Catálogo", "📁 Cargar PDF", "👥 Gestión de Clientes", "📊 Pedidos Recibidos"])
        else:
            menu = st.radio("Menú Cliente:", ["🛒 Comprar", "📜 Mis Pedidos"])

    # --- LÓGICA DE CADA SECCIÓN ---
    
    # 1. CARGAR PDF (Solo Admin)
    if menu == "📁 Cargar PDF":
        st.header("Actualización Masiva de Catálogo")
        archivo = st.file_uploader("Subir PDF", type="pdf")
        if archivo and st.button("🚀 Procesar e Instalar Catálogo"):
            with st.spinner("Extrayendo productos e imágenes..."):
                procesar_pdf(archivo)
                st.success("Catálogo instalado correctamente.")

    # 2. GESTIÓN DE CLIENTES (Solo Admin)
    elif menu == "👥 Gestión de Clientes":
        st.header("Registrar Nuevo Cliente")
        with st.form("registro_cliente"):
            c_user = st.text_input("Email/Usuario del Cliente")
            c_pass = st.text_input("Clave Provisoria")
            c_nom = st.text_input("Nombre de la Empresa / Cliente")
            if st.form_submit_button("Crear Cuenta Cliente"):
                try:
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (c_user, c_pass, c_nom, 'cliente'))
                    conn.commit(); conn.close()
                    st.success(f"Cliente {c_nom} creado con éxito.")
                except: st.error("El usuario ya existe.")

    # 3. VER CATÁLOGO (Admin y Cliente)
    elif menu in ["🛒 Ver Catálogo", "🛒 Comprar"]:
        st.header("Catálogo de Productos")
        busqueda = st.text_input("🔍 Buscar por Nombre o SKU...")
        
        conn = sqlite3.connect(DB_NAME)
        df_cat = pd.read_sql("SELECT * FROM productos", conn)
        conn.close()

        if df_cat.empty:
            st.warning("No hay productos cargados.")
        else:
            # Filtrado
            if busqueda:
                df_ver = df_cat[(df_cat['descripcion'].str.contains(busqueda, case=False)) | (df_cat['sku'].str.contains(busqueda, case=False))]
            else: df_ver = df_cat
            
            # Mostrar por Categorías
            for cat in sorted(df_ver['categoria'].unique()):
                st.subheader(cat)
                items = df_ver[df_ver['categoria'] == cat]
                cols = st.columns(4)
                for idx, row in items.reset_index().iterrows():
                    with cols[idx % 4]:
                        with st.container(border=True):
                            if row['foto_path'] and os.path.exists(row['foto_path']): st.image(row['foto_path'], width=140)
                            st.markdown(f"**{row['sku']}**")
                            st.caption(row['descripcion'])
                            st.write(f"💰 ${row['precio']:.2f}")
                            if user['rol'] == 'cliente':
                                cant = st.number_input("Cant.", min_value=0, key=f"q_{row['sku']}")
                                if cant > 0: st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}

        # Botón para confirmar pedido (Solo Clientes)
        if user['rol'] == 'cliente' and st.session_state.carrito:
            if st.sidebar.button("🛒 Confirmar Pedido"):
                st.sidebar.success("Pedido enviado al administrador.")

    # 4. PEDIDOS RECIBIDOS (Solo Admin)
    elif menu == "📊 Pedidos Recibidos":
        st.header("Bandeja de Entrada de Pedidos")
        st.info("Aquí verás los pedidos que tus clientes confirmen.")