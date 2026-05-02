import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
import io
import shutil
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

# Tenta importar o suporte a Word
try:
    import docx
    WORD_SUPPORT = True
except ImportError:
    WORD_SUPPORT = False

# --- CONFIGURAÇÃO DE IDENTIDADE E PWA ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://jadirmoreirajunior.github.io/meu-leitor/narrador.ai.png"

st.set_page_config(page_title=APP_NAME, page_icon=ICON_URL, layout="wide")

# 1. INICIALIZAÇÃO DA MEMÓRIA (SESSION STATE)
if "zip_buffer" not in st.session_state:
    st.session_state.zip_buffer = None
if "book_ready" not in st.session_state:
    st.session_state.book_ready = False
if "frase_idx" not in st.session_state:
    st.session_state.frase_idx = 0
if "chapters_generated" not in st.session_state:
    st.session_state.chapters_generated = []

# Injeção de CSS para Mobile-First (Sem Sidebar obrigatória)
st.markdown(f"""
    <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{ background-color: rgba(0,0,0,0); height: 3rem; }}
        
        /* Ajuste da Logo Centralizada e Menor */
        .logo-container {{
            display: flex; justify-content: center; margin-bottom: 10px;
        }}
        .logo-img {{
            width: 120px; border-radius: 20px; box-shadow: 0px 4px 15px rgba(0,0,0,0.3);
        }}

        .main .block-container {{
            max-width: 800px; padding-top: 1rem; padding-bottom: 2rem;
        }}
        
        /* Botões Arredondados */
        .stButton>button {{
            width: 100%; border-radius: 20px; height: 3em;
            background-color: #0e1117; color: white; border: 1px solid #30363d; font-weight: bold;
        }}
        .stButton>button:hover {{ border-color: #f0ad4e; color: #f0ad4e; }}
        
        /* Inputs */
        .stTextInput, .stSelectbox, .stTextArea, .stFileUploader {{
            border-radius: 12px !important;
        }}
    </style>
    <meta property="og:title" content="{APP_NAME}">
    <meta property="og:image" content="{ICON_URL}">
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

# --- FUNÇÕES DE EXTRAÇÃO ---
def extract_text_docx(file):
    if not WORD_SUPPORT: return "Erro: python-docx não instalado."
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_text_txt(file):
    return file.getvalue().decode("utf-8")

def extract_text_pdf(file):
    reader = PdfReader(file)
    return "\n".join([page.extract_text() or "" for page in reader.pages])

def extract_text_epub(file):
    with open("temp.epub", "wb") as f: f.write(file.getbuffer())
    try:
        book = epub.read_epub("temp.epub")
        chapters = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            for tag in soup(['img', 'svg']): tag.decompose()
            text = soup.get_text(separator="\n")
            if text.strip() and len(text) > 300:
                chapters.append({"title": f"Parte {len(chapters)+1:02d}", "content": text.strip()})
        return chapters, "EPUB"
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
            chapters.append({"title": matches[i].group().strip(), "content": text[start:end].strip()})
        return chapters, "Regex"
    
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
    return chunks, "Divisão Automática"

async def run_edge_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio(text, voice, filename, tags):
    text = text.replace('\xa0', ' ').strip()
    if not text: return False
    try:
        asyncio.run(run_edge_tts(text, voice, filename))
        if os.path.exists(filename):
            audio = MP3(filename, ID3=ID3)
            try: audio.add_tags()
            except: pass
            audio.tags.add(TIT2(encoding=3, text=tags['title']))
            audio.tags.add(TPE1(encoding=3, text=tags['author']))
            audio.tags.add(TRCK(encoding=3, text=str(tags['track'])))
            if tags.get('year'): audio.tags.add(TYER(encoding=3, text=str(tags['year'])))
            audio.save()
            return True
    except: return False

# --- INTERFACE PRINCIPAL (CORPO DA PÁGINA) ---
st.markdown(f'<div class="logo-container"><img src="{ICON_URL}" class="logo-img"></div>', unsafe_allow_html=True)
st.markdown("<h2 style='text-align: center; margin-bottom: 0;'>Narrador.AI</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: gray;'>Audiobooks neurais para PDF, EPUB, DOCX e TXT</p>", unsafe_allow_html=True)

# Bloco de Configuração Central
with st.container():
    st.write("---")
    input_method = st.radio("Escolha a entrada:", ["Arquivo", "Texto Manual"], horizontal=True)
    
    col1, col2 = st.columns(2)
    with col1:
        book_title = st.text_input("Título do Livro", "Meu Audiobook")
        book_author = st.text_input("Autor", "Narrador.AI")
    with col2:
        book_year = st.text_input("Ano (Opcional)", "")
        voice_label = st.selectbox("Escolha a Voz", list(VOICES.keys()))

    if input_method == "Arquivo":
        file = st.file_uploader("Arraste ou selecione o arquivo", type=["pdf", "epub", "docx", "txt"])
    else:
        manual_text = st.text_area("Cole seu texto abaixo:", height=250)

    # Botões de Ação Lado a Lado
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("▶️ Ouvir Prévia"):
            frases = ["Preparado para dar vida a mais uma história?", "Sua biblioteca, agora em áudio."]
            preview_text = frases[st.session_state.frase_idx % len(frases)]
            st.session_state.frase_idx += 1
            asyncio.run(run_edge_tts(preview_text, VOICES[voice_label], "preview.mp3"))
            st.audio("preview.mp3")
    with btn_col2:
        if st.button("🗑️ Limpar Tudo"):
            st.session_state.zip_buffer = None
            st.session_state.book_ready = False
            st.session_state.chapters_generated = []
            if os.path.exists("out"): shutil.rmtree("out")
            st.rerun()

# --- LÓGICA DE GERAÇÃO ---
chapters = []
if input_method == "Arquivo" and file:
    if file.name.endswith(".pdf"): chapters, m = split_text_regex(extract_text_pdf(file))
    elif file.name.endswith(".epub"): chapters, m = extract_text_epub(file)
    elif file.name.endswith(".docx"): chapters, m = split_text_regex(extract_text_docx(file))
    elif file.name.endswith(".txt"): chapters, m = split_text_regex(extract_text_txt(file))
elif input_method == "Texto Manual" and manual_text:
    chapters, m = split_text_regex(manual_text)

if chapters:
    st.success(f"Identificadas {len(chapters)} partes.")
    if st.button("🚀 INICIAR GERAÇÃO COMPLETA"):
        st.session_state.chapters_generated = []
        progress = st.progress(0)
        status = st.empty()
        if not os.path.exists("out"): os.makedirs("out")
        
        for i, cap in enumerate(chapters):
            track = i + 1
            fname = f"out/{track:03d}.mp3"
            status.text(f"Gerando: {cap['title']}")
            tags = {'title': f"{book_title} - {cap['title']}", 'author': book_author, 'track': track, 'year': book_year}
            if generate_audio(cap['content'], VOICES[voice_label], fname, tags):
                with open(fname, "rb") as f:
                    st.session_state.chapters_generated.append({"title": cap['title'], "data": f.read(), "track": track})
            progress.progress(track / len(chapters))
        
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            for item in st.session_state.chapters_generated:
                zf.writestr(f"{item['track']:03d}.mp3", item['data'])
        st.session_state.zip_buffer = buffer.getvalue()
        st.session_state.book_ready = True
        st.success("Tudo pronto!")

# --- ÁREA DE DOWNLOADS ---
if st.session_state.chapters_generated:
    st.subheader("📥 Downloads")
    for item in st.session_state.chapters_generated:
        with st.expander(f"Capítulo {item['track']}: {item['title']}"):
            st.download_button("Baixar MP3", item["data"], f"{item['track']:03d}.mp3", key=f"dl_{item['track']}")

if st.session_state.book_ready:
    st.write("---")
    st.download_button("📥 BAIXAR LIVRO COMPLETO (.ZIP)", st.session_state.zip_buffer, f"{book_title}.zip")
