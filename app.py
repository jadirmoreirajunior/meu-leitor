import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import shutil
import requests
import pdfplumber  # Biblioteca mais potente para PDF
from io import BytesIO
from PIL import Image
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TRCK
from mutagen.mp3 import MP3

# --- CONFIGURAÇÃO ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://raw.githubusercontent.com/jadirmoreirajunior/meu-leitor/main/narrador.ai.png"

st.set_page_config(page_title=APP_NAME, page_icon="🎧", layout="wide")

# Diretório de trabalho
OUTPUT_DIR = "temp_audio_out"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

VOICES = {
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
}

# --- FUNÇÕES DE EXTRAÇÃO MELHORADAS ---

def extract_text_from_pdf(file):
    text_content = []
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)
        return "\n".join(text_content)
    except Exception as e:
        st.error(f"Erro ao processar PDF: {e}")
        return ""

def extract_text_from_epub(file):
    text = ""
    try:
        with open("temp_book.epub", "wb") as f:
            f.write(file.getbuffer())
        book = epub.read_epub("temp_book.epub")
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text += soup.get_text() + " "
        os.remove("temp_book.epub")
    except Exception as e:
        st.error(f"Erro ao processar EPUB: {e}")
    return text

# --- LOGICA DE DIVISÃO ---

def split_text_smart(text, limit=4000):
    if not text or len(text.strip()) == 0:
        return []
    
    # Limpeza básica
    text = " ".join(text.split())
    
    sentences = text.split(". ")
    chunks = []
    current_chunk = ""

    for s in sentences:
        if len(current_chunk) + len(s) < limit:
            current_chunk += s + ". "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = s + ". "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

# --- TTS ASSINCRONO ---

async def generate_audio(text, voice, path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(path)

# --- INTERFACE ---

with st.sidebar:
    st.image(ICON_URL, width=120)
    st.title("Configurações")
    uploaded_file = st.file_uploader("Upload do Livro", type=["pdf", "epub", "txt"])
    input_title = st.text_input("Título", "Meu Livro")
    input_author = st.text_input("Autor", "Narrador AI")
    selected_voice = st.selectbox("Voz", list(VOICES.keys()))
    
    if st.button("🗑️ Limpar Arquivos"):
        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
            os.makedirs(OUTPUT_DIR)
        st.rerun()

st.title("🎧 Narrador.AI - Estúdio de Audiobook")

if uploaded_file:
    # Extração de texto baseada no tipo
    with st.spinner("Extraindo texto do arquivo..."):
        if uploaded_file.name.endswith(".pdf"):
            full_text = extract_text_from_pdf(uploaded_file)
        elif uploaded_file.name.endswith(".epub"):
            full_text = extract_text_from_epub(uploaded_file)
        else:
            full_text = uploaded_file.getvalue().decode("utf-8")

    # Verificação se o texto foi realmente extraído
    if not full_text or len(full_text.strip()) < 10:
        st.error("❌ Não conseguimos ler o texto deste arquivo. Ele pode ser um PDF protegido ou composto apenas por imagens (sem camada de texto).")
    else:
        chunks = split_text_smart(full_text)
        
        # Dashboard de métricas
        m1, m2, m3 = st.columns(3)
        m1.metric("Partes Identificadas", len(chunks))
        m2.metric("Caracteres Totais", len(full_text))
        m3.metric("Voz", selected_voice.split(" ")[0])

        if st.button("🚀 Iniciar Produção", use_container_width=True):
            progress_bar = st.progress(0)
            status = st.empty()
            
            for i, chunk in enumerate(chunks):
                p_num = i + 1
                f_name = f"Parte_{p_num:03d}.mp3"
                f_path = os.path.join(OUTPUT_DIR, f_name)
                
                status.write(f"🎙️ Gravando parte {p_num} de {len(chunks)}...")
                
                # Execução assíncrona
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(generate_audio(chunk, VOICES[selected_voice], f_path))
                loop.close()
                
                progress_bar.progress(p_num / len(chunks))
            
            status.success("✅ Audiobook pronto!")

            # Download ZIP
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in sorted(os.listdir(OUTPUT_DIR)):
                    if f.endswith(".mp3"):
                        zf.write(os.path.join(OUTPUT_DIR, f), f)
            
            st.download_button(
                "📥 Baixar Audiobook Completo (.ZIP)",
                zip_buffer.getvalue(),
                f"{input_title}.zip",
                "application/zip",
                use_container_width=True
            )
else:
    st.info("👋 Bem-vindo! Carregue um arquivo PDF, EPUB ou TXT na barra lateral para começar.")
