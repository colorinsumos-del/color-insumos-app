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

def init_db():
    conn = sqlite3.connect(DB_NAME)
    # Tabla de Productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de Usuarios
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT)''')
    # Tabla de Pedidos
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # Insertar Usuario Maestro
    try:
        conn.execute("""
            INSERT OR REPLACE INTO usuarios (username, password, nombre, rol) 
            VALUES (?, ?, ?, ?)
        """, ('colorinsumos@gmail.com', '20880157', 'Administrador Maestro', 'admin'))
        conn.commit()
    except:
        pass
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

# --- INTERFAZ DE USUARIO ---
if not st.session_state.auth:
    st.title("🚀 Color Insumos - Acceso")
    u = st.text_input("Usuario / Email")
    p = st.text_input("Contraseña", type="password")
    if st.button("Iniciar Sesión", type="primary"):
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
        nav_options = ["🛒 Tienda", "📁 Cargar PDF", "👥 Clientes", "📊 Pedidos Recibidos"] if user['rol'] == 'admin' else ["🛒 Comprar", "📜 Mis Pedidos"]
        menu = st.radio("Navegación", nav_options)

    # --- LÓGICA DE TIENDA Y CARRITO ---
    if menu in ["🛒 Tienda", "🛒 Comprar"]:
        tab1, tab2 = st.tabs(["🛍️ Catálogo", "🛒 Mi Carrito Detallado"])

        with tab1:
            st.subheader("Seleccione sus productos")
            c1, c2 = st.columns([2, 1])
            busqueda = c1.text_input("🔍 Buscar por SKU o Nombre...")
            
            conn = sqlite3.connect(DB_NAME)
            df_cat = pd.read_sql("SELECT * FROM productos", conn)
            conn.close()

            if not df_cat.empty:
                cat_sel = c2.selectbox("Categoría", ["Todas"] + sorted(df_cat['categoria'].unique().tolist()))
                df_ver = df_cat.copy()
                if busqueda: df_ver = df_ver[df_ver['descripcion'].str.contains(busqueda, case=False) | df_ver['sku'].str.contains(busqueda, case=False)]
                if cat_sel != "Todas": df_ver = df_ver[df_ver['categoria'] == cat_sel]

                for cat in sorted(df_ver['categoria'].unique()):
                    with st.expander(f"{cat}", expanded=True):
                        items = df_ver[df_ver['categoria'] == cat]
                        cols = st.columns(4)
                        for idx, row in items.reset_index().iterrows():
                            with cols[idx % 4]:
                                with st.container(border=True):
                                    if row['foto_path'] and os.path.exists(row['foto_path']): st.image(row['foto_path'], use_container_width=True)
                                    st.write(f"**{row['sku']}**")
                                    st.caption(row['descripcion'])
                                    st.write(f"💰 **${row['precio']:.2f}**")
                                    
                                    cant = st.number_input("Cantidad:", min_value=1, value=1, key=f"q_{row['sku']}")
                                    if st.button(f"➕ Añadir", key=f"b_{row['sku']}", use_container_width=True):
                                        st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                                        st.toast(f"Agregado: {row['sku']}")

        with tab2:
            st.subheader("Gestión de Pedido")
            if not st.session_state.carrito:
                st.info("El carrito está vacío.")
            else:
                total_global = 0
                resumen_final = []
                
                for sku, info in list(st.session_state.carrito.items()):
                    with st.container(border=True):
                        col1, col2, col3, col4, col5 = st.columns([1, 2, 1, 1, 1])
                        col1.write(f"**{sku}**")
                        col2.write(info['desc'])
                        col3.write(f"${info['p']:.2f}")
                        
                        # Edición de cantidad
                        n_cant = col4.number_input("Cant", min_value=1, value=info['c'], key=f"ed_{sku}")
                        st.session_state.carrito[sku]['c'] = n_cant
                        
                        subt = info['p'] * n_cant
                        total_global += subt
                        col5.write(f"**Sub: ${subt:.2f}**")
                        
                        if st.button("Eliminar ❌", key=f"rm_{sku}"):
                            del st.session_state.carrito[sku]
                            st.rerun()
                        
                        resumen_final.append({"SKU": sku, "Descripción": info['desc'], "Precio": info['p'], "Cantidad": n_cant, "Subtotal": subt})

                st.divider()
                st.write(f"## Total Final: ${total_global:.2f}")

                cx, cp = st.columns(2)
                
                # Excel
                df_ex = pd.DataFrame(resumen_final)
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as w:
                    df_ex.to_excel(w, index=False)
                
                cx.download_button("📥 Descargar Excel", buf.getvalue(), f"Pedido_{datetime.now().strftime('%d%m%Y')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

                if cp.button("🚀 Procesar Pedido Web", type="primary", use_container_width=True):
                    conn = sqlite3.connect(DB_NAME)
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(resumen_final), total_global, "Pendiente"))
                    conn.commit(); conn.close()
                    st.session_state.carrito = {}
                    st.success("Pedido procesado con éxito."); st.balloons(); st.rerun()

    # --- PANEL ADMIN (PEDIDOS) ---
    elif menu == "📊 Pedidos Recibidos":
        st.title("Pedidos de Clientes")
        conn = sqlite3.connect(DB_NAME)
        pedidos = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn)
        conn.close()
        for _, p in pedidos.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['username']} - ${p['total']:.2f}"):
                st.table(pd.DataFrame(json.loads(p['items'])))
                st.write(f"Fecha: {p['fecha']} | Estado: {p['status']}")

    # --- PANEL ADMIN (CARGA Y CLIENTES) ---
    elif menu == "📁 Cargar PDF":
        f = st.file_uploader("Subir PDF", type="pdf")
        if f and st.button("Actualizar Catálogo"):
            procesar_pdf(f); st.success("Catálogo actualizado."); st.rerun()

    elif menu == "👥 Clientes":
        st.subheader("Nuevo Cliente")
        with st.form("c"):
            u, p, n = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
            if st.form_submit_button("Crear"):
                conn = sqlite3.connect(DB_NAME)
                try:
                    conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (u, p, n, 'cliente'))
                    conn.commit(); st.success("Cliente Creado")
                except: st.error("Error: El usuario ya existe.")
                conn.close()