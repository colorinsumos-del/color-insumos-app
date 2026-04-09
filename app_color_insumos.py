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

st.set_page_config(page_title="Catálogo Color Insumos", layout="wide")

# --- INICIALIZACIÓN DEL ESTADO ---
if 'carrito' not in st.session_state: 
    st.session_state.carrito = {}

# --- CONEXIÓN A GOOGLE SHEETS ---
try:
    conn_gs = st.connection("gsheets", type=GSheetsConnection)
except:
    st.error("Error al configurar la conexión GSheets. Verifica tus Secrets.")

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

# --- MOTOR DE EXTRACCIÓN (PDF + FOTOS + DB) ---
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

# --- INTERFAZ ---
init_db()
df_cat = cargar_catalogo()

# --- MENÚ LATERAL (SIDEBAR) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3081/3081840.png", width=100)
    
    # MÓDULO 1: ACCESO Y ADMINISTRACIÓN
    st.title("Administración")
    with st.expander("🔑 Iniciar Sesión Admin"):
        user = st.text_input("Usuario / Correo")
        passw = st.text_input("Contraseña", type="password")
        
        if user and passw == "20880157":
            st.success(f"Bienvenido, {user}")
            
            st.subheader("📦 Módulo de Carga")
            nuevo_pdf = st.file_uploader("Subir Catálogo (PDF)", type="pdf")
            if nuevo_pdf and st.button("🚀 Sincronizar Todo (Fotos y DB)"):
                with st.spinner("Procesando PDF, extrayendo imágenes y actualizando base de datos..."):
                    df_n = procesar_pdf_a_db(nuevo_pdf)
                    actualizar_base_datos(df_n)
                    st.success("✅ ¡Sincronización Completa!")
                    st.rerun()

            st.divider()
            st.subheader("👥 Módulo de Clientes")
            if st.button("📊 Ver Pedidos en la Nube"):
                try:
                    df_pedidos = conn_gs.read(worksheet="Pedidos")
                    st.dataframe(df_pedidos)
                except:
                    st.error("No se pudo conectar a la Nube. Revisa los Secrets.")

    # MÓDULO 2: CARRITO DE COMPRAS
    if st.session_state.carrito:
        st.divider()
        st.title("🛒 Carrito")
        nom_cliente = st.text_input("Nombre del Cliente", key="nom_cli")
        
        total = 0
        lista_pedidos = []
        for sku, info in st.session_state.carrito.items():
            subt = info['precio'] * info['cant']
            total += subt
            lista_pedidos.append({"Cliente": nom_cliente, "SKU": sku, "Cant": info['cant'], "Total": round(subt, 2)})
            st.caption(f"{info['cant']}x {sku} (${subt:.2f})")
        
        st.write(f"**Total a Pagar: ${total:.2f}**")
        
        # Botón para la Nube
        if st.button("☁️ Enviar Pedido a la Nube"):
            if not nom_cliente:
                st.error("Falta el nombre.")
            else:
                try:
                    df_gs = conn_gs.read(worksheet="Pedidos")
                    df_final = pd.concat([df_gs, pd.DataFrame(lista_pedidos)], ignore_index=True)
                    conn_gs.update(worksheet="Pedidos", data=df_final)
                    st.success("Pedido enviado.")
                except:
                    st.error("Error de conexión.")

        # Botón para Excel Local
        if st.button("📄 Descargar Excel Local"):
            df_xl = pd.DataFrame(lista_pedidos)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as w:
                df_xl.to_excel(w, index=False)
            st.download_button("📥 Bajar Excel", buf.getvalue(), "pedido.xlsx")

# --- VISTA PRINCIPAL (COMPRADOR) ---
st.title("🏬 Color Insumos - Catálogo")

if df_cat.empty:
    st.info("El catálogo está vacío. El administrador debe sincronizar el PDF.")
else:
    c1, c2 = st.columns([2, 1])
    buscar = c1.text_input("🔍 Buscar producto...")
    filtro = c2.selectbox("📂 Categoría:", ["TODAS"] + sorted(df_cat['categoria'].unique().tolist()))
    
    df_f = df_cat[df_cat['descripcion'].str.contains(buscar, case=False) | df_cat['sku'].str.contains(buscar, case=False)]
    if filtro != "TODAS": df_f = df_f[df_f['categoria'] == filtro]

    for cat in sorted(df_f['categoria'].unique()):
        st.header(cat)
        rows = df_f[df_f['categoria'] == cat]
        cols = st.columns(4)
        for i, row in rows.reset_index().iterrows():
            with cols[i % 4]:
                with st.container(border=True):
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], width=150)
                    else: st.write("🖼️ Sin Foto")
                    st.write(f"**{row['sku']}**")
                    st.caption(row['descripcion'])
                    st.write(f"**${row['precio']:.2f}**")
                    c_input = st.number_input("Cant.", min_value=0, key=f"in_{row['sku']}", step=1)
                    if c_input > 0:
                        st.session_state.carrito[row['sku']] = {"precio": row['precio'], "cant": c_input}
                    elif row['sku'] in st.session_state.carrito:
                        del st.session_state.carrito[row['sku']]