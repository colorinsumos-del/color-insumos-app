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
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT, 
                  rif TEXT, ciudad TEXT, notas TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, status TEXT)''')
    
    # --- TABLA PARA CARRITO PERSISTENTE ---
    conn.execute('''CREATE TABLE IF NOT EXISTS carritos 
                 (username TEXT PRIMARY KEY, data TEXT)''')
    
    # --- SISTEMA DE MIGRACIÓN AUTOMÁTICA ---
    cursor = conn.cursor()
    
    # Migración Tabla Pedidos
    cursor.execute("PRAGMA table_info(pedidos)")
    cols_pedidos = [info[1] for info in cursor.fetchall()]
    nuevas_cols_pedidos = {
        "cliente_nombre": "TEXT", "metodo_pago": "TEXT",
        "subtotal": "REAL", "descuento": "REAL"
    }
    for col, tipo in nuevas_cols_pedidos.items():
        if col not in cols_pedidos:
            try: conn.execute(f"ALTER TABLE pedidos ADD COLUMN {col} {tipo}")
            except: pass

    # Migración Tabla Usuarios
    cursor.execute("PRAGMA table_info(usuarios)")
    cols_usuarios = [info[1] for info in cursor.fetchall()]
    nuevas_cols_usuarios = {"rif": "TEXT", "ciudad": "TEXT", "notas": "TEXT"}
    for col, tipo in nuevas_cols_usuarios.items():
        if col not in cols_usuarios:
            try: conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {tipo}")
            except: pass

    # Admin por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol, direccion, telefono) VALUES (?,?,?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin', 'Maracaibo', '04126901346'))
    conn.commit()

# --- FUNCIONES DE PERSISTENCIA DE CARRITO ---
def guardar_carrito_db(username, carrito_dict):
    conn = get_connection()
    data_json = json.dumps(carrito_dict)
    conn.execute("INSERT OR REPLACE INTO carritos (username, data) VALUES (?, ?)", (username, data_json))
    conn.commit()

def cargar_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT data FROM carritos WHERE username=?", (username,)).fetchone()
    return json.loads(res[0]) if res else {}

# --- FUNCIONES DE EXPORTACIÓN ---
def generar_pdf_recibo(pedido, info_cliente):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>COLOR INSUMOS</b>", styles['Title']))
    elements.append(Paragraph("Comprobante de Pedido / Recibo", styles['Normal']))
    elements.append(Spacer(1, 12))

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
    
    sub = pedido.get('subtotal') if pedido.get('subtotal') is not None else 0.0
    desc = pedido.get('descuento') if pedido.get('descuento') is not None else 0.0
    tot = pedido.get('total') if pedido.get('total') is not None else 0.0

    elements.append(Spacer(1, 15))
    elements.append(Paragraph(f"<b>SUBTOTAL: ${sub:.2f}</b>", styles['Normal']))
    elements.append(Paragraph(f"<b>DESCUENTO APLICADO: ${desc:.2f}</b>", styles['Normal']))
    elements.append(Paragraph(f"<b>TOTAL A PAGAR: ${tot:.2f}</b>", styles['Normal']))
    doc.build(elements)
    return buffer.getvalue()

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

# --- FLUJO PRINCIPAL ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

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
    carrito_usuario = cargar_carrito_db(uid)

    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': opc += ["📊 Gestión Ventas", "📁 Cargar PDF", "👥 Clientes"]
        menu = st.radio("Menú", opc)
        if st.button("Salir"): 
            st.session_state.auth = False
            st.rerun()

    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        c1, c2 = st.columns([2, 1])
        busq = c1.text_input("🔍 Buscar SKU o Producto...")
        df_full = cargar_catalogo()
        cat_sel = c2.selectbox("📂 Categoría", ["Todas"] + sorted(list(df_full['categoria'].unique())))
        
        df = df_full.copy()
        if busq: df = df[df['descripcion'].str.contains(busq, case=False) | df['sku'].str.contains(busq, case=False)]
        if cat_sel != "Todas": df = df[df['categoria'] == cat_sel]

        # --- DISEÑO DE LISTA COMPACTA CON INDICADOR ---
        st.divider()
        h1, h2, h3, h4, h5, h6 = st.columns([0.8, 1.2, 4, 1, 1, 1])
        h1.caption("Imagen")
        h2.caption("SKU")
        h3.caption("Descripción")
        h4.caption("Precio")
        h5.caption("Cant.")
        h6.caption("Estado")
        st.divider()

        for i, row in df.iterrows():
            en_carrito = row['sku'] in carrito_usuario
            # Si está en el carrito, usamos un contenedor con borde resaltado
            with st.container(border=en_carrito):
                col1, col2, col3, col4, col5, col6 = st.columns([0.8, 1.2, 4, 1, 1, 1])
                
                with col1:
                    if row['foto_path'] and os.path.exists(row['foto_path']):
                        st.image(row['foto_path'], width=60)
                    else:
                        st.image("https://via.placeholder.com/60?text=📦", width=60)
                
                col2.markdown(f"**{row['sku']}**")
                col3.write(row['descripcion'])
                col4.markdown(f"**${row['precio']:.2f}**")
                
                cant = col5.number_input("n", 1, 500, 1, key=f"q_{row['sku']}_{i}", label_visibility="collapsed")
                
                # Indicador visual en el botón / estado
                if en_carrito:
                    if col6.button("✅ En Carrito", key=f"btn_{row['sku']}_{i}", help="Ya está en tu lista"):
                        st.toast("💡 Ya lo tienes en el carrito")
                else:
                    if col6.button("🛒 Añadir", key=f"btn_{row['sku']}_{i}"):
                        carrito_actual = cargar_carrito_db(uid)
                        carrito_actual[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_actual)
                        st.toast(f"✅ {row['sku']} añadido")
                        time.sleep(0.3)
                        st.rerun()
            st.divider()

    elif "🛒" in menu:
        st.title("🛒 Carrito de Compras")
        if not carrito_usuario: st.warning("Carrito vacío")
        else:
            total_b = 0
            items_p = []
            for sku, info in list(carrito_usuario.items()):
                monto = info['p'] * info['c']
                total_b += monto
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 0.5])
                    c1.write(f"**{sku}** - {info['desc']}")
                    c2.write(f"{info['c']} x ${info['p']:.2f} = ${monto:.2f}")
                    if c3.button("🗑️", key=f"del_{sku}"):
                        del carrito_usuario[sku]
                        guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()
                items_p.append({"sku": sku, "desc": info['desc'], "cant": info['c'], "precio": info['p']})

            st.divider()
            metodo = st.radio("Método de Pago", ["Transferencia BS / $ BCV", "Zelle / Divisas (Efectivo)"])
            porcentaje_desc = 0.30 if "Zelle" in metodo else (0.10 if total_b > 100 else 0.0)
            monto_descuento = total_b * porcentaje_desc
            total_n = total_b - monto_descuento
            
            c1, c2 = st.columns(2)
            c1.metric("Subtotal", f"${total_b:.2f}")
            c2.metric("Descuento Aplicado", f"-${monto_descuento:.2f} ({porcentaje_desc*100:.0f}%)")
            st.write(f"### Total Final: ${total_n:.2f}")

            if st.button("Confirmar Pedido ✅", type="primary", use_container_width=True):
                get_connection().execute(
                    "INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, subtotal, descuento, total, status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, user['nombre'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(items_p), metodo, total_b, monto_descuento, total_n, "Pendiente")
                )
                guardar_carrito_db(uid, {})
                get_connection().commit()
                st.success("Pedido enviado!"); time.sleep(1); st.rerun()

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
        st.title("👥 Gestión Integral de Clientes")
        with st.expander("➕ Registrar Nuevo Cliente / Empresa", expanded=False):
            with st.form("reg_nuevo_completo"):
                c1, c2 = st.columns(2)
                u_n = c1.text_input("Usuario (Email / ID)")
                p_n = c2.text_input("Contraseña de Acceso")
                n_n = c1.text_input("Nombre Completo o Razón Social")
                rif_n = c2.text_input("R.I.F. / Cédula")
                t_n = c1.text_input("Teléfono Principal")
                ciu_n = c2.text_input("Ciudad / Zona")
                d_n = st.text_area("Dirección Fiscal / Despacho")
                not_n = st.text_area("Notas Internas")
                if st.form_submit_button("✅ Registrar Cliente"):
                    if u_n and p_n:
                        get_connection().execute(
                            "INSERT INTO usuarios (username, password, nombre, rol, direccion, telefono, rif, ciudad, notas) VALUES (?,?,?,?,?,?,?,?,?)", 
                            (u_n, p_n, n_n, 'cliente', d_n, t_n, rif_n, ciu_n, not_n)
                        )
                        get_connection().commit(); st.success("Cliente registrado"); st.rerun()
                    else: st.error("Usuario y Contraseña requeridos.")

        st.divider()
        bus_cli = st.text_input("Filtrar por nombre, RIF o ciudad...")
        df_clientes = pd.read_sql("SELECT * FROM usuarios WHERE rol='cliente'", get_connection())
        if bus_cli:
            df_clientes = df_clientes[df_clientes['nombre'].str.contains(bus_cli, case=False, na=False)]

        for _, cli in df_clientes.iterrows():
            with st.expander(f"👤 {cli['nombre']} | {cli['rif']}"):
                with st.form(key=f"edit_full_{cli['username']}"):
                    col1, col2 = st.columns(2)
                    e_nom = col1.text_input("Nombre", value=cli['nombre'])
                    e_rif = col2.text_input("RIF", value=cli.get('rif', ''))
                    e_pass = col1.text_input("Clave", value=cli['password'])
                    e_tlf = col2.text_input("Tlf", value=cli['telefono'])
                    e_ciu = col1.text_input("Ciudad", value=cli.get('ciudad', ''))
                    e_dir = st.text_area("Dirección", value=cli['direccion'])
                    e_not = st.text_area("Notas", value=cli.get('notas', ''))
                    if st.form_submit_button("💾 Guardar"):
                        get_connection().execute(
                            "UPDATE usuarios SET nombre=?, password=?, telefono=?, direccion=?, rif=?, ciudad=?, notas=? WHERE username=?",
                            (e_nom, e_pass, e_tlf, e_dir, e_rif, e_ciu, e_not, cli['username'])
                        )
                        get_connection().commit(); st.success("Actualizado"); st.rerun()