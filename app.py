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
# UI MOBILE STYLE
# =========================

st.set_page_config(page_title=APP_NAME, layout="wide")

st.markdown("""
<style>
.block-container {
    padding-top: 1rem;
    padding-bottom: 4rem;
}
button {
    width: 100%;
    border-radius: 12px;
    height: 50px;
    font-size: 16px;
}
</style>
""", unsafe_allow_html=True)

st.title("🎧 Narrador.AI PRO")

# =========================
# UTILS
# =========================

def hash_book(title, author):
    return hashlib.md5((title + author).encode()).hexdigest()

def normalize_text(text):
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

def create_parts(text):
    parts = split_sentences(text)
    return [
        {"title": f"Parte {i+1}", "content": p}
        for i, p in enumerate(parts)
    ]

# =========================
# CACHE
# =========================

def progress_file(book_id):
    return CACHE_DIR / f"{book_id}.json"

def load_progress(book_id):
    f = progress_file(book_id)
    if f.exists():
        return json.loads(f.read_text())
    return {}

def save_progress(book_id, data):
    progress_file(book_id).write_text(json.dumps(data))

# =========================
# SSML
# =========================

def apply_ssml(text, voice):
    text = text.replace("\n", " ")
    return f"""
<speak>
    <voice name="{voice}">
        <prosody rate="0.95" pitch="+0%">
            {text}
        </prosody>
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
    ssml = apply_ssml(text, voice)

    try:
        asyncio.run(tts_generate(ssml, voice, output))
        return True
    except:
        return False

# =========================
# TAG + CAPA
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
# TABS
# =========================

tab1, tab2, tab3 = st.tabs(["📚 Livro", "🎧 Player", "⚙️ Config"])

# =========================
# TAB LIVRO
# =========================

with tab1:
    book_title = st.text_input("Título do Livro")
    book_author = st.text_input("Autor")

    voice_label = st.selectbox("Voz", list(VOICES.keys()))
    voice = VOICES[voice_label]

    cover = st.file_uploader("Capa do livro", type=["jpg", "png"])

    text = st.text_area("Cole seu texto aqui", height=250)

    if st.button("📖 Processar Texto"):
        if text.strip():
            clean = normalize_text(text)
            st.session_state.parts = create_parts(clean)
            st.success(f"{len(st.session_state.parts)} partes criadas")

# =========================
# GERAR
# =========================

    if "parts" in st.session_state:

        if st.button("🚀 Gerar Audiobook"):

            book_id = hash_book(book_title, book_author)
            progress = load_progress(book_id)

            progress_bar = st.progress(0)

            for i, part in enumerate(st.session_state.parts):
                track = i + 1
                fname = OUTPUT_DIR / f"{track:03d}.mp3"

                if str(track) in progress:
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

                    progress[str(track)] = True
                    save_progress(book_id, progress)

                progress_bar.progress((i+1)/len(st.session_state.parts))

            st.success("✅ Audiobook gerado!")

# =========================
# PLAYER
# =========================

with tab2:
    st.subheader("🎧 Player")

    files = sorted(OUTPUT_DIR.glob("*.mp3"))

    if not files:
        st.info("Nenhum áudio ainda.")
    else:
        for f in files:
            st.markdown(f"**{f.name}**")
            st.audio(str(f))

# =========================
# CONFIG
# =========================

with tab3:
    st.subheader("⚙️ Configurações")

    if st.button("🗑 Limpar tudo"):
        for f in OUTPUT_DIR.glob("*"):
            f.unlink()
        for f in CACHE_DIR.glob("*"):
            f.unlink()
        st.rerun()
