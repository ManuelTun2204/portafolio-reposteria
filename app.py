import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

# Configuración de la página
st.set_page_config(
    page_title="Portafolio de Repostería",
    page_icon="🍰",
    layout="wide"
)

st.title("🍰 Portafolio de Repostería Profesional")
st.markdown("---")

# Sección de presentación
st.header("Bienvenido")
st.image("https://static.streamlit.io/examples/streamlit_logo.png", width=200)

st.markdown("""
Este portafolio muestra mis proyectos de repostería profesional, 
incluyendo recetas, posters y portafolio de imágenes fotográficas de productos.
""")

# Sección de recetas
st.sidebar.header("Recetas")
recetas = st.sidebar.multiselect(
    "Selecciona una receta",
    ["Pastel de chocolate", "Croissant", "Pan de masa madre", "Macarons"],
    default=["Pastel de chocolate"]
)

st.sidebar.markdown("### Receta seleccionada")
for receta in recetas:
    st.sidebar.info(f"Mostrando: {receta}")

# Placeholder para datos
st.header("Datos del Portafolio")
st.markdown("*(Datos cargarán cuando estén disponibles)*")

# Gráfico de ejemplo
df = pd.DataFrame({
    "producto": ["Pastel", "Croissant", "Pan", "Macarons"],
    "ventas": [150, 80, 120, 60]
})

fig = px.bar(df, x="producto", y="ventas", title="Ventas por Producto")
st.plotly_chart(fig, use_container_width=True)

# Footer
st.markdown("---")
st.markdown("Desarrollado con Streamlit + Python")