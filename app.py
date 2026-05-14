import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import shutil
import requests
from io import BytesIO
from PIL import Image
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TRCK
from mutagen.mp3 import MP3

# --- CONFIGURAÇÃO DA INTERFACE ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://raw.githubusercontent.com/jadirmoreirajunior/meu-leitor/main/narrador.ai.png"

st.set_page_config(page_title=APP_NAME, page_icon="🎧", layout="wide")

# Estilização para um visual "App Profissional"
st.markdown("""
    <style>
    .stProgress > div > div > div > div { background-image: linear-gradient(to right, #4facfe 0%, #00f2fe 100%); }
    .main { background-color: #f8f9fa; }
    section[data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e0e0e0; }
    </style>
""", unsafe_allow_html=True)

# --- GERENCIAMENTO DE DIRETÓRIOS ---
# Usamos uma pasta local no servidor para processar os arquivos
OUTPUT_DIR = "temp_audio_out"
if os.path.exists(OUTPUT_DIR):
    shutil.rmtree(OUTPUT_DIR)
os.makedirs(OUTPUT_DIR)

VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
}

# --- FUNÇÕES TÉCNICAS ---

def extract_text(file):
    """Extrai texto de diferentes formatos de forma limpa."""
    text = ""
    try:
        if file.name.endswith(".pdf"):
            reader = PdfReader(file)
            text = " ".join([page.extract_text() or "" for page in reader.pages])
        elif file.name.endswith(".epub"):
            # Salva temporariamente para leitura do ebooklib
            with open("temp_book.epub", "wb") as f:
                f.write(file.getbuffer())
            book = epub.read_epub("temp_book.epub")
            for item in book.get_items_of_type(ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text += soup.get_text() + " "
            os.remove("temp_book.epub")
        elif file.name.endswith(".txt"):
            text = file.getvalue().decode("utf-8")
    except Exception as e:
        st.error(f"Erro ao ler arquivo: {e}")
    
    # Limpeza básica de ruído de texto
    return " ".join(text.split())

def split_text_into_chunks(text, limit=4500):
    """Divide o texto sem cortar palavras, respeitando o limite do TTS."""
    words = text.split()
    chunks = []
    current_chunk = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 <= limit:
            current_chunk.append(word)
            current_length += len(word) + 1
        else:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_length = len(word)
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks

async def save_audio(text, voice, path):
    """Função core para gerar o áudio sem erros de 0 bytes."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(path)

def apply_metadata(path, title, author, track_num):
    """Adiciona tags ID3 profissionais ao MP3."""
    try:
        audio = MP3(path, ID3=ID3)
        try: audio.add_tags()
        except: pass
        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=author))
        audio.tags.add(TRCK(encoding=3, text=str(track_num)))
        audio.save()
    except:
        pass

# --- INTERFACE DO USUÁRIO ---

with st.sidebar:
    st.image(ICON_URL if requests.get(ICON_URL).status_code == 200 else "https://via.placeholder.com/150", width=120)
    st.title("Configurações")
    
    uploaded_file = st.file_uploader("Upload do Livro", type=["pdf", "epub", "txt"])
    input_title = st.text_input("Título do Audiobook", "Meu Livro")
    input_author = st.text_input("Autor", "Narrador AI")
    selected_voice = st.selectbox("Selecione a Voz", list(VOICES.keys()))
    
    st.divider()
    st.info("Dica: Arquivos PDF grandes podem levar alguns minutos para processar.")

st.title("🎧 Narrador.AI - Estúdio de Audiobook")

if uploaded_file:
    # 1. Extração
    full_text = extract_text(uploaded_file)
    chunks = split_text_into_chunks(full_text)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Partes Identificadas", len(chunks))
    col2.metric("Caracteres Totais", len(full_text))
    col3.metric("Voz Selecionada", selected_voice.split(" ")[0])

    # 2. Processamento
    if st.button("🚀 Iniciar Produção Profissional", use_container_width=True):
        progress_bar = st.progress(0)
        status_msg = st.empty()
        
        for i, text_segment in enumerate(chunks):
            part_num = i + 1
            file_name = f"Parte_{part_num:03d}.mp3"
            file_path = os.path.join(OUTPUT_DIR, file_name)
            
            status_msg.write(f"🎙️ Gravando {file_name}...")
            
            # Execução segura do loop assíncrono para ambiente Web
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(save_audio(text_segment, VOICES[selected_voice], file_path))
            loop.close()
            
            # Metadados
            apply_metadata(file_path, f"{input_title} - Parte {part_num}", input_author, part_num)
            
            # Atualiza progresso
            progress_bar.progress(part_num / len(chunks))
        
        status_msg.success("🎉 Produção finalizada!")

        # 3. Downloads
        st.divider()
        st.subheader("📥 Seus Arquivos estão prontos")
        
        final_files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp3")])
        
        if final_files:
            # Opção de baixar tudo em ZIP (Profissional)
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in final_files:
                    zf.write(os.path.join(OUTPUT_DIR, f), f)
            
            st.download_button(
                label="📦 Baixar Audiobook Completo (.ZIP)",
                data=zip_buffer.getvalue(),
                file_name=f"{input_title.replace(' ', '_')}.zip",
                mime="application/zip",
                use_container_width=True
            )
            
            # Player de prévia para cada capítulo
            with st.expander("Ouvir capítulos individualmente"):
                for f in final_files:
                    path = os.path.join(OUTPUT_DIR, f)
                    with open(path, "rb") as audio_file:
                        st.audio(audio_file.read(), format="audio/mp3")
                        st.caption(f)

else:
    st.warning("Aguardando upload de arquivo para iniciar...")
