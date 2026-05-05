import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import json
import shutil
import requests
import re
from io import BytesIO
from PIL import Image
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, APIC
from mutagen.mp3 import MP3

# --- CONFIGURAÇÕES E ESTILIZAÇÃO ---
APP_NAME = "Narrador.AI Pro"
ICON_URL = "https://raw.githubusercontent.com/jadirmoreirajunior/meu-leitor/main/narrador.ai.png"
OUTPUT_DIR = "audiobook_out"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def apply_custom_css():
    st.markdown("""
        <style>
        .main { background-color: #0f111a; color: #ffffff; }
        .stButton>button { width: 100%; border-radius: 8px; background-color: #f08913; color: white; border: none; transition: 0.3s; }
        .stButton>button:hover { background-color: #ff9d2f; transform: scale(1.02); }
        .chapter-card { background: #1a1d29; padding: 15px; border-radius: 10px; border-left: 5px solid #f08913; margin-bottom: 10px; font-size: 0.9rem; }
        .stTextInput>div>div>input, .stSelectbox>div>div>div { background-color: #1a1d29 !important; color: white !important; }
        </style>
    """, unsafe_allow_html=True)

@st.cache_data
def get_icon():
    try:
        res = requests.get(ICON_URL, timeout=5)
        return Image.open(BytesIO(res.content))
    except:
        return None

st.set_page_config(page_title=APP_NAME, page_icon=get_icon(), layout="wide")
apply_custom_css()

# --- LÓGICA DE NEGÓCIO ---

VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
    "Thalita (Feminina)": "pt-BR-ThalitaNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural"
}

def clean_text(text):
    if not text: return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def split_by_chapters(text):
    if not text: return []
    
    # CORREÇÃO re.PatternError: Flag (?i) movida para o início da expressão
    patterns = [
        r'(?i)\nCapítulo\s+[0-9]+', 
        r'(?i)\nChapter\s+[0-9]+',
        r'(?i)\nParte\s+[IVXLCDM0-9]+',
        r'\n[0-9]+\.\s+[A-ZÁÉÍÓÚ]'
    ]
    
    combined_pattern = "|".join(patterns)
    
    # Dividindo o texto
    segments = re.split(combined_pattern, "\n" + text)
    titles = re.findall(combined_pattern, "\n" + text)
    
    # Fallback caso não encontre divisões claras
    if len(segments) < 2:
        chunk_size = 7000 
        return [{"title": f"Parte {i+1:02d}", "content": text[j:j+chunk_size]} 
                for i, j in enumerate(range(0, len(text), chunk_size))]

    chapters = []
    for i, content in enumerate(segments):
        content_cleaned = clean_text(content)
        if len(content_cleaned) < 50: continue # Ignora pedaços muito pequenos (ruído)
        
        # Título limpo (remove o \n do início)
        title = titles[i-1].strip() if i > 0 else "Introdução / Início"
        chapters.append({"title": title, "content": content_cleaned})
    
    return chapters

async def run_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio_with_metadata(text, voice, filename, tags, cover_image=None):
    try:
        asyncio.run(run_tts(text, voice, filename))
        
        audio = MP3(filename, ID3=ID3)
        try:
            audio.add_tags()
        except:
            pass

        audio.tags.add(TIT2(encoding=3, text=tags['title']))
        audio.tags.add(TPE1(encoding=3, text=tags['author']))
        audio.tags.add(TRCK(encoding=3, text=str(tags['track'])))
        
        if cover_image:
            img_byte_arr = BytesIO()
            # Converte para RGB para garantir compatibilidade com MP3 tags
            if cover_image.mode in ("RGBA", "P"):
                cover_image = cover_image.convert("RGB")
            cover_image.save(img_byte_arr, format='JPEG')
            audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_byte_arr.getvalue()))
            
        audio.save()
        return True
    except Exception as e:
        st.error(f"Erro ao processar áudio: {e}")
        return False

# --- INTERFACE ---

