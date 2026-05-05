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
import time
from io import BytesIO
from PIL import Image
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

ICON_URL = "https://raw.githubusercontent.com/jadirmoreirajunior/meu-leitor/main/narrador.ai.png"

# favicon
try:
    response = requests.get(ICON_URL)
    icon = Image.open(BytesIO(response.content))
except:
    icon = "🎧"

st.set_page_config(page_title=APP_NAME, page_icon=icon, layout="wide")

# HEADER
st.markdown(f"""
<div style="display:flex;align-items:center;gap:12px;margin-bottom:5px;">
    <img src="{ICON_URL}" width="60" style="border-radius:12px;">
    <h1 style="margin:0;">Narrador.AI</h1>
</div>

<p style="margin-top:0; color: gray;">
Transforme seus livros em audiobooks com vozes neurais de alta qualidade.
Envie arquivos PDF, EPUB, DOCX ou TXT — ou escreva seu próprio texto — e gere áudios automaticamente organizados por capítulos.
Se o sistema conseguir identificar títulos e capítulos, possivelmente fará arquivos de áudio separado de acordo com estes capítulos, se não conseguir identificar, irá calcular tamanho médio para criação de audiobokk separado por partes.
Se a geração de um áudiobook parar em algum momento, por instabilidade da internet ou por ter minimizado o navegador, clique novamente no botão Gerar, possivelmente ele continuará a geração de áudio a partir do capítulo ou parte onde parou.
</p>
""", unsafe_allow_html=True)

OUTPUT_DIR = "out"
PROGRESS_FILE = "progress.json"

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# SESSION STATE
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
    "Fabio (Masculino - BR)": "pt-BR-FabioNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural"
}

# PROGRESSO
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

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

