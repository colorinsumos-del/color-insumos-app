import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import json
import shutil
import time
from datetime import datetime

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema de Pedidos", layout="wide")

# --- ESTILO CSS (Scrollbar y Diseño) ---
st.markdown("""
    <style>
        [data-testid="stSidebarNav"] { max-height: 100vh; overflow-y: auto; }
        section[data-testid="stSidebar"] > div { height: 100vh; overflow-y: auto; }
        .stButton button { border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    try:
        conn.execute("INSERT OR REPLACE INTO usuarios (username, password, nombre, rol) VALUES (?, ?, ?, ?)",
                     ('colorinsumos@gmail.com', '20880157', 'Administrador Maestro', 'admin'))
        conn.commit()
    except: pass
    conn.close()

# --- ESTADO DE SESIÓN ---
if 'auth' not in st.session_state: st.session_state.auth = False
if 'user_data' not in st.session_state: st.session_state.user_data = None
if 'carrito' not in st.session_state: st.session_state.carrito = {}

init_db()

# --- FUNCIONES DE APOYO ---
def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ", "MEMORIA"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA"]): return "✂️ OFICINA / ESCOLAR"
    return "📦 VARIOS"

def procesar_pdf(pdf_file):
    progress_bar = st.progress(0)
    status_text = st.empty()
    with open("temp.pdf", "wb") as f: f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)

    with pdfplumber.open("temp.pdf") as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            status_text.text(f"Analizando página {i+1} de {total_pages}...")
            tables = page.find_tables()
            if not tables: continue
            imgs_pag = [{'bbox': img['bbox'], 'xref': x[0]} for img, x in zip(doc[i].get_image_info(), doc[i].get_images(full=True))]
            for row in tables[0].rows:
                try:
                    sku_t = page.within_bbox(row.cells[0]).extract_text()
                    if not sku_t or "REFERENCIA" in sku_t.upper(): continue
                    sku = sku_t.strip().split('\n')[0]
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
            progress_bar.progress((i + 1) / total_pages)
            
    df = pd.DataFrame(productos)
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM productos"); df.to_sql('productos', conn, if_exists='append', index=False); conn.close()
    status_text.success("✅ ¡Catálogo importado!")
    time.sleep(1.5)
    progress_bar.empty()
    status_text.empty()

# --- INTERFAZ ---
if not st.session_state.auth:
    st.title("🚀 Color Insumos - Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        conn = sqlite3.connect(DB_NAME)
        res = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        conn.close()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Usuario o clave incorrecta")
else:
    user = st.session_state.user_data
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False; st.rerun()
        st.divider()
        nav = ["🛒 Tienda", "📁 Cargar PDF", "👥 Clientes", "📊 Pedidos Totales"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav)

    # --- COMPRAS Y CARRITO ---
    if menu in ["🛒 Tienda", "🛒 Comprar"]:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🛒 Carrito"])
        with t1:
            conn = sqlite3.connect(DB_NAME)
            df_cat = pd.read_sql("SELECT * FROM productos", conn)
            conn.close()
            if not df_cat.empty:
                busq = st.text_input("Buscar producto...")
                df_v = df_cat[df_cat['descripcion'].str.contains(busq, case=False)] if busq else df_cat
                for cat in sorted(df_v['categoria'].unique()):
                    with st.expander(cat):
                        itms = df_v[df_v['categoria'] == cat]
                        cols = st.columns(4)
                        for idx, row in itms.reset_index().iterrows():
                            with cols[idx % 4]:
                                with st.container(border=True):
                                    if row['foto_path']: st.image(row['foto_path'], use_container_width=True)
                                    st.write(f"**{row['sku']}**")
                                    st.write(f"${row['precio']:.2f}")
                                    cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
                                    if st.button("Añadir", key=f"b_{row['sku']}_{idx}"):
                                        st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                                        st.toast(f"Añadido {row['sku']}")
        with t2:
            if not st.session_state.carrito: st.info("El carrito está vacío.")
            else:
                resumen = []
                total = 0
                for sku, info in list(st.session_state.carrito.items()):
                    sub = info['p'] * info['c']
                    total += sub
                    st.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']}) = **${sub:.2f}**")
                    resumen.append({"SKU": sku, "Descripción": info['desc'], "Precio": info['p'], "Cantidad": info['c'], "Subtotal": sub})
                st.write(f"## Total: ${total:.2f}")
                
                if st.button("🚀 Confirmar Pedido Web", type="primary", use_container_width=True):
                    with st.spinner("Procesando su pedido..."):
                        conn = sqlite3.connect(DB_NAME)
                        # Guardamos con fecha y hora actual
                        fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
                        conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                     (user['user'], fecha_hoy, json.dumps(resumen), total, "Pendiente"))
                        conn.commit(); conn.close()
                        time.sleep(1)
                        st.session_state.carrito = {}
                        st.success("¡Pedido enviado con éxito!")
                        st.balloons()
                        st.rerun()

    # --- HISTORIAL DE PEDIDOS (CON DESCARGA EXCEL) ---
    elif menu in ["📜 Mis Pedidos", "📊 Pedidos Totales"]:
        st.title("Historial de Pedidos Registrados")
        conn = sqlite3.connect(DB_NAME)
        # Filtrar si es cliente o mostrar todo si es admin
        if user['rol'] == 'cliente':
            query = "SELECT * FROM pedidos WHERE username=? ORDER BY id DESC"
            params = (user['user'],)
        else:
            query = "SELECT * FROM pedidos ORDER BY id DESC"
            params = ()
            
        peds = pd.read_sql(query, conn, params=params)
        conn.close()
        
        if peds.empty: 
            st.warning("No se encontraron registros de pedidos.")
        else:
            for _, p in peds.iterrows():
                with st.expander(f"📦 Pedido #{p['id']} | Cliente: {p['username']} | Fecha: {p['fecha']}"):
                    lista_items = json.loads(p['items'])
                    df_items = pd.DataFrame(lista_items)
                    st.table(df_items)
                    st.write(f"### Total del pedido: ${p['total']:.2f}")
                    
                    # --- BOTÓN DE DESCARGA PARA ESTE PEDIDO ESPECÍFICO ---
                    # Limpiamos el nombre de usuario para el archivo
                    nombre_archivo = f"Pedido_{p['username']}_{p['fecha'].replace('/', '-').replace(':', '')}.xlsx"
                    
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_items.to_excel(writer, index=False, sheet_name='Detalle Pedido')
                    
                    st.download_button(
                        label=f"📥 Descargar Excel del Pedido #{p['id']}",
                        data=output.getvalue(),
                        file_name=nombre_archivo,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{p['id']}"
                    )

    # --- ADMINISTRACIÓN ---
    elif menu == "📁 Cargar PDF":
        st.subheader("Actualizar Catálogo desde PDF")
        f = st.file_uploader("Seleccione el archivo PDF", type="pdf")
        if f and st.button("Iniciar Procesamiento"):
            with st.spinner("Extrayendo productos e imágenes..."):
                procesar_pdf(f)
                st.rerun()

    elif menu == "👥 Clientes":
        st.subheader("Registrar Nuevo Cliente")
        with st.form("new_cli"):
            nu = st.text_input("Usuario (Email)")
            np = st.text_input("Contraseña")
            nn = st.text_input("Nombre de la Empresa / Cliente")
            if st.form_submit_button("Registrar Cliente"):
                if nu and np and nn:
                    conn = sqlite3.connect(DB_NAME)
                    try: 
                        conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (nu, np, nn, 'cliente'))
                        conn.commit(); st.success(f"Cliente '{nn}' creado correctamente.")
                    except: st.error("El usuario ya existe.")
                    conn.close()
                else: st.warning("Por favor complete todos los campos.")