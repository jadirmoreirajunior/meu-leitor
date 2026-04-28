import streamlit as st
import os
import re
import io
import zipfile
import asyncio
import tempfile
from datetime import datetime

from PyPDF2 import PdfReader
from ebooklib import epub
from bs4 import BeautifulSoup

import edge_tts
from gtts import gTTS

from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

# ==============================
# CONFIG
# ==============================

st.set_page_config(page_title="Gerador de Audiobook", layout="wide")

VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculina)": "pt-BR-AntonioNeural",
    "Brenda": "pt-BR-BrendaNeural",
    "Donato": "pt-BR-DonatoNeural",
    "Fabio": "pt-BR-FabioNeural",
}

MAX_CHUNK = 1500
FALLBACK_CHUNK = 3000

# ==============================
# EXTRAÇÃO DE TEXTO
# ==============================

def extract_pdf(file):
    text = ""
    reader = PdfReader(file)
    for page in reader.pages:
        text += page.extract_text() or ""
    return text


def extract_epub(file):
    book = epub.read_epub(file)
    text = ""
    for item in book.get_items():
        if item.get_type() == 9:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text += soup.get_text()
    return text


# ==============================
# DETECÇÃO DE CAPÍTULOS
# ==============================

def detect_sumario(text):
    match = re.search(r"(sum[aá]rio|índice)(.*?)(\n\n|\Z)", text, re.IGNORECASE | re.DOTALL)
    if match:
        bloco = match.group(2)
        linhas = bloco.split("\n")
        titulos = [l.strip() for l in linhas if len(l.strip()) > 5]
        return titulos if len(titulos) > 2 else None
    return None


def split_by_titles(text, titles):
    chapters = []
    for i, title in enumerate(titles):
        pattern = re.escape(title)
        matches = list(re.finditer(pattern, text, re.IGNORECASE))

        if not matches:
            continue

        start = matches[0].start()
        if i + 1 < len(titles):
            next_title = re.escape(titles[i + 1])
            next_match = re.search(next_title, text[start:], re.IGNORECASE)
            end = start + next_match.start() if next_match else len(text)
        else:
            end = len(text)

        chapters.append(text[start:end].strip())

    return chapters if chapters else None


def detect_patterns(text):
    pattern = r"(Capítulo\s+\d+|Capítulo\s+[IVXLC]+|Chapter\s+\d+|Parte\s+\d+|Part\s+[IVXLC]+)"
    matches = list(re.finditer(pattern, text, re.IGNORECASE))

    if len(matches) < 2:
        return None

    chapters = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapters.append(text[start:end].strip())

    return chapters


def split_fallback(text):
    parts = []
    current = ""

    for sentence in re.split(r'(?<=[.!?]) +', text):
        if len(current) + len(sentence) < FALLBACK_CHUNK:
            current += " " + sentence
        else:
            parts.append(current.strip())
            current = sentence

    if current:
        parts.append(current.strip())

    return parts


def split_text(text):
    # Prioridade 1
    titles = detect_sumario(text)
    if titles:
        chapters = split_by_titles(text, titles)
        if chapters:
            return chapters, "Sumário"

    # Prioridade 2
    chapters = detect_patterns(text)
    if chapters:
        return chapters, "Padrão detectado"

    # Prioridade 3
    return split_fallback(text), "Fallback automático"


# ==============================
# TTS
# ==============================

async def edge_generate(text, voice, output):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output)


def generate_audio(text, voice, output):
    # dividir em chunks
    chunks = []
    current = ""

    for sentence in re.split(r'(?<=[.!?]) +', text):
        if len(current) + len(sentence) < MAX_CHUNK:
            current += " " + sentence
        else:
            chunks.append(current.strip())
            current = sentence

    if current:
        chunks.append(current.strip())

    temp_files = []

    for i, chunk in enumerate(chunks):
        temp_file = output.replace(".mp3", f"_part{i}.mp3")

        success = False
        for attempt in range(3):
            try:
                asyncio.run(edge_generate(chunk, voice, temp_file))
                if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                    success = True
                    break
            except:
                pass

        # fallback gTTS
        if not success:
            try:
                tts = gTTS(chunk, lang="pt")
                tts.save(temp_file)
                success = True
            except:
                pass

        if success:
            temp_files.append(temp_file)

    # juntar arquivos
    if not temp_files:
        return False

    with open(output, "wb") as final:
        for f in temp_files:
            with open(f, "rb") as part:
                final.write(part.read())

    # limpar temporários
    for f in temp_files:
        os.remove(f)

    return os.path.exists(output) and os.path.getsize(output) > 0


# ==============================
# METADADOS
# ==============================

def add_metadata(file_path, title, author, track, year):
    try:
        audio = MP3(file_path, ID3=EasyID3)
    except:
        audio = MP3(file_path)
        audio.add_tags()

    audio["title"] = title
    audio["artist"] = author
    audio["tracknumber"] = str(track)
    if year:
        audio["date"] = str(year)

    audio.save()


# ==============================
# UI
# ==============================

st.title("📚➡️🎧 Gerador de Audiobook")

uploaded = st.file_uploader("Envie um PDF ou EPUB", type=["pdf", "epub"])

col1, col2 = st.columns(2)

with col1:
    title = st.text_input("Título do livro")
    author = st.text_input("Autor")

with col2:
    year = st.text_input("Ano")
    voice_label = st.selectbox("Escolha a voz", list(VOICES.keys()))

if uploaded and st.button("Gerar Audiobook"):

    with st.spinner("Extraindo texto..."):
        try:
            if uploaded.name.endswith(".pdf"):
                text = extract_pdf(uploaded)
            else:
                text = extract_epub(uploaded)
        except Exception as e:
            st.error(f"Erro ao extrair texto: {e}")
            st.stop()

    if not text.strip():
        st.error("Não foi possível extrair texto.")
        st.stop()

    chapters, method = split_text(text)

    st.success(f"Método: {method}")
    st.info(f"{len(chapters)} capítulos detectados")

    st.write("### Preview")
    for i, ch in enumerate(chapters[:3]):
        st.write(f"Capítulo {i+1}: {ch[:200]}...")

    progress = st.progress(0)

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_files = []

        for i, chapter in enumerate(chapters):
            output = os.path.join(tmpdir, f"{i+1:03}.mp3")

            ok = generate_audio(chapter, VOICES[voice_label], output)

            if ok:
                add_metadata(output, title, author, i + 1, year)
                audio_files.append(output)

            progress.progress((i + 1) / len(chapters))

        if not audio_files:
            st.error("Falha ao gerar áudios.")
            st.stop()

        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as z:
            for file in audio_files:
                z.write(file, os.path.basename(file))

        st.success("Audiobook gerado com sucesso!")

        st.download_button(
            "📥 Baixar ZIP",
            zip_buffer.getvalue(),
            file_name="audiobook.zip",
            mime="application/zip"
        )
