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
from PIL import Image  # Asegúrate de tener instalado Pillow: python -m pip install Pillow

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE VELOCIDAD (CACHÉ) ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=600)
def obtener_catalogo_cache():
    conn = get_connection()
    return pd.read_sql("SELECT * FROM productos", conn)

# --- INICIALIZACIÓN Y MIGRACIÓN ---
def init_db():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Migración de columnas si no existen
    cursor = conn.execute("PRAGMA table_info(usuarios)")
    columnas = [info[1] for info in cursor.fetchall()]
    if "direccion" not in columnas: conn.execute("ALTER TABLE usuarios ADD COLUMN direccion TEXT DEFAULT ''")
    if "telefono" not in columnas: conn.execute("ALTER TABLE usuarios ADD COLUMN telefono TEXT DEFAULT ''")
    
    try:
        conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                     ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Oficina Central', '0000-0000'))
        conn.commit()
    except: pass

# --- PROCESAMIENTO DE PDF CON OPTIMIZACIÓN DE IMÁGENES ---
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
                            
                            # Redimensionar imagen para que sea pequeña y rápida
                            img_pil = Image.open(io.BytesIO(pix.tobytes()))
                            img_pil.thumbnail((300, 300)) 
                            f_path = os.path.join(IMG_DIR, f"{sku}.webp")
                            img_pil.save(f_path, "WEBP", quality=75)
                            break
                    
                    productos.append({"sku": sku, "descripcion": desc, "precio": precio, "categoria": "VARIOS", "foto_path": f_path})
                except: continue
            progress_bar.progress((i + 1) / total_p)
            
    pd.DataFrame(productos).to_sql('productos', get_connection(), if_exists='replace', index=False)
    st.cache_data.clear()
    st.success("Catálogo y fotos optimizadas.")

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        st.write(f"**{row['sku']}**")
        st.write(f"### ${row['precio']:.2f}")
        cant = st.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("➕ Añadir", key=f"b_{row['sku']}_{idx}", use_container_width=True):
            st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast("✅ Añadido")

# --- INICIO APP ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'carrito' not in st.session_state: st.session_state.carrito = {}
if 'pago_divisas' not in st.session_state: st.session_state.pago_divisas = False

