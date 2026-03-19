import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import re
import io
from datetime import datetime
from PIL import Image

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
    # Tabla de Productos
    conn.execute('''CREATE TABLE IF NOT EXISTS productos 
                 (sku TEXT PRIMARY KEY, descripcion TEXT, precio REAL, categoria TEXT, foto_path TEXT)''')
    # Tabla de Usuarios Completa
    conn.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (username TEXT PRIMARY KEY, password TEXT, nombre TEXT, rol TEXT, direccion TEXT, telefono TEXT, 
                  rif TEXT, ciudad TEXT, notas TEXT)''')
    # Tabla de Pedidos
    conn.execute('''CREATE TABLE IF NOT EXISTS pedidos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, cliente_nombre TEXT, fecha TEXT, 
                  items TEXT, metodo_pago TEXT, subtotal REAL, descuento REAL, total REAL, status TEXT)''')
    # Tabla de Carritos persistentes
    conn.execute('''CREATE TABLE IF NOT EXISTS carritos 
                 (username TEXT PRIMARY KEY, data TEXT)''')
    
    # Usuario Administrador por defecto
    conn.execute("INSERT OR IGNORE INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                 ('colorinsumos@gmail.com', '20880157', 'Admin Maestro', 'admin'))
    conn.commit()

def limpiar_precio(texto):
    if not texto or str(texto).lower() == "none": return 0.0
    # Elimina cualquier cosa que no sea número, punto o coma
    clean = re.sub(r'[^\d,.]', '', str(texto)).replace(',', '.')
    try:
        return float(clean)
    except:
        return 0.0

def guardar_carrito_db(username, carrito_dict):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO carritos (username, data) VALUES (?, ?)", (username, json.dumps(carrito_dict)))
    conn.commit()

def cargar_carrito_db(username):
    conn = get_connection()
    res = conn.execute("SELECT data FROM carritos WHERE username=?", (username,)).fetchone()
    return json.loads(res[0]) if res else {}

# --- AUTENTICACIÓN ---
init_db()
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Color Insumos")
    u = st.text_input("Usuario (Email)")
    p = st.text_input("Contraseña", type="password")
    if st.button("Entrar", type="primary"):
        res = get_connection().execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, p)).fetchone()
        if res:
            st.session_state.auth = True
            st.session_state.user_data = {"user": res[0], "nombre": res[2], "rol": res[3]}
            st.rerun()
        else: st.error("Credenciales incorrectas")
else:
    user = st.session_state.user_data
    uid = user['user']
    carrito_usuario = cargar_carrito_db(uid)

    # Sidebar de Navegación
    with st.sidebar:
        st.header(f"👤 {user['nombre']}")
        st.write(f"Rol: {user['rol'].upper()}")
        st.divider()
        opc = ["🛍️ Tienda", f"🛒 Carrito ({len(carrito_usuario)})", "📜 Mis Pedidos"]
        if user['rol'] == 'admin': 
            opc += ["📊 Gestión Ventas", "📁 Cargar Inventario", "👥 Usuarios"]
        
        menu = st.radio("Ir a:", opc)
        if st.button("Cerrar Sesión"): 
            st.session_state.auth = False
            st.rerun()

    # --- MÓDULO 1: TIENDA ---
    if menu == "🛍️ Tienda":
        st.title("🛍️ Catálogo de Productos")
        conn = get_connection()
        df = pd.read_sql("SELECT * FROM productos", conn)
        
        if df.empty:
            st.warning("No hay productos cargados. Contacte al administrador.")
        else:
            busq = st.text_input("🔍 Buscar por SKU o Descripción...")
            if busq:
                df = df[df['descripcion'].str.contains(busq, case=False, na=False) | 
                        df['sku'].str.contains(busq, case=False, na=False)]

            for i, row in df.iterrows():
                item_carrito = carrito_usuario.get(row['sku'])
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([1, 4, 1.5, 1])
                    with c1:
                        if row['foto_path'] and os.path.exists(row['foto_path']):
                            st.image(row['foto_path'], width=100)
                        else:
                            st.image("https://via.placeholder.com/100?text=Color+Insumos", width=100)
                    
                    c2.subheader(row['sku'])
                    c2.write(row['descripcion'])
                    c3.metric("Precio", f"${row['precio']:.2f}")
                    
                    cant = c4.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                    if c4.button("🛒 Añadir", key=f"add_{row['sku']}", use_container_width=True):
                        carrito_usuario[row['sku']] = {"desc": row['descripcion'], "p": row['precio'], "c": cant}
                        guardar_carrito_db(uid, carrito_usuario)
                        st.toast(f"Añadido: {row['sku']}")
                        st.rerun()

    # --- MÓDULO 2: CARGA EXCEL (EL QUE NECESITAS) ---
    elif menu == "📁 Cargar Inventario":
        st.title("📁 Importar desde Excel")
        st.write("Sube tu archivo .xlsx. El sistema buscará: Col A(SKU), Col C(Desc), Col D(Precio).")
        
        f = st.file_uploader("Seleccionar archivo Excel", type=["xlsx"])
        
        if f and st.button("🚀 Procesar y Actualizar Catálogo"):
            try:
                df_excel = pd.read_excel(f)
                conn = get_connection()
                exito = 0
                
                for _, row in df_excel.iterrows():
                    try:
                        # Extraemos datos por posición (iloc) para ignorar nombres de cabecera cambiantes
                        sku = str(row.iloc[0]).strip().replace('\n', '')
                        desc = str(row.iloc[2]).strip().replace('\n', ' ')
                        precio = limpiar_precio(row.iloc[3])
                        
                        if len(sku) > 2 and precio > 0:
                            conn.execute("""
                                INSERT INTO productos (sku, descripcion, precio, categoria, foto_path) 
                                VALUES (?,?,?,?,?) ON CONFLICT(sku) 
                                DO UPDATE SET precio=excluded.precio, descripcion=excluded.descripcion
                            """, (sku, desc, precio, "General", ""))
                            exito += 1
                    except: continue
                
                conn.commit()
                st.success(f"✅ Se han cargado/actualizado {exito} productos correctamente.")
                st.balloons()
            except Exception as e:
                st.error(f"Error crítico al leer el archivo: {e}")

    # --- MÓDULO 3: CARRITO Y CIERRE DE PEDIDO ---
    elif "Carrito" in menu:
        st.title("🛒 Mi Carrito de Compras")
        if not carrito_usuario:
            st.info("Tu carrito está vacío.")
        else:
            total = 0
            for s, i in list(carrito_usuario.items()):
                sub = i['p'] * i['c']
                total += sub
                with st.expander(f"{s} - {i['desc']} (x{i['c']})"):
                    st.write(f"Precio Unitario: ${i['p']:.2f} | Subtotal: ${sub:.2f}")
                    if st.button("❌ Eliminar", key=f"del_{s}"):
                        del carrito_usuario[s]
                        guardar_carrito_db(uid, carrito_usuario)
                        st.rerun()
            
            st.divider()
            st.subheader(f"Total a Pagar: ${total:.2f}")
            
            metodo = st.selectbox("Método de Pago", ["Transferencia BCV", "Zelle", "Efectivo"])
            if st.button("✅ Confirmar Pedido", type="primary"):
                fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
                conn = get_connection()
                conn.execute("""INSERT INTO pedidos (username, cliente_nombre, fecha, items, metodo_pago, total, status) 
                             VALUES (?,?,?,?,?,?,?)""", 
                             (uid, user['nombre'], fecha, json.dumps(carrito_usuario), metodo, total, "Pendiente"))
                conn.commit()
                guardar_carrito_db(uid, {}) # Limpiar carrito
                st.success("¡Pedido enviado con éxito!")
                st.rerun()

    # --- MÓDULO 4: GESTIÓN DE USUARIOS ---
    elif menu == "👥 Usuarios":
        st.title("👥 Gestión de Usuarios y Clientes")
        conn = get_connection()
        
        with st.form("nuevo_u"):
            st.subheader("Registrar Nuevo Usuario/Cliente")
            c1, c2 = st.columns(2)
            new_u = c1.text_input("Correo/Login")
            new_p = c2.text_input("Contraseña")
            new_n = c1.text_input("Nombre Completo")
            new_r = c2.selectbox("Rol", ["cliente", "admin"])
            if st.form_submit_button("Crear Usuario"):
                conn.execute("INSERT INTO usuarios (username, password, nombre, rol) VALUES (?,?,?,?)", 
                             (new_u, new_p, new_n, new_r))
                conn.commit()
                st.success("Usuario creado")
                st.rerun()

        st.divider()
        df_u = pd.read_sql("SELECT username, nombre, rol, telefono, ciudad FROM usuarios", conn)
        st.dataframe(df_u, use_container_width=True)

    # --- MÓDULO 5: HISTORIAL DE VENTAS ---
    elif menu == "📊 Gestión Ventas":
        st.title("📊 Control de Pedidos")
        df_p = pd.read_sql("SELECT * FROM pedidos ORDER BY id DESC", get_connection())
        
        for _, p in df_p.iterrows():
            with st.expander(f"Pedido #{p['id']} - {p['cliente_nombre']} (${p['total']:.2f})"):
                st.write(f"Fecha: {p['fecha']} | Pago: {p['metodo_pago']} | Estado: {p['status']}")
                st.table(pd.DataFrame(json.loads(p['items'])).T)
                if st.button("Marcar como Pagado/Entregado", key=f"done_{p['id']}"):
                    get_connection().execute("UPDATE pedidos SET status='Completado' WHERE id=?", (p['id'],))
                    get_connection().commit()
                    st.rerun()