import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import io
import shutil
# --- NUEVA LIBRERÍA PARA CONEXIÓN A NUBE ---
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Catálogo Color Insumos", layout="wide")

# --- NUEVA CONEXIÓN A GOOGLE SHEETS ---
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
    s = sku.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA"]): return "✂️ OFICINA / ESCOLAR"
    if any(x in d for x in ["STICKER", "CALCOMANIA", "ADHESIVA", "FOAMI"]): return "🎨 MANUALIDADES"
    return "📦 VARIOS"

# --- MOTOR DE EXTRACCIÓN (Tu lógica optimizada) ---
def procesar_pdf_a_db(pdf_file):
    with open("temp_admin.pdf", "wb") as f:
        f.write(pdf_file.getbuffer())
    
    doc = fitz.open("temp_admin.pdf")
    productos = []
    
    # Limpiar fotos antiguas
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
                    
                    # Imagen por coordenadas
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
                    
                    productos.append({
                        "sku": sku, "descripcion": desc, "precio": precio,
                        "categoria": obtener_categoria(sku, desc), "foto_path": foto_path
                    })
                except: continue
    doc.close()
    return pd.DataFrame(productos)

# --- INTERFAZ PRINCIPAL ---
init_db()
df_cat = cargar_catalogo()

# SIDEBAR: ADMIN Y CARRITO
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3081/3081840.png", width=100)
    st.title("Panel de Control")
    
    with st.expander("🔐 Acceso Administrador"):
        clave = st.text_input("Contraseña", type="password")
        if clave == "color2026": # CAMBIA TU CLAVE AQUÍ
            nuevo_pdf = st.file_uploader("Actualizar Lista PDF", type="pdf")
            if nuevo_pdf and st.button("🔄 Sincronizar Catálogo"):
                df_n = procesar_pdf_a_db(nuevo_pdf)
                actualizar_base_datos(df_n)
                st.success("¡Catálogo actualizado!")
                st.rerun()

# CUERPO DE LA APP (VISTA CLIENTE)
st.title("🏬 Catálogo Digital Color Insumos")

if df_cat.empty:
    st.warning("Aún no hay productos cargados. El administrador debe subir el PDF.")
else:
    # Buscador y Filtro
    c1, c2 = st.columns([2, 1])
    query = c1.text_input("🔍 Buscar por nombre o código:")
    filtro_cat = c2.selectbox("📂 Área:", ["TODAS"] + sorted(df_cat['categoria'].unique().tolist()))
    
    # Filtrado
    df_res = df_cat[df_cat['descripcion'].str.contains(query, case=False) | df_cat['sku'].str.contains(query, case=False)]
    if filtro_cat != "TODAS": df_res = df_res[df_res['categoria'] == filtro_cat]

    # Carrito en Session State
    if 'carrito' not in st.session_state: st.session_state.carrito = {}

    # Mostrar por Secciones
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

# RESUMEN DE PEDIDO (Solo si hay algo)
if st.session_state.carrito:
    st.sidebar.divider()
    st.sidebar.subheader("🛒 Tu Pedido")
    
    # NUEVO: Input para nombre del cliente antes de enviar
    nombre_cliente = st.sidebar.text_input("Tu Nombre / Empresa", key="cliente_nombre")
    
    total = 0
    resumen_list = []
    for s, info in st.session_state.carrito.items():
        sub = info['precio'] * info['cant']
        total += sub
        resumen_list.append({"Cliente": nombre_cliente, "SKU": s, "Cant": info['cant'], "Subt": round(sub, 2)})
        st.sidebar.caption(f"{info['cant']}x {s} (${sub:.2f})")
    
    st.sidebar.write(f"### TOTAL: ${total:.2f}")
    
    # NUEVA FUNCIÓN: Botón para enviar a Google Sheets
    if st.sidebar.button("🚀 Finalizar y Enviar Pedido"):
        if not nombre_cliente:
            st.sidebar.error("Por favor, ingresa tu nombre antes de enviar.")
        else:
            try:
                # Leer datos existentes de la pestaña "Pedidos"
                df_gs = conn_gs.read(worksheet="Pedidos")
                # Crear DataFrame con el pedido actual
                df_nuevo = pd.DataFrame(resumen_list)
                # Unir y subir
                df_final = pd.concat([df_gs, df_nuevo], ignore_index=True)
                conn_gs.update(worksheet="Pedidos", data=df_final)
                st.sidebar.success("✅ ¡Pedido enviado correctamente!")
            except Exception as e:
                st.sidebar.error(f"Error al conectar con la nube: {e}")

    # Exportar Excel (Mantenido)
    if st.sidebar.button("📊 Descargar Excel Local"):
        df_p = pd.DataFrame(resumen_list)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_p.to_excel(writer, index=False)
        st.sidebar.download_button("📥 Click para descargar", output.getvalue(), "mi_pedido.xlsx")