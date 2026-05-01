import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
import io
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

# --- CONFIGURAÇÃO DE IDENTIDADE E PWA ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://jadirmoreirajunior.github.io/meu-leitor/narrador.ai.png"

st.set_page_config(page_title=APP_NAME, page_icon=ICON_URL, layout="wide")

# 1. INICIALIZAÇÃO DA MEMÓRIA
if "zip_buffer" not in st.session_state:
    st.session_state.zip_buffer = None
if "book_ready" not in st.session_state:
    st.session_state.book_ready = False
if "frase_idx" not in st.session_state:
    st.session_state.frase_idx = 0

# Injeção de CSS e META TAGS para Redes Sociais (WhatsApp)
st.markdown(f"""
    <head>
        <!-- Open Graph / Facebook / WhatsApp -->
        <meta property="og:type" content="website">
        <meta property="og:title" content="{APP_NAME}">
        <meta property="og:description" content="Transforme seus arquivos PDF e EPUB em audiobooks personalizados.">
        <meta property="og:image" content="{ICON_URL}">
        <meta property="og:image:width" content="1200">
        <meta property="og:image:height" content="630">

        <!-- Twitter -->
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="{APP_NAME}">
        <meta name="twitter:description" content="Transforme seus arquivos PDF e EPUB em audiobooks personalizados.">
        <meta name="twitter:image" content="{ICON_URL}">

        <link rel="icon" href="{ICON_URL}">
        <link rel="apple-touch-icon" href="{ICON_URL}">
    </head>
    <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{ background-color: rgba(0,0,0,0); height: 3rem; }}

        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:first-child {{
            display: flex; justify-content: center;
        }}
        
        .main .block-container {{
            max-width: 900px; padding-top: 2rem; padding-bottom: 2rem;
        }}

        .stButton>button {{
            width: 100%; border-radius: 20px; height: 3em;
            background-color: #0e1117; color: white; border: 1px solid #30363d; font-weight: bold;
        }}
        .stButton>button:hover {{ border-color: #f0ad4e; color: #f0ad4e; }}
    </style>
    """, unsafe_allow_html=True)

# --- CONFIGURAÇÕES DE VOZ ---
VOICES = {
    "Francisca (Feminina - BR)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino - BR)": "pt-BR-AntonioNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Brian (Multilingue)": "en-US-BrianMultilingualNeural",
    "Ava (Multilingue)": "en-US-AvaMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural",
    "Brenda (Feminina - BR)": "pt-BR-BrendaNeural",
    "Donato (Masculino - BR)": "pt-BR-DonatoNeural",
    "Fabio (Masculino - BR)": "pt-BR-FabioNeural"
}

# --- FUNÇÕES TÉCNICAS ---
def flatten_toc(toc):
    for item in toc:
        if isinstance(item, tuple):
            yield item[0]
            yield from flatten_toc(item[1])
        else: yield item

def split_epub_by_toc(book):
    chapters = []
    try:
        for item in flatten_toc(book.toc):
            try:
                title = item.title
                content_item = book.get_item_with_href(item.href)
                if not content_item: continue
                soup = BeautifulSoup(content_item.get_content(), 'html.parser')
                for tag in soup(['img', 'svg']): tag.decompose()
                text = soup.get_text(separator="\n")
                if text.strip() and len(text) > 300:
                    chapters.append({"title": title.strip(), "content": text.strip()})
            except: continue
    except: return []
    return chapters

def extract_text_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        content = page.extract_text()
        if content: text += content + "\n"
    return text

def extract_text_epub(file):
    with open("temp.epub", "wb") as f: f.write(file.getbuffer())
    try:
        book = epub.read_epub("temp.epub")
        toc_chapters = split_epub_by_toc(book)
        if len(toc_chapters) > 2: return toc_chapters, "Sumário Interno (TOC)"
        texts = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            for tag in soup(['img', 'svg']): tag.decompose()
            texts.append(soup.get_text(separator="\n"))
        return "\n\n".join(texts), "Texto Bruto EPUB"
    finally:
        if os.path.exists("temp.epub"): os.remove("temp.epub")

def split_text_regex(text):
    pattern = r'^\s*(?:Capítulo|Chapter|Parte|Part)\s+(?:[IVXLCDM]+|\d+)'
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.IGNORECASE))
    if len(matches) > 2:
        chapters = []
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            title = matches[i].group().strip()
            content = text[start:end].strip()
            if len(content) > 300: chapters.append({"title": title, "content": content})
        if len(chapters) > 1: return chapters, "Padrões de Texto (Regex)"
    
    chunks = []
    max_chars = 5000
    curr_idx = 0
    while curr_idx < len(text):
        end_idx = curr_idx + max_chars
        if end_idx < len(text):
            last_p = text.rfind('.', curr_idx, end_idx)
            if last_p != -1 and last_p > curr_idx + 2000: end_idx = last_p + 1
        chunk = text[curr_idx:end_idx].strip()
        if chunk: chunks.append({"title": f"Parte {len(chunks)+1:03d}", "content": chunk})
        curr_idx = end_idx
    return chunks, "Divisão Automática (Blocos)"

