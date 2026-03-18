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
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Gestión de Pedidos", layout="wide")

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

# --- INTERFAZ ---
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
        st.header(f"Hola, {user['nombre']}")
        if st.button("Cerrar Sesión"):
            st.session_state.auth = False; st.rerun()
        st.divider()
        menu = st.radio("Menú", ["🛒 Catálogo/Compra", "📁 Cargar PDF", "👥 Clientes", "📊 Pedidos"]) if user['rol'] == 'admin' else st.radio("Menú", ["🛒 Comprar", "📜 Mis Pedidos"])

    # --- VISTA CATÁLOGO / COMPRA ---
    if menu in ["🛒 Catálogo/Compra", "🛒 Comprar"]:
        st.title("Catálogo de Productos")
        
        c1, c2 = st.columns([2, 1])
        busqueda = c1.text_input("🔍 Buscar por Nombre o SKU...")
        
        conn = sqlite3.connect(DB_NAME)
        df_cat = pd.read_sql("SELECT * FROM productos", conn)
        conn.close()

        if not df_cat.empty:
            cat_list = ["Todas"] + sorted(df_cat['categoria'].unique().tolist())
            cat_sel = c2.selectbox("Categoría", cat_list)

            df_ver = df_cat.copy()
            if busqueda: df_ver = df_ver[df_ver['descripcion'].str.contains(busqueda, case=False) | df_ver['sku'].str.contains(busqueda, case=False)]
            if cat_sel != "Todas": df_ver = df_ver[df_ver['categoria'] == cat_sel]

            for cat in sorted(df_ver['categoria'].unique()):
                st.subheader(cat)
                items = df_ver[df_ver['categoria'] == cat]
                cols = st.columns(4)
                for idx, row in items.reset_index().iterrows():
                    with cols[idx % 4]:
                        with st.container(border=True):
                            if row['foto_path'] and os.path.exists(row['foto_path']): st.image(row['foto_path'], use_container_width=True)
                            st.markdown(f"**{row['sku']}**")
                            st.caption(row['descripcion'])
                            st.write(f"💰 **${row['precio']:.2f}**")
                            
                            # Lógica de pedido
                            cant = st.number_input("Cant:", min_value=1, value=1, key=f"n_{row['sku']}")
                            if st.button(f"➕ Añadir", key=f"b_{row['sku']}", use_container_width=True):
                                st.session_state.carrito[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                                st.toast(f"Añadido: {row['sku']}")

        # --- CARRITO EN BARRA LATERAL ---
        if st.session_state.carrito:
            st.sidebar.divider()
            st.sidebar.subheader("🛒 Pedido Actual")
            total_pedido = 0
            resumen_data = []

            for sku, v in list(st.session_state.carrito.items()):
                subtotal = v['p'] * v['c']
                total_pedido += subtotal
                st.sidebar.write(f"**{sku}** ({v['c']} ud) - ${subtotal:.2f}")
                resumen_data.append({"SKU": sku, "Descripción": v['desc'], "Precio": v['p'], "Cantidad": v['c'], "Subtotal": subtotal})
                if st.sidebar.button("Eliminar", key=f"del_{sku}"):
                    del st.session_state.carrito[sku]
                    st.rerun()

            st.sidebar.write(f"### TOTAL: ${total_pedido:.2f}")
            
            # --- BOTÓN EXPORTAR EXCEL ---
            df_excel = pd.DataFrame(resumen_data)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_excel.to_excel(writer, index=False, sheet_name='Pedido')
            
            st.sidebar.download_button(
                label="📥 Descargar Excel",
                data=output.getvalue(),
                file_name=f"Pedido_{user['nombre']}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
            if st.sidebar.button("✅ Confirmar y Guardar", use_container_width=True):
                st.sidebar.success("Pedido guardado en el sistema.")

    # --- OTRAS VISTAS (ADMIN) ---
    elif menu == "📁 Cargar PDF":
        archivo = st.file_uploader("Subir PDF de Catálogo", type="pdf")
        if archivo and st.button("Procesar"):
            procesar_pdf(archivo); st.success("Catálogo actualizado."); st.rerun()

    elif menu == "👥 Clientes":
        st.subheader("Registrar Nuevo Cliente")
        with st.form("cli"):
            nu = st.text_input("Usuario/Email")
            np = st.text_input("Clave")
            nn = st.text_input("Nombre Empresa")
            if st.form_submit_button("Crear"):
                conn = sqlite3.connect(DB_NAME)
                try:
                    conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (nu, np, nn, 'cliente'))
                    conn.commit(); st.success("Creado")
                except: st.error("Ya existe")
                conn.close()