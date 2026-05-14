import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import json
import shutil
import requests
from io import BytesIO
from PIL import Image
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TRCK
from mutagen.mp3 import MP3

# --- CONFIGURAÇÃO DA PÁGINA ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://raw.githubusercontent.com/jadirmoreirajunior/meu-leitor/main/narrador.ai.png"

try:
    response = requests.get(ICON_URL, timeout=5)
    icon = Image.open(BytesIO(response.content))
except:
    icon = "🎧"

st.set_page_config(page_title=APP_NAME, page_icon=icon, layout="wide")

# --- ESTILIZAÇÃO CSS ---
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; background-color: #4F46E5; color: white; }
    .status-card { padding: 20px; border-radius: 10px; background-color: white; border: 1px solid #e0e0e0; }
    </style>
""", unsafe_allow_html=True)

OUTPUT_DIR = "audiobook_out"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

VOICES = {
    "Francisca (Feminina - BR)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino - BR)": "pt-BR-AntonioNeural",
    "Brenda (Feminina - BR)": "pt-BR-BrendaNeural",
    "Donato (Masculino - BR)": "pt-BR-DonatoNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
}

# --- FUNÇÕES DE EXTRAÇÃO ---
def clean_text(text):
    """Limpa espaços extras e caracteres irrelevantes."""
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 2]
    return " ".join(lines)

def extract_text(file):
    text = ""
    if file.name.endswith(".pdf"):
        reader = PdfReader(file)
        text = " ".join([p.extract_text() or "" for p in reader.pages])
    elif file.name.endswith(".epub"):
        with open("temp.epub", "wb") as f:
            f.write(file.getbuffer())
        book = epub.read_epub("temp.epub")
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text += soup.get_text() + " "
        os.remove("temp.epub")
    elif file.name.endswith(".txt"):
        text = file.getvalue().decode("utf-8")
    return clean_text(text)

def split_text_smart(text, max_chars=4000):
    """Divide o texto respeitando o fim das frases."""
    paragraphs = text.split(". ")
    chunks = []
    current_chunk = ""

    for p in paragraphs:
        if len(current_chunk) + len(p) < max_chars:
            current_chunk += p + ". "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = p + ". "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

# --- CORE TTS (ASSÍNCRONO) ---
async def process_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def add_metadata(filename, title, author, track):
    try:
        audio = MP3(filename, ID3=ID3)
        try:
            audio.add_tags()
        except:
            pass
        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=author))
        audio.tags.add(TRCK(encoding=3, text=str(track)))
        audio.save()
    except Exception as e:
        st.error(f"Erro nos metadados: {e}")

# --- INTERFACE ---
col1, col2 = st.columns([1, 2])

with col1:
    st.image(ICON_URL, width=100)
    st.title("Narrador.AI")
    st.subheader("Configurações do Audiobook")
    
    file = st.file_uploader("Documento (PDF, EPUB, TXT)", type=["pdf", "epub", "txt"])
    book_title = st.text_input("Título da Obra", "Meu Audiobook")
    book_author = st.text_input("Autor", "Autor Desconhecido")
    voice_label = st.selectbox("Voz do Narrador", list(VOICES.keys()))
    
    if st.button("🗑️ Resetar Projeto"):
        shutil.rmtree(OUTPUT_DIR)
        os.makedirs(OUTPUT_DIR)
        st.rerun()

with col2:
    if file:
        text_content = extract_text(file)
        parts = split_text_smart(text_content)
        
        st.info(f"📖 Documento processado: {len(parts)} capítulos/partes geradas.")
        
        if st.button("🚀 Iniciar Conversão Profissional"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, chunk in enumerate(parts):
                track_num = i + 1
                fname = os.path.join(OUTPUT_DIR, f"capitulo_{track_num:03d}.mp3")
                
                status_text.markdown(f"🎙️ **Narrando:** Parte {track_num} de {len(parts)}...")
                
                # Execução assíncrona robusta
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(process_tts(chunk, VOICES[voice_label], fname))
                    add_metadata(fname, f"{book_title} - Parte {track_num}", book_author, track_num)
                finally:
                    loop.close()
                
                progress_bar.progress(track_num / len(parts))
            
            st.success("✅ Audiobook gerado com sucesso!")

    # --- ÁREA DE DOWNLOAD ---
    st.divider()
    st.subheader("📦 Arquivos Gerados")
    
    ready_files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp3")])
    
    if ready_files:
        c1, c2 = st.columns(2)
        with c1:
            # ZIP Download
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in ready_files:
                    zf.write(os.path.join(OUTPUT_DIR, f), f)
            st.download_button(
                label="🎁 Baixar Audiobook Completo (ZIP)",
                data=zip_buffer.getvalue(),
                file_name=f"{book_title}.zip",
                mime="application/zip"
            )
        
        with c2:
            # Lista individual
            with st.expander("Ver capítulos individuais"):
                for f in ready_files:
                    with open(os.path.join(OUTPUT_DIR, f), "rb") as a_file:
                        st.audio(a_file.read(), format="audio/mp3")
                        st.download_button(f"Download {f}", a_file.read(), file_name=f)
    else:
        st.write("Nenhum arquivo pronto ainda. Carregue um documento e clique em 'Iniciar'.")
