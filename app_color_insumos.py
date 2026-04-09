import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import io
import shutil
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema", layout="wide")

# --- CONEXIÓN A GOOGLE SHEETS ---
# Asegúrate de tener los "Secrets" configurados en Streamlit Cloud
conn_gs = st.connection("gsheets", type=GSheetsConnection)

# --- FUNCIONES DE BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.close()

def actualizar_base_datos(df):
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM productos")
    df.to_sql('productos', conn, if_exists='append', index=False)
    conn.commit()
    conn.close()

def cargar_catalogo():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM productos", conn)
    conn.close()
    return df

# --- PROCESAMIENTO DE PDF Y FOTOS ---
def procesar_pdf_completo(pdf_file):
    with open("temp.pdf", "wb") as f:
        f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)

    with pdfplumber.open("temp.pdf") as pdf:
        for i, page in enumerate(pdf.pages):
            page_fitz = doc[i]
            imgs_pag = [{'bbox': img['bbox'], 'xref': x[0]} for img, x in zip(page_fitz.get_image_info(), page_fitz.get_images(full=True))]
            tables = page.find_tables()
            if not tables: continue
            for row in tables[0].rows:
                try:
                    if not row.cells or len(row.cells) < 4 or row.cells[0] is None: continue
                    sku_raw = page.within_bbox(row.cells[0]).extract_text()
                    if not sku_raw or "REFERENCIA" in sku_raw: continue
                    sku = sku_raw.strip().split('\n')[0]
                    desc = page.within_bbox(row.cells[2]).extract_text().replace('\n', ' ').strip()
                    precio = float(page.within_bbox(row.cells[3]).extract_text().replace(',', '.').strip())
                    
                    # Extraer foto
                    y_mid = (row.bbox[1] + row.bbox[3]) / 2
                    foto_path = ""
                    for img_obj in imgs_pag:
                        if img_obj['bbox'][1] <= y_mid <= img_obj['bbox'][3]:
                            pix = fitz.Pixmap(doc, img_obj['xref'])
                            if pix.n - pix.alpha > 3: pix = fitz.Pixmap(fitz.csRGB, pix)
                            path = os.path.join(IMG_DIR, f"{sku}.png")
                            pix.save(path)
                            foto_path = path
                            break
                    
                    productos.append({"sku": sku, "descripcion": desc, "precio": precio, "categoria": "VARIOS", "foto_path": foto_path})
                except: continue
    doc.close()
    return pd.DataFrame(productos)

# --- INTERFAZ DE NAVEGACIÓN ---
init_db()
if 'carrito' not in st.session_state: st.session_state.carrito = {}

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3081/3081840.png", width=120)
    st.title("Color Insumos")
    menu = st.radio("Ir a:", ["🛍️ Ver Catálogo", "⚙️ Administración"])

# --- PÁGINA: ADMINISTRACIÓN ---
if menu == "⚙️ Administración":
    st.title("Panel de Administración")
    
    col_login, _ = st.columns([1, 2])
    with col_login:
        user = st.text_input("Usuario / Correo")
        clave = st.text_input("Contraseña", type="password")

    if user and clave == "20880157":
        st.success(f"Sesión activa: {user}")
        
        tab1, tab2 = st.tabs(["📤 Cargar Catálogo", "📊 Pedidos en la Nube"])
        
        with tab1:
            st.subheader("Sincronización de Archivos")
            file = st.file_uploader("Selecciona el PDF del Catálogo", type="pdf")
            if file and st.button("🚀 Iniciar Sincronización (Fotos + Precios)"):
                with st.spinner("Procesando catálogo..."):
                    df_nuevo = procesar_pdf_completo(file)
                    actualizar_base_datos(df_nuevo)
                    st.success(f"¡Hecho! Se cargaron {len(df_nuevo)} productos con sus fotos.")
        
        with tab2:
            st.subheader("Pedidos Recibidos de Clientes")
            if st.button("🔄 Refrescar Datos de Google Sheets"):
                try:
                    df_nube = conn_gs.read(worksheet="Pedidos")
                    st.table(df_nube)
                except:
                    st.error("No se pudo conectar a Google Sheets. Revisa tus Secrets.")
    else:
        st.info("Ingresa tus credenciales para ver las opciones de carga.")

# --- PÁGINA: CATÁLOGO ---
else:
    st.title("🏬 Catálogo Digital")
    df_cat = cargar_catalogo()

    if df_cat.empty:
        st.info("El catálogo está vacío. Ve a Administración para cargar el PDF.")
    else:
        # Buscador
        busqueda = st.text_input("🔍 ¿Qué buscas hoy? (Nombre o Código)")
        df_f = df_cat[df_cat['descripcion'].str.contains(busqueda, case=False) | df_cat['sku'].str.contains(busqueda, case=False)]
        
        # Grid de productos
        cols = st.columns(4)
        for idx, row in df_f.reset_index().iterrows():
            with cols[idx % 4]:
                with st.container(border=True):
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], use_column_width=True)
                    st.write(f"**{row['sku']}**")
                    st.caption(row['descripcion'])
                    st.write(f"**${row['precio']:.2f}**")
                    cant = st.number_input("Cant.", min_value=0, key=row['sku'], step=1)
                    
                    if cant > 0:
                        st.session_state.carrito[row['sku']] = {"p": row['precio'], "c": cant}
                    elif row['sku'] in st.session_state.carrito:
                        del st.session_state.carrito[row['sku']]

    # Carrito en el Sidebar solo si hay compras
    if st.session_state.carrito:
        with st.sidebar:
            st.divider()
            st.subheader("🛒 Tu Pedido")
            nombre_cli = st.text_input("Nombre de Cliente")
            total = 0
            datos_pedido = []
            for k, v in st.session_state.carrito.items():
                sub = v['p'] * v['c']
                total += sub
                st.write(f"{v['c']}x {k} - ${sub:.2f}")
                datos_pedido.append({"Cliente": nombre_cli, "SKU": k, "Cantidad": v['c'], "Subtotal": sub})
            
            st.write(f"**TOTAL: ${total:.2f}**")
            
            if st.button("☁️ Enviar a Color Insumos (Nube)"):
                if not nombre_cli: st.error("Escribe tu nombre")
                else:
                    try:
                        df_existente = conn_gs.read(worksheet="Pedidos")
                        df_final = pd.concat([df_existente, pd.DataFrame(datos_pedido)], ignore_index=True)
                        conn_gs.update(worksheet="Pedidos", data=df_final)
                        st.success("¡Pedido enviado!")
                    except: st.error("Error al conectar.")