with st.sidebar:
    st.image(ICON_URL if ICON_URL else "https://via.placeholder.com/150", width=80)
    st.title("Configurações")
    
    input_mode = st.radio("Origem do Conteúdo", ["📂 Arquivo", "✍️ Texto Manual"])
    voice_key = st.selectbox("Voz Narradora", list(VOICES.keys()))
    
    st.divider()
    book_title = st.text_input("Título do Livro", "Meu Audiobook")
    book_author = st.text_input("Autor", "Desconhecido")
    
    cover_file = st.file_uploader("Capa (JPG/PNG)", type=["jpg", "png"])
    cover_img = Image.open(cover_file) if cover_file else None

col1, col2 = st.columns([2, 1])

with col1:
    st.markdown(f"## 🎧 Narrador.AI Pro")
    
    if input_mode == "📂 Arquivo":
        uploaded_file = st.file_uploader("Upload do livro", type=["pdf", "epub", "txt", "docx"])
        if uploaded_file:
            raw_text = ""
            if uploaded_file.name.endswith(".pdf"):
                pdf = PdfReader(uploaded_file)
                raw_text = "\n".join([page.extract_text() or "" for page in pdf.pages])
            elif uploaded_file.name.endswith(".txt"):
                raw_text = uploaded_file.read().decode("utf-8", errors="ignore")
            elif uploaded_file.name.endswith(".epub"):
                with open("temp.epub", "wb") as f: f.write(uploaded_file.getbuffer())
                book = epub.read_epub("temp.epub")
                for item in book.get_items_of_type(ITEM_DOCUMENT):
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    raw_text += soup.get_text() + "\n"
                os.remove("temp.epub")
            
            if raw_text and st.button("🔍 Analisar Capítulos"):
                st.session_state.chapters = split_by_chapters(raw_text)
                st.rerun()

    else:
        manual_text = st.text_area("Cole seu texto", height=300)
        if st.button("Processar Texto"):
            st.session_state.chapters = split_by_chapters(manual_text)

with col2:
    st.markdown("### 📋 Capítulos")
    if "chapters" in st.session_state:
        for i, cap in enumerate(st.session_state.chapters[:12]):
            st.markdown(f"<div class='chapter-card'><b>{i+1}.</b> {cap['title']}</div>", unsafe_allow_html=True)
        if len(st.session_state.chapters) > 12:
            st.caption(f"E mais {len(st.session_state.chapters)-12} partes...")

# GERAÇÃO
if "chapters" in st.session_state and st.session_state.chapters:
    st.divider()
    c1, c2, c3 = st.columns(3)
    
    if c1.button("🚀 GERAR ÁUDIO"):
        progress_bar = st.progress(0)
        status = st.empty()
        
        for idx, cap in enumerate(st.session_state.chapters):
            track_num = idx + 1
            # Limpa nome do arquivo para evitar erros de sistema
            safe_title = re.sub(r'[\\/*?:"<>|]', "", cap['title'])[:40].strip()
            fname = os.path.join(OUTPUT_DIR, f"{track_num:03d}_{safe_title}.mp3")
            
            if not os.path.exists(fname):
                status.info(f"Processando: {cap['title']}")
                tags = {"title": cap['title'], "author": book_author, "track": track_num}
                generate_audio_with_metadata(cap['content'], VOICES[voice_key], fname, tags, cover_img)
            
            progress_bar.progress(track_num / len(st.session_state.chapters))
        
        status.success("✅ Concluído!")

    if c2.button("📦 BAIXAR TUDO (ZIP)"):
        zip_buffer = io.BytesIO()
        files_to_zip = [f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp3")]
        if files_to_zip:
            with zipfile.ZipFile(zip_buffer, "w") as z:
                for f in files_to_zip:
                    z.write(os.path.join(OUTPUT_DIR, f), f)
            st.download_button("⬇️ Salvar arquivo .zip", zip_buffer.getvalue(), f"{book_title}.zip")
        else:
            st.warning("Gere os áudios primeiro!")

    if c3.button("🗑️ LIMPAR"):
        for f in os.listdir(OUTPUT_DIR):
            os.remove(os.path.join(OUTPUT_DIR, f))
        if "chapters" in st.session_state: del st.session_state.chapters
        st.rerun()
