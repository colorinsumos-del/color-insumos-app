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

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Pedidos", layout="wide")

# --- FUNCIONES DE BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute('CREATE TABLE IF NOT EXISTS productos (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rif TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS pedidos (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL)')
    conn.close()

def cargar_catalogo():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM productos", conn)
    conn.close()
    return df

def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA"]): return "✂️ OFICINA / ESCOLAR"
    return "📦 VARIOS"

# --- LÓGICA DE EXTRACCIÓN (ADMIN) ---
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
                    if "REFERENCIA" in sku: continue
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
    return df

# --- INTERFAZ PRINCIPAL ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'carrito' not in st.session_state: st.session_state.carrito = {}

# 1. BUSCADOR Y MODO ADMIN
st.title("🛒 Catálogo Color Insumos")
busqueda = st.text_input("🔍 Buscar por Producto o SKU...", placeholder="Ej: Bolígrafo, Papel, A-105...")

if busqueda == "ADMIN_COLOR":
    u_admin = st.text_input("Usuario Admin")
    p_admin = st.text_input("Clave Admin", type="password")
    if u_admin == "colorinsumos@gmail.com" and p_admin == "20880157":
        archivo = st.file_uploader("Subir Catálogo PDF", type="pdf")
        if archivo and st.button("🚀 Sincronizar"):
            procesar_pdf(archivo); st.success("¡Catálogo actualizado!"); st.rerun()
    st.stop()

# 2. CARGAR DATOS
df_cat = cargar_catalogo()

if df_cat.empty:
    st.info("Catálogo vacío. El admin debe cargar el PDF usando la palabra secreta.")
else:
    # Filtro de búsqueda
    df_ver = df_cat[(df_cat['descripcion'].str.contains(busqueda, case=False)) | (df_cat['sku'].str.contains(busqueda, case=False))] if busqueda else df_cat
    
    # Mostrar por Categorías
    for cat in sorted(df_ver['categoria'].unique()):
        st.header(cat)
        items = df_ver[df_ver['categoria'] == cat]
        cols = st.columns(4)
        for idx, row in items.reset_index().iterrows():
            with cols[idx % 4]:
                with st.container(border=True):
                    if row['foto_path'] and os.path.exists(row['foto_path']): st.image(row['foto_path'], width=130)
                    st.markdown(f"**{row['sku']}**")
                    st.caption(row['descripcion'])
                    st.write(f"💰 ${row['precio']:.2f}")
                    cant = st.number_input("Cant.", min_value=0, key=f"q_{row['sku']}_{idx}", step=1)
                    if cant > 0:
                        st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "precio": row['precio'], "cant": cant}
                    elif row['sku'] in st.session_state.carrito:
                        del st.session_state.carrito[row['sku']]

# 3. BARRA LATERAL (LOGIN Y CARRITO)
with st.sidebar:
    if not st.session_state.auth:
        st.subheader("🔐 Acceso Clientes")
        user_log = st.text_input("Usuario")
        pass_log = st.text_input("Clave", type="password")
        if st.button("Iniciar Sesión"):
            # Aquí puedes validar contra la DB de usuarios. Por ahora acceso directo:
            st.session_state.auth = True
            st.session_state.user = user_log
            st.rerun()
        st.caption("¿No tienes cuenta? Contacta al administrador.")
    else:
        st.write(f"👤 **{st.session_state.user}**")
        menu = st.radio("Menú:", ["🛒 Carrito Actual", "📜 Historial de Pedidos", "🚪 Salir"])
        
        if menu == "🚪 Salir":
            st.session_state.auth = False; st.rerun()
            
        if menu == "📜 Historial de Pedidos":
            st.subheader("Mis compras")
            # Aquí llamarías a obtener_historial()
            st.write("Próximamente...")

        if menu == "🛒 Carrito Actual":
            st.subheader("Tu Pedido")
            if not st.session_state.carrito:
                st.write("Vacío")
            else:
                total_p = 0
                for s, v in st.session_state.carrito.items():
                    sub = v['precio'] * v['cant']
                    total_p += sub
                    st.write(f"{v['cant']}x {s} (${sub:.2f})")
                st.write(f"### TOTAL: ${total_p:.2f}")
                if st.button("✅ Confirmar Pedido"):
                    st.success("¡Pedido enviado!")