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
Transforme livros em audiobooks com vozes neurais. Envie arquivos ou escreva seu texto.
</p>
""", unsafe_allow_html=True)

OUTPUT_DIR = "out"
PROGRESS_FILE = "progress.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# SESSION
if "chapters" not in st.session_state:
    st.session_state.chapters = []

if "preview_idx" not in st.session_state:
    st.session_state.preview_idx = 0

# VOZES
VOICES = {
    "Francisca (Feminina - BR)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino - BR)": "pt-BR-AntonioNeural",
    "Brenda (Feminina - BR)": "pt-BR-BrendaNeural",
    "Donato (Masculino - BR)": "pt-BR-DonatoNeural",
    "Fabio (Masculino - BR)": "pt-BR-FabioNeural"
}

# INPUTS
book_title = st.text_input("Título do livro", "Meu Audiobook")
book_author = st.text_input("Autor", "Autor")

voice_label = st.selectbox("Escolha a voz", list(VOICES.keys()))
voice = VOICES[voice_label]

# PRÉVIA
if st.button("▶️ Ouvir Prévia"):
    frases = [
        "Olá, este é um teste de voz.",
        "Transformando texto em áudio.",
        "Seu audiobook começa agora."
    ]
    texto = frases[st.session_state.preview_idx % len(frases)]
    st.session_state.preview_idx += 1

    asyncio.run(edge_tts.Communicate(texto, voice).save("preview.mp3"))
    st.audio("preview.mp3")

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

# DETECÇÃO
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

        chapters.append({
            "title": lines[start],
            "content": "\n".join(lines[start:end])
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

def generate_audio(text, voice, filename, tags):
    asyncio.run(run_tts(text, voice, filename))

    audio = MP3(filename, ID3=ID3)
    try:
        audio.add_tags()
    except:
        pass

    audio.tags.add(TIT2(encoding=3, text=tags['title']))
    audio.tags.add(TPE1(encoding=3, text=tags['author']))
    audio.tags.add(TRCK(encoding=3, text=str(tags['track'])))
    audio.save()

# INPUT
input_mode = st.radio("Modo de entrada:", ["Arquivo", "Texto Manual"], horizontal=True)

file = None
text = None

if input_mode == "Arquivo":
    file = st.file_uploader("Envie seu arquivo", type=["pdf", "epub", "docx", "txt"])

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
    manual_text = st.text_area("Digite o texto")

    if st.button("📝 Processar Texto"):
        st.session_state.chapters = split_hybrid(manual_text)

# LISTA
if st.session_state.chapters:
    st.write("## Capítulos identificados")
    for i, c in enumerate(st.session_state.chapters):
        st.write(f"{i+1:02d} - {c['title']}")

# GERAÇÃO
if st.session_state.chapters:
    if st.button("🚀 Gerar / Continuar"):
        with st.spinner("Gerando áudio..."):
            for i, cap in enumerate(st.session_state.chapters):
                fname = f"{OUTPUT_DIR}/{i+1:03d}.mp3"

                if os.path.exists(fname):
                    continue

                tags = {
                    "title": f"{book_title} - {cap['title']}",
                    "author": book_author,
                    "track": i+1
                }

                generate_audio(cap["content"], voice, fname, tags)

        st.success("Concluído")

# DOWNLOAD
files = sorted(os.listdir(OUTPUT_DIR))

if files:
    st.write("## Downloads")

    for f in files:
        with open(os.path.join(OUTPUT_DIR, f), "rb") as audio:
            st.download_button(f"Baixar {f}", audio, f)

    if st.button("📦 Gerar ZIP"):
        with st.spinner("Compactando..."):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as z:
                for f in files:
                    z.write(os.path.join(OUTPUT_DIR, f), f)

        st.download_button("Baixar ZIP", buffer.getvalue(), "audiobook.zip")

# LIMPAR
if st.button("🗑️ Limpar Tudo"):
    shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    st.session_state.chapters = []
    st.rerun()
