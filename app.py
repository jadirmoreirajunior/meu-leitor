import streamlit as st
import edge_tts
import asyncio
import os
import json
import re
import hashlib
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TRCK

# =========================
# CONFIG
# =========================
APP_NAME = "Narrador.AI PRO"
OUTPUT_DIR = Path("out")
CACHE_DIR = Path(".cache")

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

VOICES = {
    "Francisca (BR)": "pt-BR-FranciscaNeural",
    "Antonio (BR)": "pt-BR-AntonioNeural",
    "Andrew": "en-US-AndrewMultilingualNeural",
}

# =========================
# UTILS
# =========================

def hash_text(text: str):
    return hashlib.md5(text.encode()).hexdigest()

def normalize_text(text: str):
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'([.!?])([A-Za-z])', r'\1 \2', text)
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

def split_text_smart(text):
    parts = split_sentences(text)
    return [
        {"title": f"Parte {i+1}", "content": p}
        for i, p in enumerate(parts)
    ]

# =========================
# CACHE PROGRESS
# =========================

def get_progress_file(book_id):
    return CACHE_DIR / f"{book_id}.json"

def load_progress(book_id):
    f = get_progress_file(book_id)
    if f.exists():
        return json.loads(f.read_text())
    return {}

def save_progress(book_id, data):
    f = get_progress_file(book_id)
    f.write_text(json.dumps(data))

# =========================
# TTS ENGINE (ROBUSTO)
# =========================

async def tts_generate(text, voice, output):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output)

def generate_with_retry(text, voice, filename, retries=3):
    for i in range(retries):
        try:
            asyncio.run(tts_generate(text, voice, filename))
            return True
        except Exception as e:
            if i == retries - 1:
                return False

def tag_audio(file, title, author, track):
    audio = MP3(file, ID3=ID3)
    try:
        audio.add_tags()
    except:
        pass

    audio.tags.add(TIT2(encoding=3, text=title))
    audio.tags.add(TPE1(encoding=3, text=author))
    audio.tags.add(TRCK(encoding=3, text=str(track)))
    audio.save()

# =========================
# STREAMLIT UI
# =========================

st.set_page_config(page_title=APP_NAME)
st.title("🎧 Narrador.AI PRO")

book_title = st.text_input("Título do Livro")
book_author = st.text_input("Autor")

voice_label = st.selectbox("Voz", list(VOICES.keys()))
voice = VOICES[voice_label]

text = st.text_area("Cole seu texto aqui", height=300)

if st.button("Processar"):
    clean = normalize_text(text)
    st.session_state.parts = split_text_smart(clean)
    st.success(f"{len(st.session_state.parts)} partes criadas")

# =========================
# GERAR
# =========================

if "parts" in st.session_state:

    if st.button("🚀 Gerar Audiobook"):

        book_id = hash_text(book_title + book_author)
        progress = load_progress(book_id)

        progress_bar = st.progress(0)

        for i, part in enumerate(st.session_state.parts):

            track = i + 1
            fname = OUTPUT_DIR / f"{track:03d}.mp3"

            if str(track) in progress:
                continue

            ok = generate_with_retry(
                part["content"],
                voice,
                str(fname)
            )

            if ok:
                tag_audio(
                    str(fname),
                    f"{book_title} - {part['title']}",
                    book_author,
                    track
                )

                progress[str(track)] = True
                save_progress(book_id, progress)

            progress_bar.progress((i+1)/len(st.session_state.parts))

        st.success("✅ Audiobook gerado!")

# =========================
# DOWNLOAD
# =========================

files = sorted(OUTPUT_DIR.glob("*.mp3"))

for f in files:
    with open(f, "rb") as audio:
        st.download_button(f"Baixar {f.name}", audio, f.name)

# =========================
# LIMPAR
# =========================

if st.button("🗑 Limpar"):
    for f in OUTPUT_DIR.glob("*"):
        f.unlink()
    for f in CACHE_DIR.glob("*"):
        f.unlink()
    st.rerun()
