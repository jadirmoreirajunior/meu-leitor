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

# Suporte a Word
try:
    import docx
    WORD_SUPPORT = True
except ImportError:
    WORD_SUPPORT = False

# --- CONFIGURAÇÃO DE IDENTIDADE ---
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
if "chapters_generated" not in st.session_state:
    st.session_state.chapters_generated = []

# --- VOZES ---
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

# CSS para Cabeçalho e Estilo
st.markdown(f"""
    <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{ background-color: rgba(0,0,0,0); height: 3rem; }}
        .header-container {{ display: flex; align-items: center; gap: 15px; margin-bottom: 10px; }}
        .header-logo {{ width: 70px; border-radius: 12px; }}
        .header-text h1 {{ margin: 0; font-size: 1.6rem; }}
        .header-text p {{ margin: 0; font-size: 0.9rem; color: gray; }}
        .main .block-container {{ max-width: 900px; padding-top: 1rem; padding-bottom: 2rem; }}
        .stButton>button {{ width: 100%; border-radius: 20px; height: 3em; background-color: #0e1117; color: white; border: 1px solid #30363d; font-weight: bold; }}
        .stButton>button:hover {{ border-color: #f0ad4e; color: #f0ad4e; }}
    </style>
    """, unsafe_allow_html=True)

# --- FUNÇÕES TÉCNICAS ---

def extract_text_docx(file):
    if not WORD_SUPPORT: return "Erro: biblioteca docx ausente."
    doc = docx.Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def extract_text_txt(file):
    return file.getvalue().decode("utf-8", errors="ignore")

def extract_text_pdf(file):
    reader = PdfReader(file)
    return "\n".join([page.extract_text() or "" for page in reader.pages])

def extract_text_epub(file):
    """Versão simplificada para evitar KeyError em arquivos com erro de estrutura"""
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())
    chapters = []
    try:
        book = epub.read_epub("temp.epub")
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for tag in soup(['img', 'svg', 'style', 'script']): tag.decompose()
                text = soup.get_text(separator="\n").strip()
                if len(text) > 200:
                    chapters.append({"title": f"Parte {len(chapters)+1:02d}", "content": text})
            except: continue
        return chapters, "EPUB (Leitura Linear)"
    except Exception as e:
        return [], f"Erro na leitura: {str(e)}"
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
    return chunks, "Automática"

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

# --- INTERFACE ---

st.markdown(f"""
    <div class="header-container">
        <img src="{ICON_URL}" class="header-logo">
        <div class="header-text">
            <h1>{APP_NAME}</h1>
            <p>Audiobooks neurais para PDF, EPUB, DOCX e TXT</p>
        </div>
    </div>
""", unsafe_allow_html=True)

st.write("---")
input_method = st.radio("Método de Entrada:", ["Arquivo", "Texto Manual"], horizontal=True)

c_info1, c_info2, c_info3 = st.columns([2, 1, 1.5])
with c_info1:
    book_title = st.text_input("Título", "Meu Audiobook")
with c_info2:
    book_year = st.text_input("Ano", "")
with c_info3:
    voice_label = st.selectbox("Voz", list(VOICES.keys()))

book_author = st.text_input("Autor", "Narrador.AI")

chapters = []
if input_method == "Arquivo":
    file = st.file_uploader("Upload", type=["pdf", "epub", "docx", "txt"])
    if file:
        with st.status("Processando arquivo...", expanded=True) as status_leitura:
            if file.name.endswith(".pdf"): chapters, _ = split_text_regex(extract_text_pdf(file))
            elif file.name.endswith(".epub"): chapters, _ = extract_text_epub(file)
            elif file.name.endswith(".docx"): chapters, _ = split_text_regex(extract_text_docx(file))
            elif file.name.endswith(".txt"): chapters, _ = split_text_regex(extract_text_txt(file))
            status_leitura.update(label="Concluído!", state="complete", expanded=False)
else:
    manual_text = st.text_area("Texto:", height=250)
    if manual_text:
        with st.status("Analisando...", expanded=True) as status_manual:
            chapters, _ = split_text_regex(manual_text)
            status_manual.update(label="Análise concluída!", state="complete", expanded=False)

st.write("")
col_btn1, col_btn2 = st.columns(2)
with col_btn1:
    if st.button("▶️ Ouvir Prévia"):
        asyncio.run(run_edge_tts("Preparado para dar vida a mais uma história?", VOICES[voice_label], "preview.mp3"))
        st.audio("preview.mp3")
with col_btn2:
    if st.button("🗑️ Limpar Tudo"):
        st.session_state.zip_buffer = None
        st.session_state.book_ready = False
        st.session_state.chapters_generated = []
        if os.path.exists("out"): shutil.rmtree("out")
        st.rerun()

# --- GERAÇÃO ANIMADA ---
if chapters:
    st.info(f"Identificadas {len(chapters)} partes.")
    if st.button("🚀 INICIAR GERAÇÃO COMPLETA"):
        st.session_state.chapters_generated = []
        progress_bar = st.progress(0)
        with st.status("Iniciando motor de voz...", expanded=True) as status_gen:
            if not os.path.exists("out"): os.makedirs("out")
            for i, cap in enumerate(chapters):
                track = i + 1
                fname = f"out/{track:03d}.mp3"
                status_gen.write(f"🎙️ Narrando: {cap['title']}...")
                tags = {'title': f"{book_title} - {cap['title']}", 'author': book_author, 'track': track, 'year': book_year}
                if generate_audio(cap['content'], VOICES[voice_label], fname, tags):
                    with open(fname, "rb") as f:
                        st.session_state.chapters_generated.append({"title": cap['title'], "data": f.read(), "track": track})
                progress_bar.progress(track / len(chapters))
            status_gen.update(label="Vozes geradas!", state="complete", expanded=False)
        
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            for item in st.session_state.chapters_generated:
                zf.writestr(f"{item['track']:03d}.mp3", item['data'])
        st.session_state.zip_buffer = buffer.getvalue()
        st.session_state.book_ready = True
        st.success("Tudo pronto abaixo!")

# Downloads
if st.session_state.chapters_generated:
    st.write("---")
    st.subheader("📥 Downloads")
    for item in st.session_state.chapters_generated:
        with st.expander(f"Parte {item['track']}: {item['title']}"):
            st.download_button("Baixar MP3", item["data"], f"{item['track']:03d}.mp3", key=f"dl_{item['track']}")

if st.session_state.book_ready:
    st.write("---")
    st.download_button("📥 BAIXAR TUDO (.ZIP)", st.session_state.zip_buffer, f"{book_title}.zip")
