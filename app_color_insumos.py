import streamlit as st
import pandas as pd
import sqlite3
import os
import json
import time
from datetime import datetime

# --- CONFIGURACIÓN ---
DB_NAME = "catalogo_color_v2.db"
IMG_DIR = "static/fotos"

st.set_page_config(page_title="Color Insumos - Alto Rendimiento", layout="wide")

# --- MOTOR DE PERSISTENCIA Y VELOCIDAD ---
def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

@st.cache_data(ttl=3600) # El catálogo se guarda en RAM por 1 hora
def obtener_catalogo_optimizado():
    conn = get_connection()
    # Traemos solo lo necesario para la vista rápida
    return pd.read_sql("SELECT sku, descripcion, precio, categoria, foto_path FROM productos", conn)

def sincronizar_ahora():
    """Limpia la memoria caché para forzar la lectura de nuevos datos"""
    st.cache_data.clear()
    st.toast("🔄 Catálogo sincronizado y actualizado")
    time.sleep(0.5)

# --- INTERFAZ DE ESTILOS ---
st.markdown("""
    <style>
        .stSelectbox div[data-baseweb="select"] { background-color: #f0f2f6; }
        .product-card { border: 1px solid #ddd; padding: 10px; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- LÓGICA DE SESIÓN ---
if 'carrito' not in st.session_state: st.session_state.carrito = {}
if 'auth' not in st.session_state: st.session_state.auth = False

# (Omitimos init_db y login por brevedad, se mantienen igual a la versión anterior)

if st.session_state.auth:
    user = st.session_state.user_data
    
    # --- BARRA LATERAL CON BOTÓN DE SINCRONIZACIÓN ---
    with st.sidebar:
        st.title("Color Insumos")
        st.write(f"Hola, **{user['nombre']}**")
        
        # BOTÓN DE SINCRONIZACIÓN (ACELERADOR)
        if st.button("🔄 Sincronizar Catálogo", use_container_width=True):
            sincronizar_ahora()
            st.rerun()
            
        st.divider()
        num_items = len(st.session_state.carrito)
        menu = st.radio("Navegación", [f"🛒 Comprar ({num_items})", "📜 Mis Pedidos"])

    if "Comprar" in menu:
        st.title("🛒 Catálogo Inteligente")
        
        # --- BARRA DE BÚSQUEDA MEJORADA ---
        col_search, col_cat = st.columns([2, 1])
        
        with col_search:
            query = st.text_input("🔍 ¿Qué estás buscando?", placeholder="Escribe SKU o nombre del producto...")
            
        # Obtenemos datos de la caché (Instantáneo)
        df_completo = obtener_catalogo_optimizado()
        categorias_disponibles = ["Todas las Categorías"] + sorted(df_completo['categoria'].unique().tolist())
        
        with col_cat:
            cat_filter = st.selectbox("📁 Filtrar por Categoría", categorias_disponibles)

        # --- FILTRADO EN MEMORIA (MUCHO MÁS RÁPIDO QUE SQL) ---
        df_filtrado = df_completo.copy()
        if query:
            df_filtrado = df_filtrado[
                df_filtrado['descripcion'].str.contains(query, case=False) | 
                df_filtrado['sku'].str.contains(query, case=False)
            ]
        if cat_filter != "Todas las Categorías":
            df_filtrado = df_filtrado[df_filtrado['categoria'] == cat_filter]

        # --- MOSTRAR RESULTADOS ---
        if df_filtrado.empty:
            st.warning("No se encontraron productos con esos filtros.")
        else:
            # Dividimos por categorías automáticamente
            for categoria in df_filtrado['categoria'].unique():
                st.subheader(f"📍 {categoria}")
                items_cat = df_filtrado[df_filtrado['categoria'] == categoria]
                
                # Sistema de cuadrícula dinámica
                cols = st.columns(4)
                for idx, row in items_cat.reset_index().iterrows():
                    with cols[idx % 4]:
                        with st.container(border=True):
                            if row['foto_path'] and os.path.exists(row['foto_path']):
                                st.image(row['foto_path'], use_container_width=True)
                            st.write(f"**{row['sku']}**")
                            st.caption(row['descripcion'][:50] + "...")
                            st.write(f"### ${row['precio']:.2f}")
                            
                            # Cantidad y botón
                            c_btn1, c_btn2 = st.columns([1, 1])
                            cant = c_btn1.number_input("Cant", 1, 100, 1, key=f"q_{row['sku']}")
                            if c_btn2.button("➕", key=f"b_{row['sku']}", use_container_width=True):
                                st.session_state.carrito[row['sku']] = {
                                    "desc": row['descripcion'], 
                                    "p": row['precio'], 
                                    "c": cant
                                }
                                st.toast(f"Añadido: {row['sku']}")
                                time.sleep(0.3)
                                st.rerun()