import streamlit as st
import pdfplumber
import fitz
import pandas as pd
import sqlite3
import os
import hashlib
import io

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color.db"
IMG_DIR = "static/fotos"
os.makedirs(IMG_DIR, exist_ok=True)

st.set_page_config(page_title="Color Insumos - Login", layout="wide")

# --- FUNCIONES DE SEGURIDAD Y DB ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    # Tabla de Productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de Usuarios
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rif TEXT)''')
    conn.close()

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def crear_usuario(user, pw, nombre, rif):
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.execute("INSERT INTO usuarios VALUES (?,?,?,?)", (user, hash_password(pw), nombre, rif))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def validar_login(user, pw):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.execute("SELECT nombre FROM usuarios WHERE username=? AND password=?", (user, hash_password(pw)))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# --- LÓGICA DE EXTRACCIÓN (Simplificada para el ejemplo) ---
# [Aquí mantienes tu función procesar_pdf_a_db y obtener_categoria que ya tenemos]

# --- FLUJO DE LA APLICACIÓN ---
init_db()

if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None

# --- PANTALLA DE ACCESO ---
if not st.session_state.autenticado:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🔑 Iniciar Sesión")
        u = st.text_input("Usuario (Correo o RIF)")
        p = st.text_input("Contraseña", type="password")
        if st.button("Entrar"):
            nombre = validar_login(u, p)
            if nombre:
                st.session_state.autenticado = True
                st.session_state.usuario_actual = {"user": u, "nombre": nombre}
                st.rerun()
            else:
                st.error("Credenciales incorrectas")

    with col2:
        st.subheader("📝 Registro de Nuevo Cliente")
        new_u = st.text_input("Crear Usuario")
        new_p = st.text_input("Crear Contraseña", type="password")
        new_n = st.text_input("Nombre o Razón Social")
        new_r = st.text_input("RIF / Cédula")
        if st.button("Registrarme"):
            if crear_usuario(new_u, new_p, new_n, new_r):
                st.success("¡Registro exitoso! Ya puedes iniciar sesión.")
            else:
                st.error("El usuario ya existe.")

# --- PANTALLA DE CATÁLOGO (Solo si está logueado) ---
else:
    st.sidebar.write(f"👤 Bienvenido, **{st.session_state.usuario_actual['nombre']}**")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.autenticado = False
        st.rerun()

    # MODO ADMIN DENTRO DEL SIDEBAR
    with st.sidebar.expander("⚙️ Admin"):
        # ... [Lógica de subir PDF con clave que ya tenías] ...
        pass

    # --- AQUÍ VA EL RESTO DE TU CÓDIGO DE CATÁLOGO ---
    st.title("🛒 Catálogo para Clientes VIP")
    # [Mostrar productos, categorías y carrito...]