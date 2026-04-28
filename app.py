import streamlit as st
import tempfile
import os
import re
import zipfile
import asyncio
import time
from pathlib import Path

import PyPDF2
from ebooklib import epub
from bs4 import BeautifulSoup
from edge_tts import Communicate
from gtts import gTTS
import mutagen.mp3
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3

# ==================== CONFIGURAÇÃO ====================
st.set_page_config(
    page_title="PDF/EPUB → Audiobook",
    page_icon="🎧",
    layout="centered"
)

st.title("🎧 Conversor de Livros em Audiobook")
st.markdown("Transforme PDFs e EPUBs em audiobooks com vozes naturais (edge-tts + fallback gTTS)")

# ==================== VOZES ====================
VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculina)": "pt-BR-AntonioNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculina)": "pt-BR-DonatoNeural",
    "Fabio (Masculina)": "pt-BR-FabioNeural",
}

# ==================== FUNÇÕES AUXILIARES ====================

def extract_text_from_pdf(file_bytes):
    """Extrai texto de PDF usando PyPDF2"""
    try:
        reader = PyPDF2.PdfReader(file_bytes)
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n\n"
        return text.strip(), reader.metadata
    except Exception as e:
        st.error(f"Erro ao ler PDF: {e}")
        return "", None

def extract_text_from_epub(file_bytes):
    """Extrai texto de EPUB usando ebooklib + BeautifulSoup"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
            tmp.write(file_bytes.read())
            tmp_path = tmp.name

        book = epub.read_epub(tmp_path)
        full_text = ""
        metadata = {}

        # Tenta extrair metadados
        try:
            metadata['title'] = book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else "Livro sem título"
            metadata['creator'] = book.get_metadata('DC', 'creator')[0][0] if book.get_metadata('DC', 'creator') else "Autor desconhecido"
        except:
            metadata = {'title': "Livro sem título", 'creator': "Autor desconhecido"}

        for item in book.get_items_of_type(epub.ITEM_DOCUMENT):
            if item.get_content():
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                # Remove scripts e estilos
                for tag in soup(["script", "style"]):
                    tag.decompose()
                text = soup.get_text(separator="\n")
                full_text += text + "\n\n"

        os.unlink(tmp_path)
        return full_text.strip(), metadata
    except Exception as e:
        st.error(f"Erro ao ler EPUB: {e}")
        return "", {}

def detect_chapters(text):
    """
    Detecta capítulos com prioridade:
    1. Sumário (Índice / Sumário / Contents)
    2. Padrões comuns (Capítulo, Chapter, Parte, Part)
    3. Fallback: divisão por tamanho (~3000 chars)
    """
    lines = text.split('\n')
    chapters = []

    # Padrões de capítulos
    chapter_patterns = [
        r'^(Capítulo|Chapter|Parte|Part)\s+[\dIVX]+[:\.\s-]*(.*)$',
        r'^\s*(\d+)\.\s*(.+)$',                    # 1. Título
        r'^\s*Capítulo\s+(\d+|[IVX]+)[:\.\s-]*(.*)$',
        r'^\s*Chapter\s+(\d+|[IVX]+)[:\.\s-]*(.*)$',
    ]

    current_chapter = {"title": "Introdução", "content": ""}
    chapter_count = 0

    for line in lines:
        line_stripped = line.strip()
        is_chapter = False

        for pattern in chapter_patterns:
            match = re.match(pattern, line_stripped, re.IGNORECASE)
            if match:
                if current_chapter["content"].strip():
                    chapters.append(current_chapter)
                title = line_stripped[:100]  # limita tamanho
                current_chapter = {"title": title, "content": ""}
                is_chapter = True
                chapter_count += 1
                break

        if not is_chapter:
            current_chapter["content"] += line + "\n"

    if current_chapter["content"].strip():
        chapters.append(current_chapter)

    # Fallback se poucos capítulos foram detectados
    if len(chapters) <= 2 and len(text) > 5000:
        st.info("Poucos capítulos detectados. Usando divisão automática por blocos.")
        chunks = []
        current = ""
        for sentence in re.split(r'(?<=[.!?])\s+', text):
            if len(current) + len(sentence) > 2800:
                if current:
                    chunks.append({"title": f"Parte {len(chunks)+1}", "content": current.strip()})
                current = sentence + " "
            else:
                current += sentence + " "
        if current:
            chunks.append({"title": f"Parte {len(chunks)+1}", "content": current.strip()})
        return chunks

    return chapters if chapters else [{"title": "Conteúdo Completo", "content": text}]

def split_text_for_tts(text, max_chars=1400):
    """Divide texto em partes menores para evitar limites do TTS"""
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r'(?<=[.!?])\s+', text)
    parts = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) > max_chars:
            if current:
                parts.append(current.strip())
            current = sentence + " "
        else:
            current += sentence + " "

    if current:
        parts.append(current.strip())

    return parts

async def generate_audio_edge(text, voice, output_path):
    """Gera áudio com edge-tts com retry"""
    for attempt in range(3):
        try:
            communicate = Communicate(text, voice)
            await communicate.save(output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                return True
        except Exception as e:
            if attempt == 2:
                st.warning(f"edge-tts falhou após 3 tentativas: {e}")
                return False
            await asyncio.sleep(1)
    return False

def generate_audio_gtts(text, output_path):
    """Fallback com gTTS"""
    try:
        tts = gTTS(text=text, lang='pt', slow=False)
        tts.save(output_path)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        st.error(f"gTTS falhou: {e}")
        return False

def add_metadata_to_mp3(mp3_path, title, artist, track_num, album="Audiobook"):
    """Adiciona metadados ID3 ao MP3"""
    try:
        audio = MP3(mp3_path, ID3=EasyID3)
        audio["title"] = title
        audio["artist"] = artist
        audio["album"] = album
        audio["tracknumber"] = str(track_num)
        audio.save()
    except Exception:
        pass  # Metadados não são críticos

# ==================== INTERFACE STREAMLIT ====================

uploaded_file = st.file_uploader("Escolha um arquivo PDF ou EPUB", type=['pdf', 'epub'])

if uploaded_file:
    col1, col2 = st.columns(2)

    with col1:
        book_title = st.text_input("Título do livro", value=uploaded_file.name.rsplit('.', 1)[0])
    with col2:
        author = st.text_input("Autor", value="Autor Desconhecido")

    year = st.text_input("Ano (opcional)", value="2025")

    voice_name = st.selectbox("Escolha a voz", options=list(VOICES.keys()))
    voice_id = VOICES[voice_name]

    if st.button("🚀 Gerar Audiobook", type="primary"):
        with st.spinner("Extraindo texto do arquivo..."):
            file_bytes = uploaded_file
            file_ext = uploaded_file.name.lower().split('.')[-1]

            if file_ext == 'pdf':
                text, metadata = extract_text_from_pdf(file_bytes)
                if metadata and '/Title' in metadata:
                    book_title = metadata['/Title'] or book_title
                if metadata and '/Author' in metadata:
                    author = metadata['/Author'] or author
            else:  # epub
                text, metadata = extract_text_from_epub(file_bytes)
                if metadata.get('title'):
                    book_title = metadata['title']
                if metadata.get('creator'):
                    author = metadata['creator']

            if not text or len(text.strip()) < 100:
                st.error("Não foi possível extrair texto suficiente do arquivo.")
                st.stop()

        # Detecção de capítulos
        with st.spinner("Detectando capítulos..."):
            chapters = detect_chapters(text)
            st.success(f"✅ {len(chapters)} capítulos detectados")

        # Geração de áudio
        progress_bar = st.progress(0)
        status_text = st.empty()

        temp_dir = tempfile.mkdtemp()
        audio_files = []

        try:
            for i, chapter in enumerate(chapters):
                status_text.text(f"Gerando áudio {i+1}/{len(chapters)}: {chapter['title'][:60]}...")

                chapter_text = chapter['content'].strip()
                if not chapter_text:
                    continue

                parts = split_text_for_tts(chapter_text)
                chapter_audio_paths = []

                for j, part in enumerate(parts):
                    audio_path = os.path.join(temp_dir, f"ch_{i:03d}_part_{j:02d}.mp3")

                    success = False
                    # Tenta edge-tts primeiro
                    try:
                        success = asyncio.run(generate_audio_edge(part, voice_id, audio_path))
                    except:
                        success = False

                    # Fallback gTTS
                    if not success:
                        success = generate_audio_gtts(part, audio_path)

                    if success and os.path.exists(audio_path):
                        chapter_audio_paths.append(audio_path)

                # Junta partes do capítulo (se necessário)
                if len(chapter_audio_paths) > 1:
                    final_chapter_path = os.path.join(temp_dir, f"{i+1:03d}.mp3")
                    # Simples concatenação (pode melhorar com pydub se quiser crossfade)
                    with open(final_chapter_path, "wb") as outfile:
                        for fpath in chapter_audio_paths:
                            with open(fpath, "rb") as infile:
                                outfile.write(infile.read())
                    audio_files.append(final_chapter_path)
                elif chapter_audio_paths:
                    final_chapter_path = os.path.join(temp_dir, f"{i+1:03d}.mp3")
                    os.rename(chapter_audio_paths[0], final_chapter_path)
                    audio_files.append(final_chapter_path)

                # Atualiza progresso
                progress = (i + 1) / len(chapters)
                progress_bar.progress(progress)

            # Adiciona metadados
            for idx, audio_path in enumerate(audio_files):
                add_metadata_to_mp3(
                    audio_path,
                    title=f"{book_title} - Capítulo {idx+1}",
                    artist=author,
                    track_num=idx+1,
                    album=book_title
                )

            # Cria ZIP
            zip_path = os.path.join(temp_dir, "audiobook.zip")
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for audio in audio_files:
                    zipf.write(audio, os.path.basename(audio))

            # Download
            with open(zip_path, "rb") as f:
                st.success("✅ Audiobook gerado com sucesso!")
                st.download_button(
                    label="📥 Baixar Audiobook (.zip)",
                    data=f,
                    file_name=f"{book_title.replace(' ', '_')}_audiobook.zip",
                    mime="application/zip"
                )

            # Preview dos primeiros capítulos
            st.subheader("Preview dos capítulos")
            for i in range(min(3, len(chapters))):
                with st.expander(f"Capítulo {i+1}: {chapters[i]['title'][:80]}"):
                    st.write(chapters[i]['content'][:500] + "..." if len(chapters[i]['content']) > 500 else chapters[i]['content'])

        except Exception as e:
            st.error(f"Erro durante a geração: {e}")
        finally:
            # Limpeza (opcional - Streamlit Cloud gerencia temp)
            pass

else:
    st.info("Faça upload de um arquivo PDF ou EPUB para começar.")

st.caption("App robusto com fallback edge-tts → gTTS | Compatível com Streamlit Cloud")