if not st.session_state.auth:
    st.title("🚀 Acceso Color Insumos")
    u, p = st.text_input("Usuario"), st.text_input("Clave", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"): st.session_state.auth = False; st.rerun()
        nav = ["🛒 Tienda", "📊 Pedidos", "📁 Cargar PDF", "👥 Clientes"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav)

    # --- TIENDA Y CARRITO CON DESCUENTOS ---
    if "🛒" in menu:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🧾 Mi Carrito"])
        with t1:
            df = obtener_catalogo_cache()
            busq = st.text_input("🔍 Buscar SKU o Nombre...")
            if busq:
                df_v = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
                cols = st.columns(5) 
                for idx, row in df_v.reset_index().iterrows():
                    with cols[idx % 5]: card_producto(row, idx)
            else: st.info("Busca productos para empezar.")

        with t2:
            if not st.session_state.carrito: st.info("Carrito vacío.")
            else:
                total_base = 0
                resumen = []
                for sku, info in list(st.session_state.carrito.items()):
                    sub = info['p'] * info['c']
                    total_base += sub
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([3, 1, 1])
                        c1.write(f"**{sku}** - {info['desc']} ({info['c']} x ${info['p']})")
                        c2.write(f"**${sub:.2f}**")
                        if c3.button("🗑️", key=f"rm_{sku}"): del st.session_state.carrito[sku]; st.rerun()
                    resumen.append({"SKU": sku, "Desc": info['desc'], "Cant": info['c'], "Subtotal": sub})
                
                # --- LÓGICA DE DESCUENTOS ---
                st.divider()
                st.write(f"Subtotal: ${total_base:.2f}")
                
                total_final = total_base
                # Descuento 10% por monto > $100
                if total_base > 100:
                    desc_monto = total_base * 0.10
                    total_final -= desc_monto
                    st.success(f"🎉 Descuento automático 10% aplicado (-${desc_monto:.2f})")
                
                # Opción de Pago en Divisas (30%)
                st.session_state.pago_divisas = st.toggle("💸 ¿Pagar en Divisas? (Aplica 30% de descuento adicional)", value=st.session_state.pago_divisas)
                
                if st.session_state.pago_divisas:
                    desc_divisa = total_final * 0.30
                    total_final -= desc_divisa
                    st.info(f"✨ Descuento por pago en divisas aplicado (-${desc_divisa:.2f})")
                
                st.write(f"## Total a Pagar: ${total_final:.2f}")
                
                if st.button("🚀 Confirmar Pedido", type="primary", use_container_width=True):
                    get_connection().execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%y %H:%M"), json.dumps(resumen), total_final, "Pendiente"))
                    get_connection().commit(); st.session_state.carrito = {}; st.success("¡Pedido enviado!"); st.rerun()

    # --- GESTIÓN DE CLIENTES (LISTA CORREGIDA) ---
    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        t_list, t_new = st.tabs(["📝 Ver Lista Completa", "➕ Nuevo Registro"])
        with t_list:
            # Selecciona a todos los usuarios registrados que no son administradores principales
            df_u = pd.read_sql("SELECT * FROM usuarios WHERE rol != 'admin'", get_connection())
            if df_u.empty:
                st.warning("No hay clientes registrados aún.")
            else:
                for idx, row in df_u.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 2, 1])
                        c1.write(f"**{row['nombre']}**"); c1.caption(f"ID: {row['username']}")
                        c2.write(f"📞 {row['telefono']}"); c2.write(f"📍 {row['direccion']}")
                        if c3.button("🗑️ Borrar", key=f"del_u_{row['username']}"):
                            get_connection().execute("DELETE FROM usuarios WHERE username=?", (row['username'],))
                            get_connection().commit(); st.rerun()
                        if st.button("✏️ Editar", key=f"ed_btn_{row['username']}"): st.session_state[f"ed_{row['username']}"] = True
                        
                        if st.session_state.get(f"ed_{row['username']}", False):
                            with st.form(f"f_edit_{row['username']}"):
                                en = st.text_input("Nombre", value=row['nombre'])
                                et = st.text_input("Teléfono", value=row['telefono'])
                                ed = st.text_area("Dirección", value=row['direccion'])
                                ep = st.text_input("Clave", value=row['password'])
                                if st.form_submit_button("Guardar Cambios"):
                                    get_connection().execute("UPDATE usuarios SET nombre=?, telefono=?, direccion=?, password=? WHERE username=?", (en, et, ed, ep, row['username']))
                                    get_connection().commit(); st.session_state[f"ed_{row['username']}"] = False; st.rerun()
        with t_new:
            with st.form("new_u_form"):
                nu, np, nn = st.text_input("ID/Email"), st.text_input("Clave"), st.text_input("Nombre Empresa")
                nt, nd = st.text_input("Teléfono"), st.text_area("Dirección")
                if st.form_submit_button("Registrar Cliente"):
                    try:
                        get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (nu, np, nn, 'cliente', nd, nt))
                        get_connection().commit(); st.success("Registrado correctamente"); st.rerun()
                    except: st.error("Error: El usuario ya existe.")

    # --- PEDIDOS TOTALES ---
    elif menu == "📊 Pedidos":
        st.title("📊 Control de Ventas")
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} ({p['fecha']})"):
                st.table(pd.DataFrame(json.loads(p['items'])))
                st.write(f"### Total: ${p['total']:.2f}")
                if st.button(f"🗑️ Eliminar Pedido #{p['id']}", key=f"dp_{p['id']}"):
                    get_connection().execute("DELETE FROM pedidos WHERE id=?", (p['id'],))
                    get_connection().commit(); st.rerun()

    # --- CARGA PDF ---
    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Procesar Catálogo"):
            with st.spinner("Optimizando imágenes..."): procesar_pdf(f)