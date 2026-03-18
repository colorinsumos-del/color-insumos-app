import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import time
import re
from datetime import datetime
from fpdf import FPDF

# --- CONFIGURACIÓN ---
DB_NAME = "color_premium_v15.db" # Nueva versión para limpieza total
st.set_page_config(page_title="Color Insumos - Catálogo", layout="wide")

# --- ESTILOS CSS PARA CUADROS VISTOSOS ---
st.markdown("""
    <style>
    .product-card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 15px;
        border: 1px solid #e0e0e0;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.05);
        text-align: center;
        margin-bottom: 20px;
        height: 100%;
    }
    .product-title {
        font-size: 16px;
        font-weight: bold;
        color: #333;
        margin-bottom: 10px;
        height: 40px;
        overflow: hidden;
    }
    .price-tag {
        font-size: 20px;
        color: #2e7d32;
        font-weight: bold;
    }
    .sku-tag {
        font-size: 12px;
        color: #757575;
    }
    </style>
    """, unsafe_allow_html=True)

# --- MOTOR DE DATOS ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    # Productos: SKU es la clave, Descripcion es el nombre
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio_divisa REAL, precio_bcv REAL, categoria TEXT)''')
    # Usuarios con datos extendidos
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT)''')
    # Pedidos
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, items TEXT, total REAL, descuento REAL, neto REAL)''')
    # Carrito persistente en DB
    conn.execute('''CREATE TABLE IF NOT EXISTS carrito 
                 (username TEXT, sku TEXT, nombre TEXT, precio_bcv REAL, cantidad INTEGER, PRIMARY KEY(username, sku))''')
    
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Color', 'admin'))
    conn.commit()

# --- PROCESADOR EXCEL ---
def procesar_excel(file):
    try:
        df = pd.read_excel(file)
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        c_sku = next((c for c in df.columns if any(x in c for x in ["SKU", "COD"])), None)
        c_desc = next((c for c in df.columns if any(x in c for x in ["DESC", "PROD", "NOMBRE"])), None)
        c_div = next((c for c in df.columns if any(x in c for x in ["DIVISA", "USD", "$"])), None)
        c_bcv = next((c for c in df.columns if "BCV" in c), None)

        if not c_sku or not c_desc: return "Error: Faltan columnas SKU o Nombre."

        conn = get_connection()
        for _, row in df.iterrows():
            sku = str(row[c_sku]).strip()
            if not sku or sku.lower() == "nan": continue
            
            p_div = float(row[c_div]) if c_div and pd.notna(row[c_div]) else 0.0
            p_bcv = float(row[c_bcv]) if c_bcv and pd.notna(row[c_bcv]) else 0.0
            
            conn.execute("""INSERT INTO productos (sku, descripcion, precio_divisa, precio_bcv, categoria) 
                         VALUES (?,?,?,?,'General') ON CONFLICT(sku) DO UPDATE SET 
                         descripcion=excluded.descripcion, precio_divisa=excluded.precio_divisa, precio_bcv=excluded.precio_bcv""",
                         (sku, str(row[c_desc]), p_div, p_bcv))
        conn.commit()
        return True
    except Exception as e: return str(e)

# --- GENERADOR PDF ---
def generar_pdf(pedido_id, fecha, cliente, items, subtotal, desc, neto):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(190, 10, "COLOR INSUMOS - ORDEN DE COMPRA", ln=True, align='C')
    pdf.set_font("Arial", "", 10)
    pdf.cell(190, 7, f"Pedido: #{pedido_id} | Fecha: {fecha}", ln=True, align='C')
    pdf.cell(190, 7, f"Cliente: {cliente}", ln=True, align='C')
    pdf.ln(10)
    # Tabla
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(120, 10, "Producto", 1, 0, 'C', True)
    pdf.cell(20, 10, "Cant", 1, 0, 'C', True)
    pdf.cell(50, 10, "Total BCV", 1, 1, 'C', True)
    for i in items:
        pdf.cell(120, 8, str(i['nombre'])[:50], 1)
        pdf.cell(20, 8, str(i['cantidad']), 1, 0, 'C')
        pdf.cell(50, 8, f"{i['subtotal']:.2f} Bs", 1, 1, 'R')
    pdf.ln(5)
    pdf.cell(140, 8, "Subtotal:", 0, 0, 'R')
    pdf.cell(50, 8, f"{subtotal:.2f} Bs", 0, 1, 'R')
    pdf.cell(140, 8, f"Descuento Aplicado:", 0, 0, 'R')
    pdf.cell(50, 8, f"-{desc:.2f} Bs", 0, 1, 'R')
    pdf.set_font("Arial", "B", 12)
    pdf.cell(140, 10, "TOTAL A PAGAR:", 0, 0, 'R')
    pdf.cell(50, 10, f"{neto:.2f} Bs", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1')

# --- INTERFAZ DE USUARIO ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ Sistema Color Insumos")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=?", (u.strip(),)).fetchone()
        if res and res[1] == p:
            st.session_state.auth, st.session_state.user = True, {"id": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Error de acceso")
else:
    user = st.session_state.user
    menu = st.sidebar.radio("Menú", ["🛒 Tienda", "🧾 Mi Carrito", "📊 Pedidos", "👥 Clientes", "📁 Cargar Excel"])

    if menu == "🛒 Tienda":
        st.title("🛍️ Catálogo de Productos")
        busqueda = st.text_input("🔍 Buscar por nombre o SKU...")
        prods = pd.read_sql("SELECT * FROM productos", get_connection())
        if busqueda:
            prods = prods[prods['descripcion'].str.contains(busqueda, case=False) | prods['sku'].str.contains(busqueda, case=False)]
        
        cols = st.columns(4)
        for idx, row in prods.iterrows():
            with cols[idx % 4]:
                st.markdown(f"""
                <div class="product-card">
                    <div class="sku-tag">SKU: {row['sku']}</div>
                    <div class="product-title">{row['descripcion']}</div>
                    <div class="price-tag">{row['precio_bcv']:.2f} Bs.</div>
                </div>
                """, unsafe_allow_html=True)
                cant = st.number_input("Cantidad", 1, 100, 1, key=f"q_{row['sku']}")
                if st.button("Añadir 🛒", key=f"b_{row['sku']}", use_container_width=True):
                    get_connection().execute("INSERT OR REPLACE INTO carrito VALUES (?,?,?,?,?)",
                                            (user['id'], row['sku'], row['descripcion'], row['precio_bcv'], cant))
                    get_connection().commit()
                    st.toast("Añadido al carrito")

    elif menu == "🧾 Mi Carrito":
        st.title("🧾 Tu Pedido")
        items = pd.read_sql("SELECT * FROM carrito WHERE username=?", get_connection(), params=(user['id'],))
        if items.empty: st.info("El carrito está vacío.")
        else:
            subtotal = 0
            resumen = []
            for _, item in items.iterrows():
                sub = item['precio_bcv'] * item['cantidad']
                subtotal += sub
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.write(f"**{item['nombre']}**")
                nueva_cant = c2.number_input("Cant.", 1, 500, int(item['cantidad']), key=f"edit_{item['sku']}")
                if c3.button("🗑️", key=f"del_{item['sku']}"):
                    get_connection().execute("DELETE FROM carrito WHERE username=? AND sku=?", (user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
                
                if nueva_cant != item['cantidad']:
                    get_connection().execute("UPDATE carrito SET cantidad=? WHERE username=? AND sku=?", (nueva_cant, user['id'], item['sku']))
                    get_connection().commit(); st.rerun()
                
                resumen.append({"sku": item['sku'], "nombre": item['nombre'], "cantidad": nueva_cant, "subtotal": sub})

            # REGLA DE DESCUENTO: 10% si supera los 5000 Bs (ejemplo)
            descuento = subtotal * 0.10 if subtotal > 5000 else 0
            neto = subtotal - descuento

            st.divider()
            st.write(f"Subtotal: {subtotal:.2f} Bs.")
            if descuento > 0: st.success(f"🎁 ¡Descuento del 10% aplicado!: -{descuento:.2f} Bs.")
            st.write(f"### TOTAL A PAGAR: {neto:.2f} Bs.")

            if st.button("🚀 Confirmar y Enviar Pedido", type="primary", use_container_width=True):
                conn = get_connection()
                conn.execute("INSERT INTO pedidos (username, fecha, items, total, descuento, neto) VALUES (?,?,?,?,?,?)",
                             (user['id'], datetime.now().strftime("%d/%m/%Y %H:%M"), json.dumps(resumen), subtotal, descuento, neto))
                conn.execute("DELETE FROM carrito WHERE username=?", (user['id'],))
                conn.commit(); st.success("¡Pedido realizado!"); time.sleep(1); st.rerun()

    elif menu == "📊 Pedidos":
        st.title("📊 Gestión de Pedidos")
        query = "SELECT * FROM pedidos ORDER BY id DESC" if user['rol'] == 'admin' else f"SELECT * FROM pedidos WHERE username='{user['id']}'"
        peds = pd.read_sql(query, get_connection())
        for _, p in peds.iterrows():
            with st.expander(f"📦 Pedido #{p['id']} - {p['fecha']} ({p['neto']:.2f} Bs.)"):
                items_p = json.loads(p['items'])
                st.table(pd.DataFrame(items_p))
                pdf_data = generar_pdf(p['id'], p['fecha'], p['username'], items_p, p['total'], p['descuento'], p['neto'])
                st.download_button("Descargar PDF", pdf_data, f"Pedido_{p['id']}.pdf", key=f"pdf_{p['id']}")

    elif menu == "👥 Clientes" and user['rol'] == 'admin':
        st.title("👥 Gestión de Clientes")
        # Registro
        with st.form("nuevo_cliente"):
            st.write("Registrar Nuevo Cliente")
            c1, c2 = st.columns(2)
            nu = c1.text_input("Usuario (Email)"); np = c2.text_input("Clave")
            nn = c1.text_input("Nombre Empresa"); nt = c2.text_input("Teléfono")
            nd = st.text_area("Dirección")
            if st.form_submit_button("Guardar"):
                get_connection().execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (nu, np, nn, 'cliente', nd, nt))
                get_connection().commit(); st.success("Cliente Creado")
        
        # Lista y Edición
        st.divider()
        clis = pd.read_sql("SELECT * FROM usuarios WHERE rol='cliente'", get_connection())
        for _, c in clis.iterrows():
            with st.expander(f"🏢 {c['nombre']}"):
                st.write(f"Usuario: {c['username']} | Tel: {c['telefono']}")
                if st.button("Eliminar Cliente", key=f"delc_{c['username']}"):
                    get_connection().execute("DELETE FROM usuarios WHERE username=?", (c['username'],))
                    get_connection().commit(); st.rerun()

    elif menu == "📁 Cargar Excel" and user['rol'] == 'admin':
        st.title("📁 Cargar Inventario")
        file = st.file_uploader("Sube el archivo Excel", type=["xlsx"])
        if file and st.button("Procesar"):
            res = procesar_excel(file)
            if res is True: st.success("Catálogo Actualizado"); st.rerun()
            else: st.error(res)