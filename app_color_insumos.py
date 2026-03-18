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
        conn.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?)",
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
            status_text.text(f"Procesando página {i+1} de {total_pages}...")
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
    status_text.text("¡Catálogo actualizado con éxito!")
    time.sleep(1)
    progress_bar.empty()

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
        else: st.error("Error de acceso")
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
                                        st.toast("Añadido")
        with t2:
            if not st.session_state.carrito: st.info("Vacío")
            else:
                resumen = []
                total = 0
                for sku, info in list(st.session_state.carrito.items()):
                    sub = info['p'] * info['c']
                    total += sub
                    st.write(f"{sku} - {info['desc']} ({info['c']} x ${info['p']}) = ${sub:.2f}")
                    resumen.append({"SKU": sku, "Descripción": info['desc'], "Precio": info['p'], "Cantidad": info['c'], "Subtotal": sub})
                st.write(f"### Total: ${total:.2f}")
                
                if st.button("🚀 Procesar Pedido Web", type="primary"):
                    with st.spinner("Guardando pedido..."):
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                     (user['user'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                        conn.commit(); conn.close()
                        time.sleep(1) # Simulación de carga
                        st.session_state.carrito = {}
                        st.success("Pedido registrado correctamente.")
                        st.rerun()

    # --- HISTORIAL DE PEDIDOS (CORREGIDO) ---
    elif menu in ["📜 Mis Pedidos", "📊 Pedidos Totales"]:
        st.title("Historial de Pedidos")
        conn = sqlite3.connect(DB_NAME)
        # Si es cliente, solo ve los suyos. Si es admin, ve todos.
        query = "SELECT * FROM pedidos WHERE username=? ORDER BY id DESC" if user['rol'] == 'cliente' else "SELECT * FROM pedidos ORDER BY id DESC"
        params = (user['user'],) if user['rol'] == 'cliente' else ()
        peds = pd.read_sql(query, conn, params=params)
        conn.close()
        
        if peds.empty: st.warning("No hay pedidos registrados.")
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['fecha']} - Total: ${p['total']:.2f}"):
                st.table(pd.DataFrame(json.loads(p['items'])))
                st.write(f"Estado: **{p['status']}**")

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("PDF", type="pdf")
        if f and st.button("Procesar"):
            procesar_pdf(f); st.rerun()