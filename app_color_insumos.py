import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import sqlite3
import os
import json
import time
import re
import io
from datetime import datetime

# Librerías para PDF y Excel
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# --- CONFIGURACIÓN DE RUTAS ---
DB_NAME = "color_insumos_v10.db" 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "fotos")
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema Maestro", layout="wide")

# --- MOTOR DE DATOS ---
@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    # Tablas Base
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # --- SISTEMA DE MIGRACIÓN AUTOMÁTICA ---
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(pedidos)")
    cols_existentes = [info[1] for info in cursor.fetchall()]
    
    nuevas_cols = {
        "cliente_nombre": "TEXT",
        "metodo_pago": "TEXT",
        "subtotal": "REAL",
        "descuento": "REAL"
    }
    
    for col, tipo in nuevas_cols.items():
        if col not in cols_existentes:
            try:
                conn.execute(f"ALTER TABLE pedidos ADD COLUMN {col} {tipo}")
            except: pass

    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

# --- FUNCIONES DE EXPORTACIÓN ---
def generar_pdf_recibo(pedido, info_cliente):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Encabezado
    elements.append(Paragraph("<b>COLOR INSUMOS</b>", styles['Title']))
    elements.append(Paragraph("Comprobante de Pedido / Recibo", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Info Cliente
    detalles = [
        f"<b>Pedido #:</b> {pedido['id']}",
        f"<b>Fecha:</b> {pedido['fecha']}",
        f"<b>Cliente:</b> {pedido.get('cliente_nombre', 'N/A')}",
        f"<b>Teléfono:</b> {info_cliente[0] if info_cliente else 'N/A'}",
        f"<b>Dirección:</b> {info_cliente[1] if info_cliente else 'No registrada'}",
        f"<b>Método de Pago:</b> {pedido.get('metodo_pago', 'N/A')}"
    ]
    for d in detalles:
        elements.append(Paragraph(d, styles['Normal']))
    
    elements.append(Spacer(1, 15))

    # Tabla
    data = [["SKU", "Descripción", "Cant", "Precio", "Total"]]
    items = json.loads(pedido['items'])
    for i in items:
        p = i.get('Precio', i.get('precio', 0))
        c = i.get('Cant', i.get('cant', 0))
        data.append([i.get('sku', i.get('SKU')), i.get('desc', i.get('Desc')), c, f"${p:.2f}", f"${p*c:.2f}"])

    t = Table(data, colWidths=[60, 240, 40, 60, 60])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.darkblue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTSIZE', (0,0), (-1,-1), 9),
    ]))
    elements.append(t)
    
    # Manejo de nulos para evitar TypeError
    sub = pedido.get('subtotal') if pedido.get('subtotal') is not None else 0.0
    desc = pedido.get('descuento') if pedido.get('descuento') is not None else 0.0
    tot = pedido.get('total') if pedido.get('total') is not None else 0.0

    elements.append(Spacer(1, 15))
    elements.append(Paragraph(f"<b>SUBTOTAL: ${sub:.2f}</b>", styles['Normal']))
    elements.append(Paragraph(f"<b>DESCUENTO APLICADO: ${desc:.2f}</b>", styles['Normal']))
    elements.append(Paragraph(f"<b>TOTAL A PAGAR: ${tot:.2f}</b>", styles['Normal']))
    doc.build(elements)
    return buffer.getvalue()

# --- FUNCIONES AUXILIARES ---
def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        if clean.count('.') > 1:
            parts = clean.split('.')
            clean = "".join(parts[:-1]) + "." + parts[-1]
        return float(clean)
    except: return 0.0

@st.cache_data(ttl=60)
def cargar_catalogo():
    return pd.read_sql("SELECT * FROM productos", get_connection())

