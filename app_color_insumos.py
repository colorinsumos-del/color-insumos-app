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

st.set_page_config(page_title="Color Insumos - Sistema Profesional", layout="wide")

# --- MOTOR DE VELOCIDAD (CACHÉ) ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

def sincronizar_ahora():
    st.cache_data.clear()
    st.toast("🔄 Catálogo sincronizado al instante")

# --- ESTILOS ---
st.markdown("""
    <style>
        [data-testid="stSidebarNav"] { max-height: 100vh; overflow-y: auto; }
        .stButton button { border-radius: 8px; }
        .stTabs [data-baseweb="tab-list"] { gap: 20px; }
    </style>
""", unsafe_allow_html=True)

def init_db():
    conn = get_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS productos (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS pedidos (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)')
    try:
        conn.execute("INSERT OR REPLACE INTO usuarios VALUES (?, ?, ?, ?)", ('colorinsumos@gmail.com', '20880157', 'Administrador Maestro', 'admin'))
        conn.commit()
    except: pass

# --- FRAGMENTO DE PRODUCTO ---
@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:60] + "...")
        st.write(f"### ${row['precio']:.2f}")
        
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast(f"✅ {row['sku']} en carrito")
            time.sleep(0.5)
            st.rerun()

# --- LÓGICA DE PDF (ADMIN) ---
def procesar_pdf(pdf_file):
    progress = st.progress(0)
    with open("temp.pdf", "wb") as f: f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)
    with pdfplumber.open("temp.pdf") as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
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
            progress.progress((i + 1) / total)
    pd.DataFrame(productos).to_sql('productos', get_connection(), if_exists='replace', index=False)
    st.cache_data.clear()

def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ"]): return "🧩 JUEGOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA"]): return "📄 PAPELERÍA"
    return "📦 VARIOS"

# --- INICIO DE SESIÓN ---
if 'auth' not in st.session_state: st.session_state.auth = False
if 'user_data' not in st.session_state: st.session_state.user_data = None
if 'carrito' not in st.session_state: st.session_state.carrito = {}

init_db()

if not st.session_state.auth:
    st.title("🚀 Color Insumos - Acceso")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
else:
    user = st.session_state.user_data
    num_items = len(st.session_state.carrito)
    
    # --- MENÚ LATERAL ---
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("🔄 Sincronizar", use_container_width=True): sincronizar_ahora(); st.rerun()
        if st.button("Cerrar Sesión", type="secondary"): st.session_state.auth = False; st.rerun()
        st.divider()
        cart_lbl = f"🛒 Carrito ({num_items})" if num_items > 0 else "🛒 Comprar"
        if user['rol'] == 'admin':
            menu = st.radio("Navegación", [cart_lbl, "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Clientes"])
        else:
            menu = st.radio("Navegación", [cart_lbl, "📜 Mis Pedidos"])

    # --- TIENDA Y CARRITO ---
    if "🛒" in menu:
        t_cat, t_car = st.tabs(["🛍️ Catálogo", "🧾 Mi Pedido"])
        
        with t_cat:
            df = obtener_catalogo_cache()
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar SKU o Nombre...")
            cats = ["Todas"] + sorted(df['categoria'].unique().tolist())
            cat_sel = c2.selectbox("Categoría", cats)
            
            df_v = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)] if busq else df
            if cat_sel != "Todas": df_v = df_v[df_v['categoria'] == cat_sel]
            
            for cat in sorted(df_v['categoria'].unique()):
                with st.expander(f"{cat}", expanded=True):
                    items = df_v[df_v['categoria'] == cat]
                    cols = st.columns(4)
                    for idx, row in items.reset_index().iterrows():
                        with cols[idx % 4]: card_producto(row, idx)

        with t_car:
            if not st.session_state.carrito: st.info("El carrito está vacío.")
            else:
                total = 0
                resumen = []
                for sku, info in list(st.session_state.carrito.items()):
                    sub = info['p'] * info['c']
                    total += sub
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        col1.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']})")
                        col2.write(f"**${sub:.2f}**")
                        if col3.button("🗑️", key=f"del_{sku}"): del st.session_state.carrito[sku]; st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Precio": info['p'], "Cant": info['c'], "Subtotal": sub})
                
                st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                    with st.spinner("Guardando..."):
                        conn = get_connection()
                        conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                     (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                        conn.commit()
                        st.session_state.carrito = {}; st.success("¡Pedido enviado!"); st.balloons(); time.sleep(1); st.rerun()

    # --- HISTORIAL Y ADMINISTRACIÓN ---
    elif "Pedidos" in menu:
        st.title("Historial de Pedidos")
        conn = get_connection()
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else "SELECT * FROM pedidos WHERE username=? ORDER BY id DESC"
        peds = pd.read_sql(query, conn, params=() if user['rol'] == 'admin' else (user['user'],))
        
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} - {p['fecha']}"):
                df_p = pd.DataFrame(json.loads(p['items']))
                st.table(df_p)
                st.write(f"**Total: ${p['total']:.2f}**")
                
                # Botón de Descarga Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df_p.to_excel(writer, index=False)
                st.download_button(f"📥 Descargar Excel #{p['id']}", output.getvalue(), f"Pedido_{p['id']}.xlsx", key=f"dl_{p['id']}")

    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("Subir Catálogo PDF", type="pdf")
        if f and st.button("Iniciar"): 
            with st.spinner("Procesando..."): procesar_pdf(f); st.rerun()

    elif menu == "👥 Clientes":
        with st.form("new_u"):
            nu, np, nn = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
            if st.form_submit_button("Crear"):
                try:
                    conn = get_connection()
                    conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (nu, np, nn, 'cliente'))
                    conn.commit(); st.success("Cliente creado")
                except: st.error("El usuario ya existe")