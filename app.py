import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
import io
import json
import shutil
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
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
st.set_page_config(page_title=APP_NAME, page_icon="🎧", layout="wide")

OUTPUT_DIR = "out"
PROGRESS_FILE = "progress.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# ---------------- VOZES ----------------
VOICES = {
    "Francisca (Feminina - BR)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino - BR)": "pt-BR-AntonioNeural",
    "Brenda (Feminina - BR)": "pt-BR-BrendaNeural",
    "Donato (Masculino - BR)": "pt-BR-DonatoNeural",
    "Fabio (Masculino - BR)": "pt-BR-FabioNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural"
}

# ---------------- PROGRESSO ----------------
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

# ---------------- EXTRAÇÃO ----------------
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

def extract_text_epub(file):
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())

    chapters = []
    try:
        book = epub.read_epub("temp.epub")
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text = soup.get_text(separator="\n").strip()
            if len(text) > 300:
                chapters.append(text)
    finally:
        if os.path.exists("temp.epub"):
            os.remove("temp.epub")

    return "\n\n".join(chapters)

# ---------------- DIVISÃO ----------------
def split_text(text):
    chunks = []
    size = 5000
    i = 0

    while i < len(text):
        part = text[i:i+size]
        chunks.append({
            "title": f"Parte {len(chunks)+1}",
            "content": part
        })
        i += size

    return chunks

# ---------------- TTS ----------------
async def run_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio(text, voice, filename, tags):
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
        audio.save()

        return True
    except Exception as e:
        print(e)
        return False

# ---------------- UI ----------------
st.title("🎧 Narrador.AI")

file = st.file_uploader("Envie seu arquivo", type=["pdf", "epub", "docx", "txt"])

book_title = st.text_input("Título", "Meu Livro")
book_author = st.text_input("Autor", "Autor")

voice_label = st.selectbox("Escolha a voz", list(VOICES.keys()))
voice = VOICES[voice_label]

# ---------------- PRÉVIA ----------------
if "preview_idx" not in st.session_state:
    st.session_state.preview_idx = 0

if st.button("▶️ Ouvir Prévia da Voz"):
    frases = [
        "Olá, este é um teste de voz do Narrador A I.",
        "Transformando textos em experiências incríveis de áudio.",
        "Agora você pode ouvir seus livros favoritos."
    ]

    texto = frases[st.session_state.preview_idx % len(frases)]
    st.session_state.preview_idx += 1

    asyncio.run(run_tts(texto, voice, "preview.mp3"))
    st.audio("preview.mp3")

# ---------------- PROCESSAMENTO ----------------
chapters = []

if file:
    if file.name.endswith(".pdf"):
        text = extract_text_pdf(file)
    elif file.name.endswith(".epub"):
        text = extract_text_epub(file)
    elif file.name.endswith(".docx"):
        text = extract_text_docx(file)
    elif file.name.endswith(".txt"):
        text = extract_text_txt(file)
    else:
        text = ""

    if text:
        chapters = split_text(text)
        st.success(f"{len(chapters)} partes identificadas")

# ---------------- GERAR ----------------
if chapters:
    if st.button("🚀 Gerar / Continuar"):
        progress = load_progress()

        for i, cap in enumerate(chapters):
            track = i + 1
            fname = f"{OUTPUT_DIR}/{track:03d}.mp3"

            if os.path.exists(fname):
                continue

            st.write(f"Gerando parte {track}...")

            tags = {
                "title": f"{book_title} - {cap['title']}",
                "author": book_author,
                "track": track
            }

            ok = generate_audio(cap["content"], voice, fname, tags)

            if ok:
                progress[str(track)] = True
                save_progress(progress)
            else:
                st.error(f"Erro na parte {track}")
                break

        st.success("Processo concluído ou pausado")

# ---------------- DOWNLOAD ----------------
st.write("## Downloads")

files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp3")])

for f in files:
    with open(os.path.join(OUTPUT_DIR, f), "rb") as audio:
        st.download_button(f"Baixar {f}", audio, f)

if files:
    if st.button("📦 Gerar ZIP"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            for f in files:
                z.write(os.path.join(OUTPUT_DIR, f), f)

        st.download_button("Baixar ZIP", buffer.getvalue(), "audiobook.zip")

# ---------------- LIMPAR ----------------
if st.button("🗑️ Limpar Tudo"):
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)

    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    st.rerun()