@st.fragment
def card_producto(row, idx):
    with st.container(border=True):
        if row['foto_path'] and os.path.exists(row['foto_path']):
            st.image(row['foto_path'], use_container_width=True)
        else:
            st.image("https://via.placeholder.com/150?text=Color+Insumos", use_container_width=True)
        st.subheader(f"$ {row['precio']:.2f}")
        st.write(f"**{row['sku']}**")
        st.caption(row['descripcion'][:80])
        cant = st.number_input("Cantidad", 1, 500, 1, key=f"q_{row['sku']}_{idx}")
        if st.button("🛒 Añadir", key=f"btn_{row['sku']}_{idx}", use_container_width=True):
            uid = st.session_state.user_data['user']
            if uid not in st.session_state.carritos: st.session_state.carritos[uid] = {}
            st.session_state.carritos[uid][row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
            st.toast("✅ Añadido")

# --- FLUJO PRINCIPAL ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False
if 'carritos' not in st.session_state: st.session_state.carritos = {}

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Error de acceso")
else:
    user = st.session_state.user_data
    uid = user['user']
    if uid not in st.session_state.carritos: st.session_state.carritos[uid] = {}

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(st.session_state.carritos[uid])})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Clientes"]
        menu = st.radio("Menú", opc)
        if st.button("Salir"): 
            st.session_state.auth = False
            st.rerun()

    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo")
        c1, c2 = st.columns([2, 1])
        busq = c1.text_input("🔍 Buscar SKU o Producto...")
        df_full = cargar_catalogo()
        cat_sel = c2.selectbox("📂 Categoría", ["Todas"] + sorted(list(df_full['categoria'].unique())))
        
        if busq or cat_sel != "Todas":
            df = df_full.copy()
            if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
            if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]
            cols = st.columns(4)
            for i, (_, row) in enumerate(df.iterrows()):
                with cols[i % 4]: card_producto(row, i)

    elif "🛒" in menu:
        st.title("🛒 Carrito de Compras")
        carrito = st.session_state.carritos[uid]
        if not carrito: st.warning("Carrito vacío")
        else:
            total_b = 0
            items_p = []
            for sku, info in list(carrito.items()):
                monto = info['p'] * info['c']
                total_b += monto
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 0.5])
                    c1.write(f"**{sku}** - {info['desc']}")
                    c2.write(f"{info['c']} x ${info['p']:.2f} = ${monto:.2f}")
                    if c3.button("🗑️", key=f"del_{sku}"):
                        del st.session_state.carritos[uid][sku]; st.rerun()
                items_p.append({"sku": sku, "desc": info['desc'], "cant": info['c'], "precio": info['p']})

            st.divider()
            # --- NUEVA LÓGICA DE DESCUENTOS ---
            metodo = st.radio("Método de Pago", ["Transferencia BS / $ BCV", "Zelle / Divisas (Efectivo)"])
            
            porcentaje_desc = 0.0
            if "Zelle" in metodo:
                porcentaje_desc = 0.30  # 30% Fijo
            else:
                if total_b > 100:
                    porcentaje_desc = 0.10  # 10% si > $100
            
            monto_descuento = total_b * porcentaje_desc
            total_n = total_b - monto_descuento
            
            c1, c2 = st.columns(2)
            c1.metric("Subtotal", f"${total_b:.2f}")
            c2.metric("Descuento Aplicado", f"-${monto_descuento:.2f} ({porcentaje_desc*100:.0f}%)", delta_color="normal")
            st.write(f"### Total Final: ${total_n:.2f}")

            if st.button("Confirmar Pedido ✅", type="primary", use_container_width=True):
                get_connection().execute(
                    "INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(items_p), metodo, total_b, monto_descuento, total_n, "Pendiente")
                )
                get_connection().commit()
                st.session_state.carritos[uid] = {}; st.success("Pedido enviado!"); time.sleep(1); st.rerun()

    elif "Pedidos" in menu or "Ventas" in menu:
        st.title("📜 Historial de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{uid}' ORDER BY id DESC"
        df_p = pd.read_sql(query, get_connection())
        
        for _, p in df_p.iterrows():
            info_cli = get_connection().execute("SELECT telefono, direccion FROM usuarios WHERE username=?", (p['username'],)).fetchone()
            with st.expander(f"Pedido #{p['id']} - {p.get('cliente_nombre','Cliente')} | {p['fecha']} | ${p['total']:.2f}"):
                c1, c2 = st.columns([2, 1])
                with c1: st.table(pd.DataFrame(json.loads(p['items'])))
                with c2:
                    st.info(f"**Estado:** {p['status']}\n\n**Pago:** {p.get('metodo_pago')}")
                    pdf = generar_pdf_recibo(p, info_cli)
                    st.download_button("📥 PDF Recibo", pdf, f"Recibo_{p['id']}.pdf", "application/pdf", key=f"p_{p['id']}")
                    
                    ex_buf = io.BytesIO()
                    pd.DataFrame(json.loads(p['items'])).to_excel(ex_buf, index=False)
                    st.download_button("📊 Excel", ex_buf.getvalue(), f"Pedido_{p['id']}.xlsx", key=f"x_{p['id']}")
                
                if user['rol'] == 'admin':
                    nst = st.selectbox("Estatus", ["Pendiente", "Pagado", "Enviado"], key=f"s_{p['id']}")
                    if st.button("Actualizar", key=f"b_{p['id']}"):
                        get_connection().execute("UPDATE pedidos SET status=? WHERE id=?", (nst, p['id']))
                        get_connection().commit(); st.rerun()

    elif menu == "📁 Cargar PDF":
        st.title("📁 Importar Inventario")
        f = st.file_uploader("PDF Pointer", type="pdf")
        if f and st.button("Procesar"):
            with st.spinner("Cargando..."):
                with open("temp.pdf", "wb") as file: file.write(f.getbuffer())
                doc = fitz.open("temp.pdf")
                conn = get_connection()
                for page in doc:
                    tabs = page.find_tables()
                    if tabs:
                        for tab in tabs:
                            for row in tab.to_pandas().itertuples():
                                try:
                                    sku, desc, prec = str(row[1]), str(row[3]), limpiar_precio(row[5])
                                    if len(sku) > 2:
                                        conn.execute("INSERT INTO productos (sku, descripcion, precio, categoria) VALUES (?,?,?,?) ON CONFLICT(sku) DO UPDATE SET precio=excluded.precio", (sku, desc, prec, "General"))
                                except: pass
                conn.commit(); st.success("Actualizado"); st.rerun()

    elif menu == "👥 Clientes":
        st.title("👥 Gestión de Clientes")
        
        # Formulario para registro nuevo
        with st.expander("➕ Registrar Nuevo Cliente"):
            with st.form("reg_nuevo"):
                u_n, p_n, n_n, t_n = st.text_input("Usuario (Email)"), st.text_input("Clave"), st.text_input("Nombre"), st.text_input("Tlf")
                d_n = st.text_area("Dirección")
                if st.form_submit_button("Guardar"):
                    get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (u_n, p_n, n_n, 'cliente', d_n, t_n))
                    get_connection().commit(); st.success("Cliente registrado"); st.rerun()
        
        st.divider()
        st.subheader("Lista de Clientes Registrados")
        df_clientes = pd.read_sql("SELECT * FROM usuarios WHERE rol='cliente'", get_connection())
        
        for _, cli in df_clientes.iterrows():
            with st.expander(f"👤 {cli['nombre']} ({cli['username']})"):
                with st.form(key=f"edit_{cli['username']}"):
                    c1, c2 = st.columns(2)
                    edit_nom = c1.text_input("Nombre", value=cli['nombre'])
                    edit_pass = c2.text_input("Clave", value=cli['password'])
                    edit_tlf = c1.text_input("Teléfono", value=cli['telefono'])
                    edit_dir = st.text_area("Dirección", value=cli['direccion'])
                    
                    col_b1, col_b2 = st.columns(2)
                    if col_b1.form_submit_button("💾 Guardar Cambios"):
                        get_connection().execute(
                            "UPDATE usuarios SET nombre=?, password=?, telefono=?, direccion=? WHERE username=?",
                            (edit_nom, edit_pass, edit_tlf, edit_dir, cli['username'])
                        )
                        get_connection().commit()
                        st.success("Actualizado")
                        st.rerun()
                    
                    if col_b2.form_submit_button("🗑️ Eliminar Cliente"):
                        get_connection().execute("DELETE FROM usuarios WHERE username=?", (cli['username'],))
                        get_connection().commit()
                        st.warning("Cliente eliminado")
                        st.rerun()