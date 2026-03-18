import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import json
import shutil
from datetime import datetime

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema de Pedidos", layout="wide")

# --- ESTILO CSS (Scrollbar para Sidebar y Diseño) ---
st.markdown("""
    <style>
        /* Barra de scroll para el menú lateral */
        [data-testid="stSidebarNav"] {
            max-height: 100vh;
            overflow-y: auto;
        }
        section[data-testid="stSidebar"] > div {
            height: 100vh;
            overflow-y: auto;
        }
        /* Ajuste de tarjetas de producto */
        .stButton button {
            border-radius: 5px;
        }
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
    if any(x in d for x in ["ABACO", "DIDACTICO", "JUEGO", "ROMPECABEZA", "PZZ", "MEMORIA", "LOTERIA"]): return "🧩 JUEGOS Y DIDÁCTICOS"
    if any(x in d for x in ["MARCADOR", "LAPIZ", "BOLIGRAFO", "COLORES", "BORRADOR", "SACAPUNTA", "TIZA", "RESALTADOR"]): return "✏️ ESCRITURA"
    if any(x in d for x in ["PAPEL", "CARTULINA", "BLOCK", "LIBRETA", "CUADERNO", "RESMA", "SOBRE", "FORRO"]): return "📄 PAPELERÍA"
    if any(x in d for x in ["TIJERA", "REGLA", "PEGA", "GRAPADORA", "CINTA", "CORRECTOR", "CARPETA", "PERFORADORA"]): return "✂️ OFICINA / ESCOLAR"
    if any(x in d for x in ["TEMPERA", "PINCEL", "PLASTILINA", "FOAMI", "SILICON", "ESTUCHE", "ACUARELA"]): return "🎨 ARTE Y MANUALIDADES"
    return "📦 VARIOS"

def procesar_pdf(pdf_file):
    with open("temp.pdf", "wb") as f: f.write(pdf_file.getbuffer())
    doc = fitz.open("temp.pdf")
    productos = []
    if os.path.exists(IMG_DIR): shutil.rmtree(IMG_DIR)
    os.makedirs(IMG_DIR)
    with pdfplumber.open("temp.pdf") as pdf:
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
    df = pd.DataFrame(productos)
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM productos"); df.to_sql('productos', conn, if_exists='append', index=False); conn.close()

# --- INTERFAZ ---
if not st.session_state.auth:
    st.title("🚀 Color Insumos - Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Iniciar Sesión", type="primary"):
        conn = sqlite3.connect(DB_NAME)
        res = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        conn.close()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Acceso denegado")
else:
    user = st.session_state.user_data
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False; st.rerun()
        st.divider()
        nav = ["🛒 Tienda", "📁 Cargar PDF", "👥 Clientes", "📊 Pedidos"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav)

    if menu in ["🛒 Tienda", "🛒 Comprar"]:
        t1, t2 = st.tabs(["🛍️ Catálogo", "🛒 Mi Carrito"])

        with t1:
            c1, c2 = st.columns([2, 1])
            busq = c1.text_input("🔍 Buscar...")
            conn = sqlite3.connect(DB_NAME)
            df_cat = pd.read_sql("SELECT * FROM productos", conn)
            conn.close()

            if not df_cat.empty:
                cat_s = c2.selectbox("Categoría", ["Todas"] + sorted(df_cat['categoria'].unique().tolist()))
                df_v = df_cat.copy()
                if busq: df_v = df_v[df_v['descripcion'].str.contains(busq, case=False) | df_v['sku'].str.contains(busq, case=False)]
                if cat_s != "Todas": df_v = df_v[df_v['categoria'] == cat_s]

                for cat in sorted(df_v['categoria'].unique()):
                    with st.expander(f"{cat}", expanded=True):
                        itms = df_v[df_v['categoria'] == cat]
                        cols = st.columns(4)
                        for idx, row in itms.reset_index().iterrows():
                            # LA CLAVE AHORA USA EL ÍNDICE PARA EVITAR DUPLICADOS
                            unique_key = f"{row['sku']}_{idx}" 
                            with cols[idx % 4]:
                                with st.container(border=True):
                                    if row['foto_path'] and os.path.exists(row['foto_path']): st.image(row['foto_path'], use_container_width=True)
                                    st.write(f"**{row['sku']}**")
                                    st.caption(row['descripcion'])
                                    st.write(f"💰 **${row['precio']:.2f}**")
                                    
                                    cant = st.number_input("Cantidad:", min_value=1, value=1, key=f"q_{unique_key}")
                                    if st.button(f"➕ Añadir", key=f"b_{unique_key}", use_container_width=True):
                                        st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                                        st.toast(f"Agregado: {row['sku']}")

        with t2:
            if not st.session_state.carrito:
                st.info("Carrito vacío.")
            else:
                total = 0
                resumen = []
                for sku, info in list(st.session_state.carrito.items()):
                    with st.container(border=True):
                        c_a, c_b, c_c, c_d = st.columns([2, 1, 1, 1])
                        c_a.write(f"**{sku}** - {info['desc']}")
                        # Edición con llave segura
                        ncant = c_b.number_input("Cant", min_value=1, value=info['c'], key=f"edit_{sku}")
                        st.session_state.carrito[sku]['c'] = ncant
                        sub = info['p'] * ncant
                        total += sub
                        c_c.write(f"${sub:.2f}")
                        if c_d.button("🗑️", key=f"del_{sku}"):
                            del st.session_state.carrito[sku]; st.rerun()
                        resumen.append({"SKU": sku, "Descripción": info['desc'], "Precio": info['p'], "Cantidad": ncant, "Subtotal": sub})

                st.write(f"## Total: ${total:.2f}")
                # Exportar Excel
                df_ex = pd.DataFrame(resumen)
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w: df_ex.to_excel(w, index=False)
                st.download_button("📥 Descargar Excel", buf.getvalue(), "Pedido.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
                if st.button("🚀 Procesar Pedido", type="primary", use_container_width=True):
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%Y"), json.dumps(resumen), total, "Pendiente"))
                    conn.commit(); conn.close()
                    st.session_state.carrito = {}; st.success("¡Pedido enviado!"); st.rerun()

    # --- RESTO DE FUNCIONES ADMIN ---
    elif menu == "📊 Pedidos":
        conn = sqlite3.connect(DB_NAME)
        peds = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn)
        conn.close()
        for _, p in peds.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']}"):
                st.table(pd.DataFrame(json.loads(p['items'])))

    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("PDF", type="pdf")
        if f and st.button("Procesar"):
            procesar_pdf(f); st.success("Listo"); st.rerun()

    elif menu == "👥 Clientes":
        with st.form("new_cli"):
            u, p, n = st.text_input("User"), st.text_input("Pass"), st.text_input("Nombre")
            if st.form_submit_button("Crear"):
                conn = sqlite3.connect(DB_NAME)
                try: 
                    conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (u, p, n, 'cliente'))
                    conn.commit(); st.success("Creado")
                except: st.error("Error")
                conn.close()