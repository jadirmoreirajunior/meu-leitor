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
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

APP_NAME = "Narrador.AI"

OUTPUT_DIR = "out"
PROGRESS_FILE = "progress.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

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

def split_text(text):
    chunks = []
    size = 5000
    i = 0
    while i < len(text):
        part = text[i:i+size]
        chunks.append({"title": f"Parte {len(chunks)+1}", "content": part})
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
st.title(APP_NAME)

file = st.file_uploader("Envie seu PDF", type=["pdf"])

book_title = st.text_input("Título", "Meu Livro")
book_author = st.text_input("Autor", "Autor")
voice = "pt-BR-FranciscaNeural"

if file:
    text = extract_text_pdf(file)
    chapters = split_text(text)

    st.success(f"{len(chapters)} partes detectadas")

    if st.button("🚀 Gerar / Continuar"):
        progress = load_progress()

        for i, cap in enumerate(chapters):
            track = i + 1
            fname = f"{OUTPUT_DIR}/{track:03d}.mp3"

            # 🔥 PULA SE JÁ EXISTE
            if os.path.exists(fname):
                continue

            st.write(f"Gerando {track}...")

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
                st.error(f"Erro no capítulo {track}")
                break

        st.success("Processo finalizado ou pausado")

# ---------------- DOWNLOAD ----------------
st.write("## Downloads")

files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp3")])

for f in files:
    with open(os.path.join(OUTPUT_DIR, f), "rb") as audio:
        st.download_button(f"Baixar {f}", audio, f)

# ZIP
if files:
    if st.button("📦 Gerar ZIP"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            for f in files:
                z.write(os.path.join(OUTPUT_DIR, f), f)
        st.download_button("Baixar ZIP", buffer.getvalue(), "livro.zip")

# ---------------- LIMPAR ----------------
if st.button("🗑️ Limpar Tudo"):
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    st.rerun()
