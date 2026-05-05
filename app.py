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

    chapter_indices = []
    titles = []

    # ❌ palavras proibidas (não são capítulos)
    blacklist = [
        "agradecimentos",
        "créditos",
        "creditos",
        "dedicatória",
        "dedicatoria",
        "prefácio",
        "prefacio",
        "sumário",
        "sumario",
        "índice",
        "indice",
        "introdução",
        "introducao"
    ]

    # 🎯 padrões mais confiáveis
    patterns = [
        r'^\s*cap[ií]tulo\s+[ivxlcdm\d]+',
        r'^\s*chapter\s+\d+',
        r'^\s*parte\s+\d+',
        r'^\s*[ivxlcdm]+$',  # I, II, III...
    ]

    for i, line in enumerate(lines):
        clean = line.strip().lower()

        if len(clean) < 3:
            continue

        # ❌ ignora lixo
        if any(word in clean for word in blacklist):
            continue

        # 🎯 detecta padrão
        for pattern in patterns:
            if re.match(pattern, clean):
                
                # evita subtítulos próximos
                if chapter_indices and (i - chapter_indices[-1] < 15):
                    continue

                chapter_indices.append(i)
                titles.append(line.strip())
                break

    # 🎯 VALIDAÇÃO FINAL
    chapters = []

    if len(chapter_indices) >= 3:
        for idx in range(len(chapter_indices)):
            start = chapter_indices[idx]
            end = chapter_indices[idx+1] if idx+1 < len(chapter_indices) else len(lines)

            content = "\n".join(lines[start:end]).strip()

            # ignora capítulos muito pequenos (erro comum)
            if len(content) < 800:
                continue

            chapters.append({
                "title": titles[idx],
                "content": content
            })

    # 🔁 fallback inteligente
    if len(chapters) < 3:
        return split_text(text)

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

        chapters = []

        # 🔥 FUNÇÃO SEGURA PARA PEGAR ITEM DO SPINE
        def get_item(spine_item):
            if isinstance(spine_item, tuple):
                return book.get_item_with_id(spine_item[0])
            return book.get_item_with_id(spine_item)

        # 🔥 1. DETECÇÃO POR HEADINGS (estilo Kindle)
        for spine_item in book.spine:
            item = get_item(spine_item)

            if not item:
                continue

            soup = BeautifulSoup(item.get_content(), "html.parser")

            for tag in soup(["script", "style", "img", "svg"]):
                tag.decompose()

            headings = soup.find_all(["h1", "h2"])

            if headings:
                for h in headings:
                    title = h.get_text().strip()

                    content = []
                    for sibling in h.find_next_siblings():
                        if sibling.name in ["h1", "h2"]:
                            break
                        content.append(sibling.get_text(" ", strip=True))

                    text = " ".join(content).strip()

                    if len(text) > 500:
                        chapters.append({
                            "title": title,
                            "content": text
                        })

        # 🎯 VALIDAÇÃO
        if 3 <= len(chapters) <= 50:
            return chapters

        # 🔁 FALLBACK
        texts = []

        for spine_item in book.spine:
            item = get_item(spine_item)

            if item:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n").strip()

                if len(text) > 200:
                    texts.append(text)

        full_text = "\n\n".join(texts)

        return split_hybrid(full_text)

    except Exception as e:
        st.error(f"Erro ao processar EPUB: {str(e)}")
        return []

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
