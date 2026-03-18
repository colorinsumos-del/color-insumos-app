import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import shutil
from datetime import datetime

# --- CONFIGURACIÓN E INICIALIZACIÓN ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema de Pedidos", layout="wide")

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
                    sku = page.within_bbox(row.cells[0]).extract_text().strip().split('\n')[0]
                    if not sku or "REFERENCIA" in sku.upper(): continue
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

# --- INTERFAZ DE ACCESO ---
if not st.session_state.auth:
    st.title("🚀 Color Insumos - Acceso")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        conn = sqlite3.connect(DB_NAME)
        res = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        conn.close()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False; st.rerun()
        st.divider()
        menu = st.radio("Navegación", ["🛒 Tienda / Catálogo", "📁 Cargar PDF", "👥 Clientes", "📊 Pedidos"]) if user['rol'] == 'admin' else st.radio("Navegación", ["🛒 Comprar", "📜 Mis Pedidos"])

    # --- VISTA TIENDA / COMPRA ---
    if menu in ["🛒 Tienda / Catálogo", "🛒 Comprar"]:
        tab1, tab2 = st.tabs(["🛍️ Catálogo de Productos", "🛒 Mi Carrito"])

        with tab1:
            st.subheader("Explorar Productos")
            c1, c2 = st.columns([2, 1])
            busqueda = c1.text_input("🔍 Buscar por Nombre o SKU...")
            
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
            st.subheader("Resumen de tu Pedido")
            if not st.session_state.carrito:
                st.info("Tu carrito está vacío. Agrega productos desde el catálogo.")
            else:
                total_global = 0
                resumen_lista = []
                
                # Tabla de edición
                for sku, info in list(st.session_state.carrito.items()):
                    with st.container(border=True):
                        col1, col2, col3, col4, col5 = st.columns([1, 2, 1, 1, 1])
                        col1.write(f"**{sku}**")
                        col2.write(info['desc'])
                        col3.write(f"${info['p']:.2f}")
                        
                        # Permitir modificar cantidad desde el carrito
                        nueva_cant = col4.number_input("Cant", min_value=1, value=info['c'], key=f"edit_{sku}")
                        st.session_state.carrito[sku]['c'] = nueva_cant
                        
                        subtotal = info['p'] * nueva_cant
                        total_global += subtotal
                        col5.write(f"**Sub: ${subtotal:.2f}**")
                        
                        if st.button("Eliminar 🗑️", key=f"del_{sku}"):
                            del st.session_state.carrito[sku]
                            st.rerun()
                        
                        resumen_lista.append({"SKU": sku, "Descripción": info['desc'], "Precio": info['p'], "Cantidad": nueva_cant, "Subtotal": subtotal})

                st.divider()
                st.write(f"## Total a Pagar: ${total_global:.2f}")

                col_ex, col_proc = st.columns(2)
                
                # --- EXPORTAR A EXCEL ---
                df_excel = pd.DataFrame(resumen_lista)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_excel.to_excel(writer, index=False, sheet_name='Pedido_ColorInsumos')
                
                col_ex.download_button(
                    label="📥 Descargar Pedido en Excel",
                    data=output.getvalue(),
                    file_name=f"Pedido_{user['user']}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

                # --- PROCESAR PEDIDO WEB ---
                if col_proc.button("🚀 Procesar Pedido Web", variant="primary", use_container_width=True):
                    conn = sqlite3.connect(DB_NAME)
                    items_json = json.dumps(resumen_lista)
                    conn.execute("INSERT INTO pedidos (username, fecha, items, total, status) VALUES (?,?,?,?,?)",
                                 (user['user'], datetime.now().strftime("%Y-%m-%d %H:%M"), items_json, total_global, "Pendiente"))
                    conn.commit()
                    conn.close()
                    st.session_state.carrito = {}
                    st.success("¡Pedido procesado correctamente! El administrador lo revisará pronto.")
                    st.balloons()

    # --- VISTA PEDIDOS (ADMIN) ---
    elif menu == "📊 Pedidos":
        st.title("Gestión de Pedidos Web")
        conn = sqlite3.connect(DB_NAME)
        df_pedidos = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", conn)
        conn.close()
        
        if df_pedidos.empty:
            st.write("No hay pedidos registrados aún.")
        else:
            for _, p in df_pedidos.iterrows():
                with st.expander(f"Pedido #{p['id']} - {p['username']} ({p['fecha']}) - Total: ${p['total']:.2f}"):
                    items = json.loads(p['items'])
                    st.table(pd.DataFrame(items))
                    st.write(f"Estado actual: **{p['status']}**")

    # --- CARGAR PDF / CLIENTES (ADMIN) ---
    elif menu == "📁 Cargar PDF":
        archivo = st.file_uploader("Subir Catálogo PDF", type="pdf")
        if archivo and st.button("Procesar"):
            procesar_pdf(archivo); st.success("Catálogo actualizado."); st.rerun()

    elif menu == "👥 Clientes":
        st.subheader("Registro de Clientes")
        with st.form("cli"):
            nu, np, nn = st.text_input("Usuario"), st.text_input("Clave"), st.text_input("Nombre")
            if st.form_submit_button("Registrar"):
                conn = sqlite3.connect(DB_NAME)
                try:
                    conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (nu, np, nn, 'cliente'))
                    conn.commit(); st.success("Cliente registrado con éxito.")
                except: st.error("El usuario ya existe.")
                conn.close()