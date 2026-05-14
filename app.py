import streamlit as st
import edge_tts
import asyncio
import os
import re
import zipfile
import shutil
import time

from io import BytesIO
from pathlib import Path

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

# =====================================
# CONFIG
# =====================================

APP_NAME = "Narrador.AI"
OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")

OUTPUT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

MAX_CHUNK_SIZE = 1800
MAX_RETRIES = 5

# =====================================
# PAGE
# =====================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🎧",
    layout="wide"
)

st.title("🎧 Narrador.AI")
st.caption("Criação profissional de audiobooks")

# =====================================
# VOICES
# =====================================

VOICES = {
    "Francisca (BR)": "pt-BR-FranciscaNeural",
    "Antonio (BR)": "pt-BR-AntonioNeural",
    "Brenda (BR)": "pt-BR-BrendaNeural",
    "Donato (BR)": "pt-BR-DonatoNeural",
    "Fabio (BR)": "pt-BR-FabioNeural",
    "Emma (EN)": "en-US-EmmaMultilingualNeural",
    "Andrew (EN)": "en-US-AndrewMultilingualNeural"
}

# =====================================
# SESSION STATE
# =====================================

if "text" not in st.session_state:
    st.session_state.text = ""

if "chunks" not in st.session_state:
    st.session_state.chunks = []

if "generated" not in st.session_state:
    st.session_state.generated = False

# =====================================
# TEXT CLEANER
# =====================================


def clean_text(text):

    text = text.replace("\x00", " ")

    text = re.sub(r"\s+", " ", text)

    text = re.sub(r"([a-z])\-\s+([a-z])", r"\1\2", text)

    text = text.strip()

    return text

# =====================================
# SMART SPLIT
# =====================================


def split_text_smart(text, max_size=MAX_CHUNK_SIZE):

    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current = ""

    for sentence in sentences:

        if len(current) + len(sentence) <= max_size:
            current += " " + sentence

        else:
            if current:
                chunks.append(current.strip())
            current = sentence

    if current:
        chunks.append(current.strip())

    return chunks

# =====================================
# EXTRACTORS
# =====================================


def extract_pdf(file):

    reader = PdfReader(file)

    pages = []

    for page in reader.pages:

        txt = page.extract_text()

        if txt:
            pages.append(txt)

    return clean_text("\n".join(pages))


def extract_txt(file):

    content = file.read()

    try:
        return clean_text(content.decode("utf-8"))
    except:
        return clean_text(content.decode("latin-1"))


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

# =====================================
# AUDIO VALIDATION
# =====================================


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

# =====================================
# TTS
# =====================================


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

# =====================================
# TAGS
# =====================================


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

# =====================================
# UI
# =====================================

uploaded = st.file_uploader(
    "Envie um arquivo",
    type=["pdf", "epub", "txt", "docx"]
)

book_title = st.text_input(
    "Título do audiobook",
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

# =====================================
# EXTRAÇÃO
# =====================================

if uploaded:

    if st.button("📖 Extrair Texto"):

        with st.spinner("Extraindo texto..."):

            try:

                if uploaded.name.endswith(".pdf"):
                    text = extract_pdf(uploaded)

                elif uploaded.name.endswith(".epub"):
                    text = extract_epub(uploaded)

                elif uploaded.name.endswith(".txt"):
                    text = extract_txt(uploaded)

                elif uploaded.name.endswith(".docx"):
                    text = extract_docx(uploaded)

                else:
                    text = ""

                st.session_state.text = text
                st.session_state.chunks = split_text_smart(text)

                st.success("Texto extraído com sucesso")

            except Exception as e:
                st.error(f"Erro ao extrair texto: {e}")

# =====================================
# PREVIEW
# =====================================

if st.session_state.text:

    st.write("---")

    st.subheader("Prévia do Texto")

    st.text_area(
        "Trecho",
        st.session_state.text[:3000],
        height=250
    )

    st.info(f"Partes identificadas: {len(st.session_state.chunks)}")

# =====================================
# GENERATE
# =====================================

if st.session_state.chunks:

    st.write("---")

    if st.button("🚀 Gerar Audiobook"):

        progress_bar = st.progress(0)
        status = st.empty()

        generated_files = []

        total = len(st.session_state.chunks)

        for idx, chunk in enumerate(st.session_state.chunks):

            track = idx + 1

            filename = OUTPUT_DIR / f"{track:03d}.mp3"

            if filename.exists() and validate_audio(filename):

                generated_files.append(filename)

                progress_bar.progress(track / total)

                continue

            status.write(f"Gerando parte {track} de {total}")

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

                st.error(f"Erro na parte {track}")
                break

            progress_bar.progress(track / total)

        st.session_state.generated = True

        st.success("Audiobook gerado com sucesso")

# =====================================
# DOWNLOADS
# =====================================

files = sorted([
    f for f in os.listdir(OUTPUT_DIR)
    if f.endswith(".mp3")
])

if files:

    st.write("---")
    st.subheader("Downloads")

    # DOWNLOAD INDIVIDUAL
    for f in files:

        path = OUTPUT_DIR / f

        with open(path, "rb") as audio_file:

            st.download_button(
                label=f"⬇️ Baixar {f}",
                data=audio_file,
                file_name=f,
                mime="audio/mpeg"
            )

    # ZIP
    zip_buffer = BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zipf:

        for f in files:
            zipf.write(OUTPUT_DIR / f, f)

    st.download_button(
        label="📦 Baixar Audiobook Completo (ZIP)",
        data=zip_buffer.getvalue(),
        file_name=f"{book_title}.zip",
        mime="application/zip"
    )

# =====================================
# CLEAN
# =====================================

st.write("---")

if st.button("🗑️ Limpar Tudo"):

    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    shutil.rmtree(TEMP_DIR, ignore_errors=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

    st.session_state.text = ""
    st.session_state.chunks = []
    st.session_state.generated = False

    st.success("Arquivos removidos")

    st.rerun()
