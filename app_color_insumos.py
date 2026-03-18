import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import shutil

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Pedidos", layout="wide")

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT)''')
    conn.close()

def cargar_catalogo():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM productos", conn)
    conn.close()
    return df

# --- EXTRACCIÓN (Mantenemos tu lógica potente) ---
def procesar_pdf(pdf_file):
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
                    if not row.cells or len(row.cells) < 4: continue
                    sku = page.within_bbox(row.cells[0]).extract_text().strip().split('\n')[0]
                    if "REFERENCIA" in sku: continue
                    desc = page.within_bbox(row.cells[2]).extract_text().replace('\n', ' ').strip()
                    precio = float(page.within_bbox(row.cells[3]).extract_text().replace(',', '.').strip())
                    
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
                    productos.append({"sku": sku, "descripcion": desc, "precio": precio, "categoria": "General", "foto_path": foto_path})
                except: continue
    doc.close()
    df = pd.DataFrame(productos)
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM productos")
    df.to_sql('productos', conn, if_exists='append', index=False)
    conn.close()
    return df

# --- INTERFAZ ---
init_db()

# 🤫 EL BOTÓN SECRETO
# Si escribes "ADMIN_COLOR" en el buscador, se activará el panel maestro
st.title("🛒 Catálogo Color Insumos")
busqueda = st.text_input("🔍 Buscar producto...", placeholder="Escribe aquí para buscar...")

if busqueda == "ADMIN_COLOR":
    st.warning("🛠️ MODO ADMINISTRADOR ACTIVADO")
    user_admin = st.text_input("Usuario Admin")
    pass_admin = st.text_input("Clave Admin", type="password")
    
    if user_admin == "colorinsumos@gmail.com" and pass_admin == "20880157":
        st.success("Acceso Maestro Concedido")
        archivo = st.file_uploader("Subir PDF Catálogo", type="pdf")
        if archivo and st.button("🚀 Actualizar Base de Datos"):
            procesar_pdf(archivo)
            st.success("✅ Catálogo actualizado. Borra el buscador para volver.")
    else:
        if user_admin != "": st.error("Credenciales incorrectas")
    st.stop() # Detiene la ejecución para que los clientes no vean nada mientras logueas

# --- VISTA DE CLIENTES ---
df_cat = cargar_catalogo()

if df_cat.empty:
    st.info("Catálogo vacío. El administrador debe cargar el PDF.")
else:
    # Filtrar por búsqueda real
    df_res = df_cat[df_cat['descripcion'].str.contains(busqueda, case=False) | df_res['sku'].str.contains(busqueda, case=False)] if busqueda else df_cat
    
    cols = st.columns(4)
    for idx, row in df_res.iterrows():
        with cols[idx % 4]:
            with st.container(border=True):
                if row['foto_path'] and os.path.exists(row['foto_path']):
                    st.image(row['foto_path'], width=150)
                st.write(f"**{row['sku']}**")
                st.caption(row['descripcion'])
                st.write(f"💰 ${row['precio']:.2f}")
                st.number_input("Cant.", min_value=0, key=f"q_{row['sku']}")

# BOTÓN DE WHATSAPP AL FINAL
st.sidebar.markdown("---")
st.sidebar.button("📞 Enviar Pedido por WhatsApp")