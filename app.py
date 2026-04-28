import asyncio
import io
import os
import re
import zipfile
import tempfile
from dataclasses import dataclass
from typing import List, Tuple, Optional

import streamlit as st
from PyPDF2 import PdfReader
from ebooklib import epub
from bs4 import BeautifulSoup
import edge_tts
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TDRC, ID3NoHeaderError
from mutagen.mp3 import MP3


VOICE_MAP = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculina)": "pt-BR-AntonioNeural",
    "Brenda": "pt-BR-BrendaNeural",
    "Donato": "pt-BR-DonatoNeural",
    "Fabio": "pt-BR-FabioNeural",
}

MAX_TTS_CHARS = 1500
FALLBACK_CHUNK_CHARS = 3000


@dataclass
class Chapter:
    title: str
    text: str


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "livro"


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[\.\!\?\:\;])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int) -> List[str]:
    sentences = split_into_sentences(text)
    if not sentences:
        return []
    chunks = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i:i + max_chars].strip())
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = sentence
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if c]


def extract_text_from_pdf(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    pages = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        pages.append(txt)
    return normalize_text("\n\n".join(pages))


def extract_text_from_epub(uploaded_file) -> Tuple[str, Optional[str], List[Tuple[str, str]]]:
    book = epub.read_epub(uploaded_file)
    title = None
    try:
        metadata_title = book.get_metadata("DC", "title")
        if metadata_title:
            title = metadata_title[0][0]
    except Exception:
        title = None

    toc_items = []
    text_parts = []

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            txt = soup.get_text("\n")
            txt = normalize_text(txt)
            if txt:
                text_parts.append(txt)

    def walk_toc(toc):
        for x in toc:
            if isinstance(x, tuple) and len(x) == 2:
                label = str(x[0]).strip()
                href = getattr(x[1], "href", "") or ""
                if label:
                    toc_items.append((label, href))
            elif hasattr(x, "title") and hasattr(x, "href"):
                label = str(getattr(x, "title", "")).strip()
                href = str(getattr(x, "href", "")).strip()
                if label:
                    toc_items.append((label, href))
            elif isinstance(x, list):
                walk_toc(x)

    try:
        walk_toc(book.toc)
    except Exception:
        pass

    return normalize_text("\n\n".join(text_parts)), title, toc_items


def extract_upload(uploaded_file) -> Tuple[str, Optional[str], List[Tuple[str, str]]]:
    name = uploaded_file.name.lower()
    uploaded_file.seek(0)
    if name.endswith(".pdf"):
        return extract_text_from_pdf(uploaded_file), None, []
    if name.endswith(".epub"):
        return extract_text_from_epub(uploaded_file)
    raise ValueError("Formato não suportado.")


def find_block(text: str, marker: str) -> Optional[Tuple[int, int]]:
    m = re.search(rf"(^|\n)\s*{re.escape(marker)}\s*(\n|$)", text, flags=re.IGNORECASE)
    if not m:
        return None
    start = m.end()
    next_heading = re.search(r"\n\s*(cap[ií]tulo\s+\d+|chapter\s+\d+|parte\s+\d+|part\s+[ivxlcdm]+)\s*(\n|$)", text[start:], flags=re.IGNORECASE)
    end = start + next_heading.start() if next_heading else len(text)
    return start, end


def detect_toc_chapters(text: str, toc_items: List[Tuple[str, str]]) -> List[Chapter]:
    if not toc_items:
        return []
    titles = []
    seen = set()
    for title, _ in toc_items:
        t = re.sub(r"\s+", " ", title).strip()
        if len(t) < 3:
            continue
        key = t.lower()
        if key not in seen:
            seen.add(key)
            titles.append(t)

    positions = []
    lower_text = text.lower()
    for title in titles:
        idx = lower_text.find(title.lower())
        if idx != -1:
            positions.append((idx, title))

    positions.sort()
    if len(positions) < 2:
        return []

    chapters = []
    for i, (start, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        piece = text[start:end].strip()
        if len(piece) > 100:
            chapters.append(Chapter(title=title, text=piece))
    return chapters


def detect_pattern_chapters(text: str) -> List[Chapter]:
    patterns = [
        r"(?im)^\s*(cap[ií]tulo\s+\d+|cap[ií]tulo\s+[ivxlcdm]+)\s*$",
        r"(?im)^\s*(parte\s+\d+|parte\s+[ivxlcdm]+)\s*$",
        r"(?im)^\s*(chapter\s+\d+|chapter\s+[ivxlcdm]+)\s*$",
        r"(?im)^\s*(part\s+\d+|part\s+[ivxlcdm]+)\s*$",
    ]
    matches = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            matches.append((m.start(), m.group(1).strip()))
    matches = sorted(set(matches), key=lambda x: x[0])
    if len(matches) < 2:
        return []

    chapters = []
    for i, (start, title) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        piece = text[start:end].strip()
        if len(piece) > 100:
            chapters.append(Chapter(title=title, text=piece))
    return chapters


def fallback_split(text: str) -> List[Chapter]:
    chunks = chunk_text(text, FALLBACK_CHUNK_CHARS)
    return [Chapter(title=f"Bloco {i+1}", text=c) for i, c in enumerate(chunks) if c.strip()]


def detect_chapters(text: str, toc_items: List[Tuple[str, str]]) -> Tuple[str, List[Chapter]]:
    toc_chapters = detect_toc_chapters(text, toc_items)
    if toc_chapters:
        return "sumário", toc_chapters

    pattern_chapters = detect_pattern_chapters(text)
    if pattern_chapters:
        return "padrão", pattern_chapters

    return "fallback", fallback_split(text)


def clean_for_tts(text: str) -> str:
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return text.strip()


async def edge_tts_save(text: str, voice: str, out_path: str) -> None:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


def generate_with_edge(text: str, voice: str, out_path: str) -> bool:
    parts = chunk_text(clean_for_tts(text), MAX_TTS_CHARS)
    if not parts:
        return False

    with tempfile.TemporaryDirectory() as td:
        tmp_files = []
        for i, part in enumerate(parts):
            tmp_part = os.path.join(td, f"part_{i:03d}.mp3")
            last_err = None
            for _ in range(3):
                try:
                    asyncio.run(edge_tts_save(part, voice, tmp_part))
                    if os.path.exists(tmp_part) and os.path.getsize(tmp_part) > 0:
                        tmp_files.append(tmp_part)
                        break
                except Exception as e:
                    last_err = e
            else:
                raise RuntimeError(f"Falha no edge-tts: {last_err}")

        if not tmp_files:
            return False

        with open(out_path, "wb") as outfile:
            for f in tmp_files:
                with open(f, "rb") as infile:
                    outfile.write(infile.read())
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def generate_with_gtts(text: str, out_path: str) -> bool:
    parts = chunk_text(clean_for_tts(text), MAX_TTS_CHARS)
    if not parts:
        return False
    with tempfile.TemporaryDirectory() as td:
        tmp_files = []
        for i, part in enumerate(parts):
            tmp_part = os.path.join(td, f"part_{i:03d}.mp3")
            tts = gTTS(text=part, lang="pt")
            tts.save(tmp_part)
            if os.path.exists(tmp_part) and os.path.getsize(tmp_part) > 0:
                tmp_files.append(tmp_part)
        if not tmp_files:
            return False
        with open(out_path, "wb") as outfile:
            for f in tmp_files:
                with open(f, "rb") as infile:
                    outfile.write(infile.read())
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def add_mp3_metadata(path: str, title: str, author: str, track_no: int, total_tracks: int, year: str = "") -> None:
    try:
        audio = MP3(path, ID3=ID3)
    except Exception:
        audio = MP3(path)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    tags["TIT2"] = TIT2(encoding=3, text=title)
    tags["TPE1"] = TPE1(encoding=3, text=author)
    tags["TALB"] = TALB(encoding=3, text=title)
    tags["TRCK"] = TRCK(encoding=3, text=f"{track_no}/{total_tracks}")
    if year and str(year).strip():
        tags["TDRC"] = TDRC(encoding=3, text=str(year).strip())
    tags.save(path)


def build_zip(audio_files: List[Tuple[str, str]]) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, path in audio_files:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                zf.write(path, arcname=arcname)
    mem.seek(0)
    return mem.read()


def preview_chapters(chapters: List[Chapter], limit: int = 3) -> str:
    lines = []
    for i, ch in enumerate(chapters[:limit], start=1):
        snippet = ch.text[:400].replace("\n", " ")
        lines.append(f"{i}. {ch.title} — {snippet}...")
    return "\n\n".join(lines)


st.set_page_config(page_title="Audiobook Builder", layout="wide")
st.title("Conversor de PDF/EPUB para Audiobook")

uploaded = st.file_uploader("Envie um arquivo PDF ou EPUB", type=["pdf", "epub"])
col1, col2 = st.columns(2)
with col1:
    title = st.text_input("Título", value="")
    author = st.text_input("Autor", value="")
with col2:
    year = st.text_input("Ano (opcional)", value="")
voice_label = st.selectbox("Voz", list(VOICE_MAP.keys()))
start = st.button("Gerar audiobook")

if uploaded:
    try:
        raw_text, epub_title, toc_items = extract_upload(uploaded)
        raw_text = normalize_text(raw_text)
        if not title and epub_title:
            title = epub_title

        method = None
        chapters = []
        if raw_text:
            method, chapters = detect_chapters(raw_text, toc_items)

        st.subheader("Extração")
        st.write(f"Método de divisão utilizado: **{method or 'indisponível'}**")
        st.write(f"Número de capítulos detectados: **{len(chapters)}**")
        if chapters:
            st.text_area("Preview dos primeiros capítulos", value=preview_chapters(chapters), height=220)
        else:
            st.warning("Nenhum capítulo detectado ainda.")
    except Exception as e:
        st.error(f"Falha ao processar o arquivo: {e}")
        chapters = []
        method = None
        raw_text = ""

if start:
    if not uploaded:
        st.error("Envie um arquivo antes de gerar.")
    elif not title.strip():
        st.error("Informe o título do livro.")
    elif not author.strip():
        st.error("Informe o autor.")
    else:
        try:
            uploaded.seek(0)
            raw_text, epub_title, toc_items = extract_upload(uploaded)
            raw_text = normalize_text(raw_text)
            method, chapters = detect_chapters(raw_text, toc_items)

            if not chapters:
                st.warning("Nenhum capítulo detectado. Usando fallback.")
                chapters = fallback_split(raw_text)
                method = "fallback"

            if not chapters:
                st.error("Não foi possível dividir o texto em capítulos válidos.")
                st.stop()

            voice = VOICE_MAP[voice_label]
            safe_title = safe_filename(title)
            out_dir = tempfile.mkdtemp(prefix="audiobook_")
            audio_files = []
            progress = st.progress(0)
            status = st.empty()

            for idx, chapter in enumerate(chapters, start=1):
                status.write(f"Gerando capítulo {idx}/{len(chapters)}: {chapter.title}")
                out_path = os.path.join(out_dir, f"{idx:03d}.mp3")

                ok = False
                try:
                    ok = generate_with_edge(chapter.text, voice, out_path)
                except Exception:
                    ok = False

                if not ok:
                    try:
                        ok = generate_with_gtts(chapter.text, out_path)
                    except Exception:
                        ok = False

                if not ok or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                    st.error(f"Falha ao gerar o áudio do capítulo {idx}.")
                    continue

                try:
                    add_mp3_metadata(
                        out_path,
                        title=title.strip(),
                        author=author.strip(),
                        track_no=idx,
                        total_tracks=len(chapters),
                        year=year.strip(),
                    )
                except Exception as e:
                    st.warning(f"Áudio gerado, mas sem metadata completa no capítulo {idx}: {e}")

                audio_files.append((f"{idx:03d}.mp3", out_path))
                progress.progress(int(idx / len(chapters) * 100))

            if not audio_files:
                st.error("Nenhum áudio foi gerado; o ZIP final não será criado.")
            else:
                zip_bytes = build_zip(audio_files)
                if not zip_bytes:
                    st.error("ZIP vazio. Verifique a geração dos arquivos.")
                else:
                    zip_name = f"{safe_title}.zip"
                    st.success("Audiobook gerado com sucesso.")
                    st.download_button(
                        label="Baixar ZIP",
                        data=zip_bytes,
                        file_name=zip_name,
                        mime="application/zip",
                    )
        except Exception as e:
            st.error(f"Erro inesperado durante a geração: {e}")
