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
from ebooklib import epub
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TRCK
from mutagen.mp3 import MP3

# DOCX
try:
    import docx
    WORD_SUPPORT = True
except:
    WORD_SUPPORT = False

APP_NAME = "Narrador.AI"
ICON_URL = "https://raw.githubusercontent.com/jadirmoreirajunior/meu-leitor/main/narrador.ai.png"

# favicon
try:
    response = requests.get(ICON_URL)
    icon = Image.open(BytesIO(response.content))
except:
    icon = "🎧"

st.set_page_config(page_title=APP_NAME, page_icon=icon, layout="wide")

# HEADER + DESCRIÇÃO
st.markdown(f"""
<div style="display:flex;align-items:center;gap:12px;">
    <img src="{ICON_URL}" width="60" style="border-radius:12px;">
    <h1 style="margin:0;">Narrador.AI</h1>
</div>

<p style="color:gray;">
Transforme livros em audiobooks automaticamente com vozes neurais.
Envie PDF, EPUB, DOCX ou TXT — ou escreva manualmente — e gere áudios organizados.
</p>
""", unsafe_allow_html=True)

OUTPUT_DIR = "out"
PROGRESS_FILE = "progress.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

if "chapters" not in st.session_state:
    st.session_state.chapters = []

# VOZES
VOICES = {
    "Francisca (BR)": "pt-BR-FranciscaNeural",
    "Antonio (BR)": "pt-BR-AntonioNeural",
    "Brenda (BR)": "pt-BR-BrendaNeural",
    "Donato (BR)": "pt-BR-DonatoNeural"
}

# EXTRAÇÃO
def extract_text_pdf(file):
    reader = PdfReader(file)
    return "\n".join([p.extract_text() or "" for p in reader.pages])

def extract_text_txt(file):
    return file.getvalue().decode("utf-8")

def extract_text_docx(file):
    if not WORD_SUPPORT:
        return ""
    doc = docx.Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

# DIVISÃO (~10 partes)
def split_text(text):
    total_len = len(text)
    chunk_size = max(3000, total_len // 10)

    chunks = []
    i = 0

    while i < total_len:
        end = i + chunk_size
        part = text[i:end].strip()

        chunks.append({
            "title": f"Parte {len(chunks)+1}",
            "content": part
        })

        i = end

    return chunks

# DETECÇÃO SIMPLES
def split_by_chapters(text):
    lines = text.split("\n")
    indices = []

    for i, line in enumerate(lines):
        if re.match(r'^\s*(cap[ií]tulo|chapter|parte|[ivxlcdm]+)', line.lower()):
            indices.append(i)

    if len(indices) < 3:
        return split_text(text)

    chapters = []
    for i in range(len(indices)):
        start = indices[i]
        end = indices[i+1] if i+1 < len(indices) else len(lines)

        content = "\n".join(lines[start:end])
        chapters.append({
            "title": lines[start],
            "content": content
        })

    return chapters

# HÍBRIDO
def split_hybrid(text):
    chapters = split_by_chapters(text)

    if len(chapters) < 3:
        return split_text(text)

    if len(chapters) > 50:
        full = "\n\n".join([c["content"] for c in chapters])
        return split_text(full)

    return chapters

# EPUB COM SPINE
def extract_text_epub(file):
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())

    try:
        book = epub.read_epub("temp.epub")
        texts = []

        for item_id, _ in book.spine:
            item = book.get_item_with_id(item_id)
            if item:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n").strip()
                if len(text) > 200:
                    texts.append(text)

        full_text = "\n\n".join(texts)
        return split_hybrid(full_text)

    finally:
        if os.path.exists("temp.epub"):
            os.remove("temp.epub")

# TTS
async def run_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio(text, voice, filename):
    asyncio.run(run_tts(text, voice, filename))

# UI
input_mode = st.radio("Modo:", ["Arquivo", "Texto"], horizontal=True)

voice = VOICES[st.selectbox("Voz", list(VOICES.keys()))]

file = None
text = None

if input_mode == "Arquivo":
    file = st.file_uploader("Arquivo", type=["pdf","epub","docx","txt"])

if file:
    if file.name.endswith(".pdf"):
        text = extract_text_pdf(file)
    elif file.name.endswith(".epub"):
        st.session_state.chapters = extract_text_epub(file)
    elif file.name.endswith(".docx"):
        text = extract_text_docx(file)
    elif file.name.endswith(".txt"):
        text = extract_text_txt(file)

    if text:
        st.session_state.chapters = split_hybrid(text)

else:
    manual = st.text_area("Texto")

    if st.button("Processar"):
        st.session_state.chapters = split_hybrid(manual)

# MOSTRAR CAPÍTULOS
if st.session_state.chapters:
    st.write("Capítulos detectados:")
    for c in st.session_state.chapters:
        st.write("-", c["title"])

# GERAR
if st.session_state.chapters:
    if st.button("Gerar"):
        with st.spinner("Gerando áudio..."):
            for i, cap in enumerate(st.session_state.chapters):
                fname = f"{OUTPUT_DIR}/{i+1:03d}.mp3"
                generate_audio(cap["content"], voice, fname)

        st.success("Concluído")

# DOWNLOAD
files = os.listdir(OUTPUT_DIR)

if files:
    if st.button("Gerar ZIP"):
        with st.spinner("Compactando..."):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as z:
                for f in files:
                    z.write(os.path.join(OUTPUT_DIR, f), f)

        st.download_button("Baixar", buffer.getvalue(), "audiobook.zip")

# LIMPAR
if st.button("Limpar"):
    shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    st.rerun()
