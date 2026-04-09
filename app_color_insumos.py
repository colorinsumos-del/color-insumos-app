import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import io
import shutil
# --- NUEVO: MÓDULO DE CONEXIÓN A LA NUBE ---
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Catálogo Color Insumos", layout="wide")

# --- MÓDULO 1: GESTIÓN DE ESTADO (Evita errores de carga) ---
if 'carrito' not in st.session_state: 
    st.session_state.carrito = {}

# --- MÓDULO 2: CONEXIÓN A GOOGLE SHEETS ---
try:
    conn_gs = st.connection("gsheets", type=GSheetsConnection)
except Exception:
    st.sidebar.error("⚠️ Configura los 'Secrets' para usar la Nube.")

# --- MÓDULO 3: MOTOR DE BASE DE DATOS LOCAL ---
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

# --- MÓDULO 4: INTELIGENCIA DE CATEGORÍAS ---
def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA"]): return "✂️ OFICINA / ESCOLAR"
    if any(x in d for x in ["STICKER", "CALCOMANIA", "ADHESIVA", "FOAMI"]): return "🎨 MANUALIDADES"
    return "📦 VARIOS"

# --- MÓDULO 5: SINCRONIZACIÓN DE FOTOS Y DATOS (Extracción PDF) ---
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

# --- INICIO DE APLICACIÓN ---
init_db()
df_cat = cargar_catalogo()

# --- MÓDULO 6: MENÚ LATERAL (ADMIN + COMPRADOR) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3081/3081840.png", width=100)
    
    # SECCIÓN ADMIN
    st.title("Panel Administrativo")
    with st.expander("🔐 Acceso de Seguridad"):
        usuario = st.text_input("Correo / Usuario")
        clave = st.text_input("Contraseña", type="password")
        
        if usuario and clave == "20880157": # Tu clave definitiva
            st.success(f"Sesión iniciada: {usuario}")
            
            # Sub-módulo de carga
            st.markdown("### 🛠️ Herramientas")
            nuevo_pdf = st.file_uploader("Actualizar PDF", type="pdf")
            if nuevo_pdf and st.button("🔄 Sincronizar Fotos y Precios"):
                with st.spinner("Procesando catálogo..."):
                    df_n = procesar_pdf_a_db(nuevo_pdf)
                    actualizar_base_datos(df_n)
                    st.success("Sincronización Exitosa")
                    st.rerun()
            
            st.divider()
            # Sub-módulo de visualización de clientes
            if st.button("📂 Ver Clientes y Pedidos (Nube)"):
                try:
                    df_pedidos = conn_gs.read(worksheet="Pedidos")
                    st.write("### Listado de Pedidos Recibidos")
                    st.dataframe(df_pedidos)
                except:
                    st.error("No se pudo conectar con la base de datos en la nube.")

    # SECCIÓN CARRITO (Para el Comprador)
    if st.session_state.carrito:
        st.divider()
        st.title("🛒 Carrito de Compras")
        nom_cli = st.text_input("Tu Nombre o Empresa", key="nombre_ped")
        
        total = 0
        pedidos_nube = []
        for s, info in st.session_state.carrito.items():
            sub = info['precio'] * info['cant']
            total += sub
            pedidos_nube.append({"Cliente": nom_cli, "SKU": s, "Cant": info['cant'], "Total": round(sub, 2)})
            st.caption(f"{info['cant']}x {s} (${sub:.2f})")
        
        st.write(f"### TOTAL: ${total:.2f}")
        
        # Sub-módulo Nube
        if st.button("🚀 Confirmar Pedido (Nube)"):
            if not nom_cli:
                st.error("Falta el nombre del cliente.")
            else:
                try:
                    df_gs = conn_gs.read(worksheet="Pedidos")
                    df_final = pd.concat([df_gs, pd.DataFrame(pedidos_nube)], ignore_index=True)
                    conn_gs.update(worksheet="Pedidos", data=df_final)
                    st.success("✅ Pedido enviado a Color Insumos")
                except:
                    st.error("Error al enviar. Verifica los permisos.")

        # Sub-módulo Excel Local
        if st.button("📊 Descargar Excel Local"):
            df_xl = pd.DataFrame(pedidos_nube)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_xl.to_excel(writer, index=False)
            st.download_button("📥 Bajar Archivo", output.getvalue(), "mi_pedido.xlsx")

# --- MÓDULO 7: CUERPO PRINCIPAL (CATÁLOGO VISUAL) ---
st.title("🏬 Catálogo Digital Color Insumos")

if df_cat.empty:
    st.warning("Catálogo vacío. El Administrador debe sincronizar el PDF en el panel lateral.")
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
                    st.caption(row['descripcion'])
                    st.info(f"Precio: ${row['precio']:.2f}")
                    cant = st.number_input("Cant.", min_value=0, key=f"k_{row['sku']}", step=1)
                    if cant > 0:
                        st.session_state.carrito[row['sku']] = {"precio": row['precio'], "cant": cant}
                    elif row['sku'] in st.session_state.carrito:
                        del st.session_state.carrito[row['sku']]