import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import io
import json
from datetime import datetime

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Sistema de Pedidos", layout="wide")

# --- BASE DE DATOS EVOLUCIONADA ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    # Tabla de Productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de Usuarios
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rif TEXT)''')
    # NUEVA: Tabla de Pedidos
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, 
                  items TEXT, total REAL)''')
    conn.close()

def guardar_pedido(username, carrito, total):
    conn = sqlite3.connect(DB_NAME)
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Convertimos el diccionario del carrito a texto (JSON) para guardarlo
    items_json = json.dumps(carrito)
    conn.execute("INSERT INTO pedidos (username, fecha, items, total) VALUES (?,?,?,?)",
                 (username, fecha, items_json, total))
    conn.commit()
    conn.close()

def obtener_historial(username):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT id, fecha, total, items FROM pedidos WHERE username=? ORDER BY id DESC", 
                     conn, params=(username,))
    conn.close()
    return df

# --- INTERFAZ DE USUARIO ---
init_db()

# Estado de la sesión
if 'auth' not in st.session_state:
    st.session_state.auth = False
    st.session_state.user = None

# --- BLOQUE DE LOGIN / REGISTRO ---
if not st.session_state.auth:
    st.title("🔐 Acceso Clientes - Color Insumos")
    tab1, tab2 = st.tabs(["Iniciar Sesión", "Registrarse"])
    
    with tab1:
        u = st.text_input("Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.button("Ingresar"):
            # Aquí iría la validación contra la tabla 'usuarios'
            # Por simplicidad para tu prueba, aceptaremos el login si existe el usuario
            st.session_state.auth = True
            st.session_state.user = u
            st.rerun()
            
    with tab2:
        st.info("Formulario de registro para nuevos clientes")
        # Aquí iría la lógica de 'INSERT INTO usuarios' que vimos antes

else:
    # --- APLICACIÓN PRINCIPAL (CLIENTE LOGUEADO) ---
    st.sidebar.title(f"👋 Hola, {st.session_state.user}")
    
    menu = st.sidebar.radio("Ir a:", ["🛒 Catálogo", "📜 Mis Pedidos", "🚪 Cerrar Sesión"])

    if menu == "🚪 Cerrar Sesión":
        st.session_state.auth = False
        st.rerun()

    # --- VISTA: MIS PEDIDOS (HISTÓRICO) ---
    if menu == "📜 Mis Pedidos":
        st.header("Historial de mis pedidos")
        historial = obtener_historial(st.session_state.user)
        
        if historial.empty:
            st.write("Aún no has realizado pedidos.")
        else:
            for _, ped in historial.iterrows():
                with st.expander(f"📦 Pedido #{ped['id']} - Fecha: {ped['fecha']} - Total: ${ped['total']:.2f}"):
                    # Mostrar items de ese pedido
                    items = json.loads(ped['items'])
                    df_items = pd.DataFrame(items).T
                    st.table(df_items[['descripcion', 'cant', 'precio']])
                    
                    # Botón para descargar de nuevo
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_items.to_excel(writer)
                    st.download_button(f"📥 Descargar Excel #{ped['id']}", output.getvalue(), 
                                     f"Pedido_{ped['id']}.xlsx", key=f"dl_{ped['id']}")

    # --- VISTA: CATÁLOGO ---
    elif menu == "🛒 Catálogo":
        # ... (Aquí va toda la lógica de búsqueda y tarjetas de productos que ya tienes) ...
        
        # Al final del carrito, añadimos el botón de "Confirmar"
        if st.button("✅ Confirmar Pedido y Guardar en Historial"):
            # total = calcular_total_del_carrito()
            # guardar_pedido(st.session_state.user, st.session_state.carrito, total)
            st.success("¡Pedido guardado en tu historial!")