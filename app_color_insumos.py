import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import io
import shutil
# --- LIBRERÍA PARA LA NUBE ---
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Catálogo Color Insumos", layout="wide")

# --- INICIALIZACIÓN DEL ESTADO (Evita errores de carga) ---
if 'carrito' not in st.session_state: 
    st.session_state.carrito = {}

# --- CONEXIÓN A GOOGLE SHEETS ---
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

# --- LÓGICA DE CATEGORIZACIÓN ---
def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA"]): return "✂️ OFICINA / ESCOLAR"
    if any(x in d for x in ["STICKER", "CALCOMANIA", "ADHESIVA", "FOAMI"]): return "🎨 MANUALIDADES"
    return "📦 VARIOS"

# --- MOTOR DE EXTRACCIÓN ---
def procesar_pdf_a_db(pdf_file):
    with open("temp_admin.pdf", "wb") as f:
        f.write(pdf_file.getbuffer())
    doc = fitz.open("temp_admin.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)
    with pdfplumber.open("temp_admin.pdf") as pdf:
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
                    precio_txt = page.within_bbox(row.cells[3]).extract_text() or "0"
                    precio = float(precio_txt.replace(',', '.').strip())
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
                    productos.append({"sku": sku, "descripcion": desc, "precio": precio, "categoria": obtener_categoria(sku, desc), "foto_path": foto_path})
                except: continue
    doc.close()
    return pd.DataFrame(productos)

# --- INICIO DE INTERFAZ ---
init_db()
df_cat = cargar_catalogo()

# --- MENÚ LATERAL (Estructura Original Solicitada) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3081/3081840.png", width=100)
    
    # 1. MENÚ ADMINISTRADOR (Clave actualizada a 20880157)
    st.title("Panel Administrador")
    with st.expander("🔐 Acceder"):
        clave = st.text_input("Contraseña", type="password")
        if clave == "20880157":
            nuevo_pdf = st.file_uploader("Actualizar Lista PDF", type="pdf")
            if nuevo_pdf and st.button("🔄 Sincronizar Catálogo"):
                df_n = procesar_pdf_a_db(nuevo_pdf)
                actualizar_base_datos(df_n)
                st.success("¡Catálogo actualizado!")
                st.rerun()

    # 2. MENÚ COMPRADOR (Resumen de Carrito)
    if st.session_state.carrito:
        st.divider()
        st.subheader("🛒 Tu Carrito")
        nombre_cliente = st.text_input("Nombre / Empresa", key="cliente_nombre")
        
        total = 0
        resumen_list = []
        for s, info in st.session_state.carrito.items():
            sub = info['precio'] * info['cant']
            total += sub
            resumen_list.append({"Cliente": nombre_cliente, "SKU": s, "Cant": info['cant'], "Subt": round(sub, 2)})
            st.caption(f"{info['cant']}x {s} (${sub:.2f})")
        
        st.write(f"### TOTAL: ${total:.2f}")
        
        # Botón para enviar a Google Sheets
        if st.button("🚀 Confirmar Pedido (Nube)"):
            if not nombre_cliente:
                st.error("Por favor, ingresa tu nombre.")
            else:
                try:
                    df_gs = conn_gs.read(worksheet="Pedidos")
                    df_nuevo = pd.DataFrame(resumen_list)
                    df_final = pd.concat([df_gs, df_nuevo], ignore_index=True)
                    conn_gs.update(worksheet="Pedidos", data=df_final)
                    st.success("✅ Pedido enviado a la nube.")
                except Exception as e:
                    st.error(f"Error de conexión: {e}")

        # Botón para descargar Excel local
        if st.button("📊 Generar Excel Local"):
            df_p = pd.DataFrame(resumen_list)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_p.to_excel(writer, index=False)
            st.download_button("📥 Descargar Archivo", output.getvalue(), "mi_pedido.xlsx")

# --- CUERPO PRINCIPAL (CATÁLOGO) ---
st.title("🏬 Catálogo Digital Color Insumos")

if df_cat.empty:
    st.warning("Aún no hay productos cargados.")
else:
    c1, c2 = st.columns([2, 1])
    query = c1.text_input("🔍 Buscar por nombre o código:")
    filtro_cat = c2.selectbox("📂 Área:", ["TODAS"] + sorted(df_cat['categoria'].unique().tolist()))
    
    df_res = df_cat[df_cat['descripcion'].str.contains(query, case=False) | df_cat['sku'].str.contains(query, case=False)]
    if filtro_cat != "TODAS": df_res = df_res[df_res['categoria'] == filtro_cat]

    for cat in sorted(df_res['categoria'].unique()):
        st.header(cat)
        items = df_res[df_res['categoria'] == cat]
        cols = st.columns(4)
        for idx, row in items.reset_index().iterrows():
            with cols[idx % 4]:
                with st.container(border=True):
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], width=140)
                    else: st.write("🖼️ (Sin Imagen)")
                    st.markdown(f"**{row['sku']}**")
                    st.write(row['descripcion'])
                    st.info(f"Precio: ${row['precio']:.2f}")
                    cant = st.number_input("Cant.", min_value=0, key=f"k_{row['sku']}", step=1)
                    if cant > 0:
                        st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "precio": row['precio'], "cant": cant}
                    elif row['sku'] in st.session_state.carrito:
                        del st.session_state.carrito[row['sku']]