# --- MOTOR DE ÁUDIO ---
async def run_edge_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio(text, voice, filename, tags):
    text = text.replace('\xa0', ' ').strip()
    if not text: return False
    success = False
    for attempt in range(3):
        try:
            asyncio.run(run_edge_tts(text, voice, filename))
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                success = True
                break
        except:
            if attempt == 2:
                try:
                    gTTS(text=text[:5000], lang='pt').save(filename)
                    success = True
                except: return False
    
    if success:
        try:
            audio = MP3(filename, ID3=ID3)
            try: audio.add_tags()
            except: pass
            audio.tags.add(TIT2(encoding=3, text=tags['title']))
            audio.tags.add(TPE1(encoding=3, text=tags['author']))
            audio.tags.add(TRCK(encoding=3, text=str(tags['track'])))
            if tags['year']: audio.tags.add(TYER(encoding=3, text=str(tags['year'])))
            audio.save()
        except: pass
    return success

def play_voice_preview(voice_id):
    frases = [
        "Preparado para dar vida a mais uma história? Eu sou uma das vozes disponíveis para sua narração.",
        "Estou pronto para transformar seus livros favoritos em uma experiência auditiva incrível.",
        "A leitura engrandece a alma, e eu estou aqui para dar voz aos seus textos preferidos.",
        "Com tecnologia neural, minha narração busca ser o mais natural e agradável possível para seus ouvidos.",
        "Me escolhe, me escolhe!!!"
    ]
    preview_text = frases[st.session_state.frase_idx]
    st.session_state.frase_idx = (st.session_state.frase_idx + 1) % len(frases)
    p_file = "voice_preview.mp3"
    try:
        asyncio.run(run_edge_tts(preview_text, voice_id, p_file))
        return p_file
    except: return None

# --- INTERFACE ---
st.title(f"🎧 {APP_NAME}")
st.markdown("#### Transforme seus arquivos PDF e EPUB em audiobooks personalizados.")
st.write("---")

with st.sidebar:
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c: st.image(ICON_URL, use_container_width=True)
    st.header("Configurações")
    file = st.file_uploader("Livro (PDF ou EPUB)", type=["pdf", "epub"])
    
    def reset_preview_idx():
        if "frase_idx" in st.session_state: st.session_state.frase_idx = (st.session_state.frase_idx + 1) % 5

    voice_label = st.selectbox("Voz", list(VOICES.keys()), on_change=reset_preview_idx)
    
    if st.button("▶️ Demonstração da voz"):
        p_path = play_voice_preview(VOICES[voice_label])
        if p_path and os.path.exists(p_path):
            st.audio(p_path, format="audio/mp3")
            os.remove(p_path)
        else: st.error("Erro ao gerar prévia.")

    book_title = st.text_input("Título", "Meu Audiobook")
    book_author = st.text_input("Autor", "Desconhecido")
    book_year = st.text_input("Ano", "")

# --- PROCESSAMENTO ---
if file:
    with st.spinner("Analisando livro..."):
        if file.name.endswith(".pdf"):
            chapters, method = split_text_regex(extract_text_pdf(file))
        else:
            res, method = extract_text_epub(file)
            if isinstance(res, list): chapters = res
            else: chapters, m2 = split_text_regex(res); method = f"{method} + {m2}"

    st.info(f"**Método:** {method} | **Partes:** {len(chapters)}")
    
    st.write("### 📋 Capítulos Identificados")
    chapter_status_container = st.container()

    if st.button("🚀 INICIAR GERAÇÃO COMPLETA"):
        st.session_state.zip_buffer = None
        st.session_state.book_ready = False
        
        progress = st.progress(0)
        status = st.empty()
        if not os.path.exists("out"): os.makedirs("out")
        files = []
        
        for i, cap in enumerate(chapters):
            track = i + 1
            fname = f"out/{track:03d}.mp3"
            status.markdown(f"🎙️ **Convertendo:** {cap['title']} ({track}/{len(chapters)})")
            
            tags = {'title': f"{book_title} - {cap['title']}", 'author': book_author, 'track': track, 'year': book_year}
            
            if generate_audio(cap['content'], VOICES[voice_label], fname, tags):
                files.append(fname)
                with chapter_status_container:
                    c1, c2 = st.columns([0.75, 0.25])
                    c1.write(f"✅ {cap['title']}")
                    with open(fname, "rb") as f:
                        c2.download_button(label="📥 Baixar", data=f.read(), file_name=f"{track:03d}.mp3", key=f"dl_{track}")
            
            progress.progress(track / len(chapters))
        
        if files:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as zf:
                for f in files: zf.write(f, os.path.basename(f))
            st.session_state.zip_buffer = buffer.getvalue()
            st.session_state.book_ready = True
            st.success("✅ Geração concluída!")
            for f in files: 
                if os.path.exists(f): os.remove(f)

# --- DOWNLOAD PERSISTENTE (ZIP) ---
if st.session_state.book_ready and st.session_state.zip_buffer:
    st.write("---")
    st.download_button(
        label="📥 BAIXAR LIVRO COMPLETO (.ZIP)",
        data=st.session_state.zip_buffer,
        file_name=f"{book_title.replace(' ', '_')}.zip",
        mime="application/zip"
    )
    if st.button("🗑️ Limpar geração"):
        st.session_state.zip_buffer = None
        st.session_state.book_ready = False
        st.rerun()