def extract_text_epub(file):
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())

    chapters = []

    try:
        book = epub.read_epub("temp.epub")

        toc = book.toc
        main_items = []

        for item in toc:
            if isinstance(item, tuple):
                main_items.append(item[0])
            else:
                main_items.append(item)

        # 🔥 tenta usar TOC
        for idx, item in enumerate(main_items):
            try:
                doc = book.get_item_with_href(item.href)
                soup = BeautifulSoup(doc.get_content(), "html.parser")

                for tag in soup(["script", "style", "img", "svg"]):
                    tag.decompose()

                text = soup.get_text(separator="\n").strip()

                if len(text) > 200:
                    title = item.title.strip() if item.title else f"Capítulo {idx+1}"

                    chapters.append({
                        "title": title,
                        "content": text
                    })
            except:
                continue

        # 🔥 valida TOC (aqui resolve seu problema)
        total_chars = sum(len(c["content"]) for c in chapters)

        if len(chapters) < 3 or total_chars < 10000:
            texts = []
            for item in book.get_items_of_type(ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text = soup.get_text(separator="\n").strip()
                if len(text) > 200:
                    texts.append(text)

            full_text = "\n\n".join(texts)
            return split_by_chapters(full_text)

        return chapters

    finally:
        if os.path.exists("temp.epub"):
            os.remove("temp.epub")

# DETECÇÃO INTELIGENTE
def split_by_chapters(text):
    if isinstance(text, list):
        text = "\n\n".join(
            [item["content"] if isinstance(item, dict) else str(item) for item in text]
        )

    lines = text.split("\n")

    chapter_indices = []
    titles = []

    patterns = [
        r'^\s*cap[ií]tulo\s+[ivxlcdm\d]+',
        r'^\s*chapter\s+\d+',
        r'^\s*parte\s+\d+',
        r'^\s*[ivxlcdm]+$',
        r'^[A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]{8,}$'
    ]

    for i, line in enumerate(lines):
        clean = line.strip()

        if len(clean) < 5:
            continue

        for pattern in patterns:
            if re.match(pattern, clean, re.IGNORECASE):
                if chapter_indices and (i - chapter_indices[-1] < 10):
                    continue

                chapter_indices.append(i)
                titles.append(clean)
                break

    if len(chapter_indices) >= 3:
        chapters = []

        for idx in range(len(chapter_indices)):
            start = chapter_indices[idx]
            end = chapter_indices[idx+1] if idx+1 < len(chapter_indices) else len(lines)

            content = "\n".join(lines[start:end]).strip()

            if len(content) < 500:
                continue

            chapters.append({
                "title": titles[idx],
                "content": content
            })

        if len(chapters) >= 3:
            return chapters

    return split_text(text)

# FALLBACK
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

# TTS
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
        st.error(str(e))
        return False

# UI
input_mode = st.radio("Modo de entrada:", ["Arquivo", "Texto Manual"], horizontal=True)

book_title = st.text_input("Título", "Meu Livro")
book_author = st.text_input("Autor", "Autor")

voice_label = st.selectbox("Escolha a voz", list(VOICES.keys()))
voice = VOICES[voice_label]

# PRÉVIA
if st.button("▶️ Ouvir Prévia"):
    frases = [
        "Olá, este é um teste de voz.",
        "Transformando textos em áudio.",
        "Seu audiobook começa aqui."
    ]
    texto = frases[st.session_state.preview_idx % len(frases)]
    st.session_state.preview_idx += 1

    asyncio.run(run_tts(texto, voice, "preview.mp3"))
    st.audio("preview.mp3")

# ENTRADA
file = None

if input_mode == "Arquivo":
    file = st.file_uploader("Envie seu arquivo", type=["pdf", "epub", "docx", "txt"])

if file:
    text = None

    if file.name.endswith(".pdf"):
        text = extract_text_pdf(file)

    elif file.name.endswith(".epub"):
        result = extract_text_epub(file)

        if isinstance(result, list) and isinstance(result[0], dict):
            st.session_state.chapters = result
            st.success(f"{len(result)} capítulos identificados")
        else:
            text = result

    elif file.name.endswith(".docx"):
        text = extract_text_docx(file)

    elif file.name.endswith(".txt"):
        text = extract_text_txt(file)

    if text:
        st.session_state.chapters = split_by_chapters(text)
        st.success(f"{len(st.session_state.chapters)} partes identificadas")

else:
    manual_text = st.text_area("Digite ou cole seu texto aqui:", height=250)

    if st.button("📝 Processar Texto"):
        if manual_text.strip():
            st.session_state.chapters = split_by_chapters(manual_text)
            st.success(f"{len(st.session_state.chapters)} partes identificadas")

# VISUALIZAÇÃO
if st.session_state.chapters:
    st.write("## 📚 Capítulos identificados")
    with st.expander("Ver lista"):
        for i, cap in enumerate(st.session_state.chapters):
            st.write(f"{i+1:02d} - {cap['title']}")

# GERAÇÃO
if st.session_state.chapters:
if st.button("🚀 Gerar / Continuar"):
    progress = load_progress()

    with st.spinner("🎧 Gerando audiobook... isso pode levar alguns minutos"):
        for i, cap in enumerate(st.session_state.chapters):
            track = i + 1
            safe_title = re.sub(r'[\\/*?:"<>|]', "", cap['title'])
            fname = f"{OUTPUT_DIR}/{track:03d} - {safe_title}.mp3"

            if os.path.exists(fname):
                continue

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

    st.success("✅ Geração concluída!")
    st.session_state.chapters = []

# DOWNLOAD
st.write("## Downloads")

files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.endswith(".mp3")])

for f in files:
    with open(os.path.join(OUTPUT_DIR, f), "rb") as audio:
        st.download_button(f"Baixar {f}", audio, f)

if files:
if st.button("📦 Gerar ZIP"):
    with st.spinner("📦 Gerando arquivo ZIP..."):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            for f in files:
                z.write(os.path.join(OUTPUT_DIR, f), f)

    st.success("✅ ZIP pronto!")
    st.download_button("Baixar ZIP", buffer.getvalue(), "audiobook.zip")

# LIMPAR
if st.button("🗑️ Limpar Tudo"):
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
    st.rerun()
