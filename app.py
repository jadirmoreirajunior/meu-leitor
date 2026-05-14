import streamlit as st
import edge_tts
import asyncio
import tempfile
import os
import zipfile
import shutil
import re
import time
import json

from pathlib import Path
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TRCK

# DOCX
try:
    import docx
    DOCX_SUPPORT = True
except:
    DOCX_SUPPORT = False

# =========================
# CONFIG
# =========================

APP_NAME = "Narrador.AI"

OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")

OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

MAX_CHUNK_SIZE = 1800
MAX_RETRIES = 5

# =========================
# STREAMLIT
# =========================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🎧",
    layout="wide"
)

st.title("🎧 Narrador.AI")
st.caption("Criação profissional de audiobooks")

# =========================
# VOICES
# =========================

VOICES = {
    "Francisca (BR)": "pt-BR-FranciscaNeural",
    "Antonio (BR)": "pt-BR-AntonioNeural",
    "Brenda (BR)": "pt-BR-BrendaNeural",
    "Donato (BR)": "pt-BR-DonatoNeural",
    "Fabio (BR)": "pt-BR-FabioNeural",
    "Emma (EN)": "en-US-EmmaMultilingualNeural",
    "Andrew (EN)": "en-US-AndrewMultilingualNeural",
}

# =========================
# TEXT CLEANER
# =========================

def clean_text(text):

    text = text.replace("\x00", " ")

    text = re.sub(r"\s+", " ", text)

    text = re.sub(r"([a-z])-\s+([a-z])", r"\1\2", text)

    text = text.strip()

    return text

# =========================
# SMART SPLITTER
# =========================

def split_text_smart(text, max_size=MAX_CHUNK_SIZE):

    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current = ""

    for sentence in sentences:

        if len(current) + len(sentence) < max_size:
            current += " " + sentence
        else:
            chunks.append(current.strip())
            current = sentence

    if current:
        chunks.append(current.strip())

    return chunks

# =========================
# EXTRACTORS
# =========================

def extract_pdf(file):

    reader = PdfReader(file)

    pages = []

    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            pages.append(txt)

    return clean_text("\n".join(pages))

def extract_txt(file):

    try:
        return clean_text(file.read().decode("utf-8"))
    except:
        return clean_text(file.read().decode("latin-1"))

def extract_docx(file):

    if not DOCX_SUPPORT:
        return ""

    document = docx.Document(file)

    text = "\n".join([p.text for p in document.paragraphs])

    return clean_text(text)

def extract_epub(uploaded_file):

    temp_path = TEMP_DIR / "temp.epub"

    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    book = epub.read_epub(str(temp_path))

    texts = []

    for item in book.get_items():

        if item.get_type() == ITEM_DOCUMENT:

            soup = BeautifulSoup(item.get_content(), "html.parser")

            text = soup.get_text(separator=" ")

            texts.append(text)

    return clean_text("\n".join(texts))

# =========================
# AUDIO VALIDATION
# =========================

def validate_audio(file_path):

    if not os.path.exists(file_path):
        return False

    if os.path.getsize(file_path) < 5000:
        return False

    try:
        audio = MP3(file_path)

        if audio.info.length <= 0:
            return False

    except:
        return False

    return True

# =========================
# TTS ENGINE
# =========================

async def tts_generate(text, voice, output_file):

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice
    )

    await communicate.save(output_file)

def generate_audio(text, voice, output_path):

    for attempt in range(MAX_RETRIES):

        try:

            temp_file = str(output_path) + ".tmp.mp3"

            asyncio.run(
                tts_generate(
                    text,
                    voice,
                    temp_file
                )
            )

            if validate_audio(temp_file):

                os.replace(temp_file, output_path)

                return True

            else:

                if os.path.exists(temp_file):
                    os.remove(temp_file)

        except Exception as e:

            print(e)

        time.sleep(2)

    return False

# =========================
# ID3 TAGS
# =========================

def add_tags(file_path, title, author, track):

    try:

        audio = MP3(file_path, ID3=ID3)

        try:
            audio.add_tags()
        except:
            pass

        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=author))
        audio.tags.add(TRCK(encoding=3, text=str(track)))

        audio.save()

    except Exception as e:
        print(e)

# =========================
# UI
# =========================

uploaded = st.file_uploader(
    "Envie um arquivo",
    type=["pdf", "epub", "txt", "docx"]
)

book_title = st.text_input(
    "Título",
    value="Meu Audiobook"
)

book_author = st.text_input(
    "Autor",
    value="Autor"
)

voice_name = st.selectbox(
    "Escolha a voz",
    list(VOICES.keys())
)

voice = VOICES[voice_name]

# =========================
# EXTRAÇÃO
# =========================

full_text = ""

if uploaded:

    with st.spinner("Extraindo texto..."):

        if uploaded.name.endswith(".pdf"):
            full_text = extract_pdf(uploaded)

        elif uploaded.name.endswith(".epub"):
            full_text = extract_epub(uploaded)

        elif uploaded.name.endswith(".txt"):
            full_text = extract_txt(uploaded)

        elif uploaded.name.endswith(".docx"):
            full_text = extract_docx(uploaded)

    st.success("Texto extraído com sucesso")

# =========================
# PROCESSAMENTO
# =========================

if full_text:

    chunks = split_text_smart(full_text)

    st.info(f"{len(chunks)} partes identificadas")

    if st.button("🚀 Gerar Audiobook"):

        progress = st.progress(0)

        status = st.empty()

        generated_files = []

        for idx, chunk in enumerate(chunks):

            track = idx + 1

            filename = OUTPUT_DIR / f"{track:03d}.mp3"

            if filename.exists() and validate_audio(filename):

                generated_files.append(filename)

                continue

            status.write(f"Gerando parte {track}/{len(chunks)}")

            ok = generate_audio(
                chunk,
                voice,
                str(filename)
            )

            if ok:

                add_tags(
                    str(filename),
                    f"{book_title} - Parte {track}",
                    book_author,
                    track
                )

                generated_files.append(filename)

            else:

                st.error(f"Erro ao gerar parte {track}")

                break

            progress.progress((idx + 1) / len(chunks))

        if generated_files:

            zip_buffer = BytesIO()

            with zipfile.ZipFile(
                zip_buffer,
                "w",
                zipfile.ZIP_DEFLATED
            ) as zipf:

                for file in generated_files:
                    zipf.write(file, file.name)

            st.success("Audiobook gerado com sucesso")

            st.download_button(
                "📦 Baixar Audiobook ZIP",
                zip_buffer.getvalue(),
                file_name=f"{book_title}.zip",
                mime="application/zip"
            )

# =========================
# CLEAN
# =========================

if st.button("🗑️ Limpar Arquivos"):

    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)

    OUTPUT_DIR.mkdir(exist_ok=True)

    st.success("Arquivos removidos")
