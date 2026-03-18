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

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- 2. MOTOR DE VELOCIDAD (CACHÉ) ---
@st.cache_resource
def get_connection():
    """Mantiene la conexión a la base de datos activa"""
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    """Carga el catálogo en RAM para que la búsqueda sea instantánea"""
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- 3. ESTILOS CSS (SCROLLBARS Y DISEÑO) ---
st.markdown("""
    <style>
        html { overflow-y: scroll !important; }
        [data-testid="stSidebar"] section { overflow-y: scroll !important; }
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-track { background: #f1f1f1; }
        ::-webkit-scrollbar-thumb { background: #888; border-radius: 5px; }
        ::-webkit-scrollbar-thumb:hover { background: #555; }
        .stButton button { border-radius: 8px; }
    </style>
""", unsafe_allow_html=True)

def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    try:
        conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                     ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Sede Principal', '0414-0000000'))
        conn.commit()
    except: pass

# --- 4. FUNCIONES DE LÓGICA ---
def obtener_categoria(sku, descripcion):
    d = descripcion.upper()
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ"]): return "🧩 JUEGOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA"]): return "✂️ OFICINA"
    return "📦 VARIOS"

def procesar_pdf(pdf_file):
    progress_bar = st.progress(0)
    with open("temp.pdf", "wb") as f: f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)
    
    with pdfplumber.open("temp.pdf") as pdf:
        total_p = len(pdf.pages)
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
            progress_bar.progress((i + 1) / total_p)
            
    df = pd.DataFrame(productos)
    df.to_sql('productos', get_connection(), if_exists='replace', index=False)
    st.cache_data.clear()
    st.success("Catálogo actualizado correctamente.")

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:60])
        st.write(f"### ${row['precio']:.2f}")
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast(f"✅ {row['sku']} añadido")
            time.sleep(0.5); st.rerun()

# --- 5. LÓGICA DE SESIÓN ---
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
        else: st.error("Acceso denegado")
else:
    user = st.session_state.user_data
    num_items = len(st.session_state.carrito)
    
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("🔄 Sincronizar Todo"): st.cache_data.clear(); st.rerun()
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        st.divider()
        cart_lbl = f"🛒 Carrito ({num_items})" if num_items > 0 else "🛒 Comprar"
        nav = [cart_lbl, "📊 Pedidos Totales", "📁 Cargar PDF", "👥 Gestión Clientes"] if user['rol'] == 'admin' else [cart_lbl, "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav)

    # --- SECCIÓN TIENDA ---
    if "🛒" in menu:
        t_cat, t_car = st.tabs(["🛍️ Catálogo Inteligente", "🧾 Revisar Mi Pedido"])
        with t_cat:
            df = obtener_catalogo_cache()
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar por SKU o Nombre...")
            cats = ["Seleccionar Categoría"] + sorted(df['categoria'].unique().tolist())
            cat_sel = c2.selectbox("📁 Filtrar por Categoría", cats)
            
            if busq or cat_sel != "Seleccionar Categoría":
                df_v = df.copy()
                if busq: df_v = df_v[df_v['descripcion'].str.contains(busq, case=False) | df_v['sku'].str.contains(busq, case=False)]
                if cat_sel != "Seleccionar Categoría": df_v = df_v[df_v['categoria'] == cat_sel]
                
                for cat in sorted(df_v['categoria'].unique()):
                    with st.expander(f"{cat}", expanded=True):
                        itms = df_v[df_v['categoria'] == cat]
                        cols = st.columns(4)
                        for idx, row in itms.reset_index().iterrows():
                            with cols[idx % 4]: card_producto(row, idx)
            else: st.info("Escribe algo o selecciona una categoría para ver productos.")

        with t_car:
            if not st.session_state.carrito: st.info("Carrito vacío.")
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
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                st.write(f"## Total: ${total:.2f}")
                if st.button("🚀 Confirmar Pedido Web", type="primary", use_container_width=True):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total, "Pendiente"))
                    get_connection().commit()
                    st.session_state.carrito = {}; st.success("¡Enviado!"); st.rerun()

    # --- GESTIÓN DE CLIENTES (ADMIN) ---
    elif menu == "👥 Gestión Clientes":
        st.title("👥 Administrador de Clientes")
        tab_list, tab_new = st.tabs(["📝 Lista y Edición", "➕ Nuevo Cliente"])
        with tab_list:
            df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol='cliente'", get_connection())
            for idx, row in df_u.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['nombre']}**"); c1.caption(f"ID: {row['username']}")
                    c2.write(f"📞 {row['telefono']}"); c2.write(f"📍 {row['direccion']}")
                    if c3.button("✏️ Editar", key=f"ed_{row['username']}"): st.session_state[f"ed_{row['username']}"] = True
                    
                    if st.session_state.get(f"ed_{row['username']}", False):
                        with st.form(f"f_{row['username']}"):
                            e_n = st.text_input("Nombre", value=row['nombre'])
                            e_t = st.text_input("Teléfono", value=row['telefono'])
                            e_d = st.text_area("Dirección", value=row['direccion'])
                            e_p = st.text_input("Clave", value=row['password'])
                            if st.form_submit_button("Guardar"):
                                get_connection().execute("UPDATE usuarios SET nombre=?, telefono=?, direccion=?, password=? WHERE username=?", (e_n, e_t, e_d, e_p, row['username']))
                                get_connection().commit(); st.session_state[f"ed_{row['username']}"] = False; st.rerun()
                    
                    if c3.button("🗑️ Borrar", key=f"dl_u_{row['username']}"):
                        get_connection().execute("DELETE FROM usuarios WHERE username=?", (row['username'],))
                        get_connection().commit(); st.rerun()
        with tab_new:
            with st.form("new_u"):
                n_u, n_p, n_n = st.text_input("Email/ID"), st.text_input("Clave"), st.text_input("Nombre Empresa")
                n_t, n_d = st.text_input("Teléfono"), st.text_area("Dirección")
                if st.form_submit_button("Registrar"):
                    get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (n_u, n_p, n_n, 'cliente', n_d, n_t))
                    get_connection().commit(); st.success("Creado"); st.rerun()

    # --- PEDIDOS TOTALES (ADMIN) ---
    elif menu == "📊 Pedidos Totales":
        st.title("📊 Control de Pedidos")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} ({p['fecha']})"):
                cli = get_connection().execute("SELECT nombre, telefono, direccion FROM usuarios WHERE username=?", (p['username'],)).fetchone()
                if cli: st.info(f"🚚 Entregar a: {cli[0]} | Tel: {cli[1]} | Dir: {cli[2]}")
                df_it = pd.DataFrame(json.loads(p['items']))
                st.table(df_it); st.write(f"### Total: ${p['total']:.2f}")
                
                c1, c2 = st.columns(2)
                if c1.button(f"🗑️ Eliminar Pedido", key=f"del_p_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df_it.to_excel(writer, index=False)
                c2.download_button("📥 Excel", output.getvalue(), f"Pedido_{p['id']}.xlsx", key=f"xl_{p['id']}")

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        st.title("📁 Actualizar Catálogo")
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Procesar Catálogo"):
            with st.spinner("Analizando..."): procesar_pdf(f)