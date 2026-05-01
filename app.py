import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
import io
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

# --- CONFIGURAÇÃO DE IDENTIDADE E PWA ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://jadirmoreirajunior.github.io/meu-leitor/narrador.ai.png"

st.set_page_config(
    page_title=APP_NAME,
    page_icon=ICON_URL,
    layout="wide"
)

# Injeção de HTML para ícone de instalação (PWA)
st.markdown(f"""
    <head>
        <link rel="apple-touch-icon" sizes="180x180" href="{ICON_URL}">
        <link rel="icon" type="image/png" sizes="32x32" href="{ICON_URL}">
        <link rel="manifest" href="data:application/json;base64,{{'name': '{APP_NAME}', 'short_name': '{APP_NAME}', 'icons': [{{'src': '{ICON_URL}', 'sizes': '512x512', 'type': 'image/png'}}]}}">
    </head>
    <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        .stButton>button {{ width: 100%; border-radius: 20px; height: 3em; background-color: #0e1117; color: white; border: 1px solid #30363d; }}
        .stButton>button:hover {{ border-color: #f0ad4e; color: #f0ad4e; }}
    </style>
    """, unsafe_allow_html=True)

# --- CONSTANTES ---
VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
    "Fabio (Masculino)": "pt-BR-FabioNeural"
}

# --- FUNÇÕES DE EXTRAÇÃO ---

def extract_text_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        content = page.extract_text()
        if content: text += content + "\n"
    return text

def extract_text_epub(file):
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())
    try:
        book = epub.read_epub("temp.epub")
        chapters = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            chapters.append(soup.get_text())
        return "\n".join(chapters)
    finally:
        if os.path.exists("temp.epub"): os.remove("temp.epub")

# --- LÓGICA DE CAPÍTULOS ---

def split_text(text):
    pattern = r'^\s*(?:Capítulo|Chapter|Parte|Part)\s+(?:[IVXLCDM]+|\d+)'
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.IGNORECASE))
    
    if len(matches) > 1:
        method = "Sumário/Padrões Detectados"
        chapters = []
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            title = matches[i].group().strip()
            content = text[start:end].strip()
            if content: chapters.append({"title": title, "content": content})
        return chapters, method

    method = "Divisão Automática (Fallback)"
    chunks = []
    max_chars = 3000
    curr_idx = 0
    while curr_idx < len(text):
        end_idx = curr_idx + max_chars
        if end_idx < len(text):
            last_p = text.rfind('.', curr_idx, end_idx)
            if last_p != -1 and last_p > curr_idx + 1000: end_idx = last_p + 1
        chunk = text[curr_idx:end_idx].strip()
        if chunk: chunks.append({"title": f"Parte {len(chunks)+1:03d}", "content": chunk})
        curr_idx = end_idx
    return chunks, method

# --- MOTOR TTS ---

async def run_edge_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio(text, voice, filename, tags):
    text = text.replace('\xa0', ' ').strip()
    if not text: return False
    
    for attempt in range(3):
        try:
            asyncio.run(run_edge_tts(text, voice, filename))
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                break
        except:
            if attempt == 2: # Última tentativa: gTTS
                try:
                    gTTS(text=text[:5000], lang='pt').save(filename)
                except: return False
    
    try:
        audio = MP3(filename, ID3=ID3)
        try: audio.add_tags()
        except: pass
        audio.tags.add(TIT2(encoding=3, text=tags['title']))
        audio.tags.add(TPE1(encoding=3, text=tags['author']))
        audio.tags.add(TRCK(encoding=3, text=str(tags['track'])))
        if tags['year']: audio.tags.add(TYER(encoding=3, text=str(tags['year'])))
        audio.save()
    except: pass
    return True

# --- INTERFACE ---

st.title(f"🎧 {APP_NAME}")
st.caption("Transforme seus livros em audiolivros com tecnologia neural.")

with st.sidebar:
    st.image(ICON_URL, width=100)
    st.header("Configurações")
    file = st.file_uploader("Upload PDF ou EPUB", type=["pdf", "epub"])
    voice_label = st.selectbox("Escolha a Voz", list(VOICES.keys()))
    book_title = st.text_input("Título do Livro", "Meu Audiobook")
    book_author = st.text_input("Autor", "Desconhecido")
    book_year = st.text_input("Ano", "")

if file:
    with st.spinner("Extraindo texto..."):
        text_data = extract_text_pdf(file) if file.name.endswith(".pdf") else extract_text_epub(file)
    
    if text_data:
        chapters, method = split_text(text_data)
        st.info(f"Modo: {method} | Itens: {len(chapters)}")
        
        if st.button("🚀 GERAR AUDIOBOOK"):
            progress = st.progress(0)
            status = st.empty()
            if not os.path.exists("out"): os.makedirs("out")
            
            files = []
            for i, cap in enumerate(chapters):
                track_num = i + 1
                fname = f"out/{track_num:03d}.mp3"
                status.text(f"Processando {track_num}/{len(chapters)}: {cap['title']}")
                
                tags = {'title': f"{book_title} - {cap['title']}", 'author': book_author, 'track': track_num, 'year': book_year}
                
                if generate_audio(cap['content'], VOICES[voice_label], fname, tags):
                    files.append(fname)
                progress.progress(track_num / len(chapters))
            
            if files:
                zip_name = f"{book_title}.zip"
                with zipfile.ZipFile(zip_name, 'w') as zf:
                    for f in files:
                        zf.write(f, os.path.basename(f))
                        os.remove(f)
                
                st.success("Concluído!")
                with open(zip_name, "rb") as f:
                    st.download_button("📥 Baixar Audiobook (ZIP)", f, file_name=zip_name)
                os.remove(zip_name)
                os.rmdir("out")
