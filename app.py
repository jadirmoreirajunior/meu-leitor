import streamlit as st
import edge_tts
import asyncio
import os
import re
import json
import hashlib
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, APIC

# EXTRAÇÃO
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

# DOCX opcional
try:
    import docx
    WORD_SUPPORT = True
except:
    WORD_SUPPORT = False

# =========================
# CONFIG
# =========================

APP_NAME = "Narrador.AI PRO"

OUTPUT_DIR = Path("out")
CACHE_DIR = Path(".cache")

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

VOICES = {
    "Francisca (Feminina - BR)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino - BR)": "pt-BR-AntonioNeural",
    "Brenda (Feminina - BR)": "pt-BR-BrendaNeural",
    "Donato (Masculino - BR)": "pt-BR-DonatoNeural",
    "Fabio (Masculino - BR)": "pt-BR-FabioNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural"
}

# =========================
# UI
# =========================

st.set_page_config(page_title=APP_NAME, layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 1rem; }
button { width: 100%; border-radius: 10px; height: 45px; }
</style>
""", unsafe_allow_html=True)

st.title("🎧 Narrador.AI PRO")

# =========================
# UTILS
# =========================

def normalize_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def split_sentences(text, max_chars=4500):
    sentences = re.split(r'(?<=[.!?]) +', text)

    chunks = []
    current = ""

    for s in sentences:
        if len(current) + len(s) < max_chars:
            current += " " + s
        else:
            chunks.append(current.strip())
            current = s

    if current:
        chunks.append(current.strip())

    return chunks

def create_parts(text):
    return [{"title": f"Parte {i+1}", "content": p}
            for i, p in enumerate(split_sentences(text))]

# =========================
# EXTRAÇÃO
# =========================

def extract_pdf(file):
    reader = PdfReader(file)
    return "\n".join([p.extract_text() or "" for p in reader.pages])

def extract_txt(file):
    return file.read().decode("utf-8", errors="ignore")

def extract_docx(file):
    if not WORD_SUPPORT:
        return ""
    doc = docx.Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def extract_epub(file):
    temp = "temp.epub"
    with open(temp, "wb") as f:
        f.write(file.read())

    book = epub.read_epub(temp)
    texts = []

    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n").strip()
        if len(text) > 200:
            texts.append(text)

    os.remove(temp)

    return "\n\n".join(texts)

# =========================
# SSML
# =========================

def apply_ssml(text, voice):
    return f"""
<speak>
    <voice name="{voice}">
        <prosody rate="0.95">{text}</prosody>
    </voice>
</speak>
"""

# =========================
# TTS
# =========================

async def tts_generate(ssml, voice, output):
    communicate = edge_tts.Communicate(ssml, voice)
    await communicate.save(output)

def generate_audio(text, voice, output):
    try:
        ssml = apply_ssml(text, voice)
        asyncio.run(tts_generate(ssml, voice, output))
        return True
    except:
        return False

# =========================
# METADATA
# =========================

def add_metadata(file, title, author, track, cover_bytes=None):
    audio = MP3(file, ID3=ID3)

    try:
        audio.add_tags()
    except:
        pass

    audio.tags.add(TIT2(encoding=3, text=title))
    audio.tags.add(TPE1(encoding=3, text=author))
    audio.tags.add(TRCK(encoding=3, text=str(track)))

    if cover_bytes:
        audio.tags.add(APIC(
            encoding=3,
            mime='image/jpeg',
            type=3,
            desc='Cover',
            data=cover_bytes
        ))

    audio.save()

# =========================
# INPUT
# =========================

tab1, tab2 = st.tabs(["📚 Entrada", "🎧 Player"])

with tab1:

    book_title = st.text_input("Título")
    book_author = st.text_input("Autor")

    voice_label = st.selectbox("Voz", list(VOICES.keys()))
    voice = VOICES[voice_label]

    cover = st.file_uploader("Capa", type=["jpg", "png"])

    mode = st.radio("Entrada", ["Arquivo", "Texto"])

    text = ""

    if mode == "Arquivo":
        file = st.file_uploader("Envie arquivo", type=["pdf", "epub", "docx", "txt"])

        if file:
            if file.name.endswith(".pdf"):
                text = extract_pdf(file)

            elif file.name.endswith(".epub"):
                text = extract_epub(file)

            elif file.name.endswith(".docx"):
                text = extract_docx(file)

            elif file.name.endswith(".txt"):
                text = extract_txt(file)

    else:
        text = st.text_area("Texto", height=200)

    if st.button("📖 Processar"):
        if text:
            clean = normalize_text(text)
            st.session_state.parts = create_parts(clean)
            st.success(f"{len(st.session_state.parts)} partes criadas")

    if "parts" in st.session_state:

        if st.button("🚀 Gerar Audiobook"):

            progress_bar = st.progress(0)

            for i, part in enumerate(st.session_state.parts):
                track = i + 1
                fname = OUTPUT_DIR / f"{track:03d}.mp3"

                if fname.exists():
                    continue

                ok = generate_audio(part["content"], voice, str(fname))

                if ok:
                    cover_bytes = cover.read() if cover else None

                    add_metadata(
                        str(fname),
                        f"{book_title} - {part['title']}",
                        book_author,
                        track,
                        cover_bytes
                    )

                progress_bar.progress((i+1)/len(st.session_state.parts))

            st.success("✅ Concluído")

# =========================
# PLAYER
# =========================

with tab2:
    files = sorted(OUTPUT_DIR.glob("*.mp3"))

    if not files:
        st.info("Nenhum áudio gerado")
    else:
        for f in files:
            st.markdown(f"**{f.name}**")
            st.audio(str(f))
