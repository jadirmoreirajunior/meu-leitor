Abaixo estão os dois arquivos completos, prontos para copiar e rodar:

---

## `app.py`

```python
import asyncio
import io
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import streamlit as st
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TDRC
from gtts import gTTS
import edge_tts


# =========================
# Configuração Streamlit
# =========================
st.set_page_config(
    page_title="PDF/EPUB para Audiobook",
    page_icon="🎧",
    layout="wide"
)


# =========================
# Constantes
# =========================
VOICE_OPTIONS = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculina)": "pt-BR-AntonioNeural",
    "Brenda": "pt-BR-BrendaNeural",
    "Donato": "pt-BR-DonatoNeural",
    "Fabio": "pt-BR-FabioNeural",
}

MAX_TTS_CHARS = 1500
FALLBACK_BLOCK_CHARS = 3000
MAX_EDGE_RETRIES = 3


# =========================
# Utilidades gerais
# =========================
def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return text.strip()


def normalize_for_match(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\sà-ÿ]", "", text, flags=re.UNICODE)
    return text.strip()


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name or "audiobook"


def split_text_safely(text: str, max_chars: int = MAX_TTS_CHARS) -> List[str]:
    text = sanitize_text(text)
    if len(text) <= max_chars:
        return [text] if text else []

    parts = []
    remaining = text

    while len(remaining) > max_chars:
        chunk = remaining[:max_chars]

        split_pos = max(
            chunk.rfind(". "),
            chunk.rfind("! "),
            chunk.rfind("? "),
            chunk.rfind("\n"),
            chunk.rfind("; "),
            chunk.rfind(", "),
        )

        if split_pos < int(max_chars * 0.5):
            split_pos = chunk.rfind(" ")

        if split_pos == -1:
            split_pos = max_chars

        part = remaining[:split_pos + 1].strip()
        if part:
            parts.append(part)

        remaining = remaining[split_pos + 1:].strip()

    if remaining:
        parts.append(remaining)

    return [p for p in parts if p.strip()]


def split_text_into_blocks(text: str, target_chars: int = FALLBACK_BLOCK_CHARS) -> List[str]:
    text = sanitize_text(text)
    if len(text) <= target_chars:
        return [text] if text else []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    blocks = []
    current = ""

    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= target_chars:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            if current:
                blocks.append(current.strip())

            if len(paragraph) <= target_chars:
                current = paragraph
            else:
                subparts = split_text_safely(paragraph, target_chars)
                if subparts:
                    blocks.extend(subparts[:-1])
                    current = subparts[-1]
                else:
                    current = ""

    if current.strip():
        blocks.append(current.strip())

    return [b for b in blocks if b.strip()]


# =========================
# Extração de texto
# =========================
def extract_text_from_pdf(file_bytes: bytes) -> str:
    text_parts = []
    try:
        pdf_stream = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_stream)
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text)
    except Exception as e:
        raise RuntimeError(f"Erro ao ler PDF: {e}") from e

    full_text = "\n\n".join(text_parts)
    full_text = sanitize_text(full_text)

    if not full_text.strip():
        raise RuntimeError("Não foi possível extrair texto do PDF.")
    return full_text


def extract_text_from_epub(file_bytes: bytes) -> str:
    text_parts = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        book = epub.read_epub(tmp_path)
        for item in book.get_items():
            if item.get_type() == ITEM_DOCUMENT:
                content = item.get_content()
                soup = BeautifulSoup(content, "html.parser")
                text = soup.get_text(separator="\n")
                text = sanitize_text(text)
                if text.strip():
                    text_parts.append(text)

    except Exception as e:
        raise RuntimeError(f"Erro ao ler EPUB: {e}") from e
    finally:
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    full_text = "\n\n".join(text_parts)
    full_text = sanitize_text(full_text)

    if not full_text.strip():
        raise RuntimeError("Não foi possível extrair texto do EPUB.")
    return full_text


def extract_text(uploaded_file) -> str:
    ext = Path(uploaded_file.name).suffix.lower()
    file_bytes = uploaded_file.read()

    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    if ext == ".epub":
        return extract_text_from_epub(file_bytes)

    raise RuntimeError("Formato não suportado. Envie PDF ou EPUB.")


# =========================
# Detecção de sumário e capítulos
# =========================
def find_toc_section(text: str) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    toc_start = -1

    for i, line in enumerate(lines):
        if re.fullmatch(r"(sumário|sumario|índice|indice|contents|table of contents)", line.strip(), re.IGNORECASE):
            toc_start = i
            break

    if toc_start == -1:
        return []

    toc_lines = []
    for line in lines[toc_start + 1: toc_start + 80]:
        clean_line = line.strip()

        if not clean_line:
            continue

        if re.fullmatch(r"\d+", clean_line):
            continue

        toc_lines.append(clean_line)

        if len(toc_lines) >= 30:
            break

    return toc_lines


def clean_toc_entry(line: str) -> Optional[str]:
    line = line.strip()

    if len(line) < 3:
        return None

    line = re.sub(r"\.{2,}\s*\d+$", "", line)
    line = re.sub(r"\s+\d+$", "", line)
    line = re.sub(r"^[\-\•\·\*]+\s*", "", line)
    line = re.sub(r"^\d+[\.\-\)]\s*", "", line)
    line = line.strip(" .-_\t")

    if len(line) < 3:
        return None

    if normalize_for_match(line) in {"sumário", "sumario", "índice", "indice", "contents"}:
        return None

    return line


def parse_toc_titles(text: str) -> List[str]:
    toc_lines = find_toc_section(text)
    titles = []

    for line in toc_lines:
        title = clean_toc_entry(line)
        if title:
            titles.append(title)

    unique_titles = []
    seen = set()
    for title in titles:
        key = normalize_for_match(title)
        if key and key not in seen:
            seen.add(key)
            unique_titles.append(title)

    return unique_titles


def locate_titles_in_text(text: str, titles: List[str]) -> List[Tuple[int, str]]:
    lines = text.splitlines()
    positions = []

    normalized_lines = [normalize_for_match(line) for line in lines]

    for title in titles:
        n_title = normalize_for_match(title)
        if not n_title:
            continue

        found_index = None

        for idx, n_line in enumerate(normalized_lines):
            if n_title == n_line:
                found_index = idx
                break

        if found_index is None:
            for idx, n_line in enumerate(normalized_lines):
                if n_title in n_line and len(n_title) >= 5:
                    found_index = idx
                    break

        if found_index is not None:
            char_pos = sum(len(lines[i]) + 1 for i in range(found_index))
            positions.append((char_pos, title))

    positions = sorted(set(positions), key=lambda x: x[0])
    return positions


def split_by_toc(text: str) -> Optional[List[Dict[str, str]]]:
    titles = parse_toc_titles(text)
    if len(titles) < 2:
        return None

    positions = locate_titles_in_text(text, titles)
    if len(positions) < 2:
        return None

    chapters = []
    for i, (start_pos, title) in enumerate(positions):
        end_pos = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        content = text[start_pos:end_pos].strip()
        if len(content) >= 50:
            chapters.append({"title": title, "content": content})

    if len(chapters) >= 2:
        return chapters
    return None


def split_by_pattern(text: str) -> Optional[List[Dict[str, str]]]:
    pattern = re.compile(
        r"(?im)^(cap[ií]tulo\s+[0-9ivxlcdm]+|parte\s+[0-9ivxlcdm]+|chapter\s+[0-9ivxlcdm]+|part\s+[0-9ivxlcdm]+)\b.*$"
    )

    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return None

    chapters = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title_line = match.group(0).strip()
        content = text[start:end].strip()

        if len(content) >= 50:
            chapters.append({"title": title_line, "content": content})

    if len(chapters) >= 2:
        return chapters
    return None


def split_by_fallback(text: str) -> List[Dict[str, str]]:
    blocks = split_text_into_blocks(text, FALLBACK_BLOCK_CHARS)
    chapters = []

    for i, block in enumerate(blocks, start=1):
        chapters.append({
            "title": f"Bloco {i}",
            "content": block
        })

    return chapters


def detect_and_split_chapters(text: str) -> Tuple[List[Dict[str, str]], str]:
    chapters = split_by_toc(text)
    if chapters:
        return chapters, "sumário"

    chapters = split_by_pattern(text)
    if chapters:
        return chapters, "padrão"

    chapters = split_by_fallback(text)
    return chapters, "fallback"


# =========================
# TTS
# =========================
async def edge_tts_generate(text: str, voice: str, output_path: str) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(output_path)


def generate_edge_audio_chunk(text: str, voice: str, output_path: str) -> bool:
    for attempt in range(1, MAX_EDGE_RETRIES + 1):
        try:
            asyncio.run(edge_tts_generate(text, voice, output_path))
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True
        except Exception:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
    return False


def generate_gtts_audio_chunk(text: str, output_path: str) -> bool:
    try:
        tts = gTTS(text=text, lang="pt")
        tts.save(output_path)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        return False


def combine_mp3_files(parts: List[str], output_path: str) -> bool:
    try:
        with open(output_path, "wb") as outfile:
            wrote_anything = False
            for part in parts:
                if os.path.exists(part) and os.path.getsize(part) > 0:
                    with open(part, "rb") as infile:
                        data = infile.read()
                        if data:
                            outfile.write(data)
                            wrote_anything = True

        return wrote_anything and os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception:
        return False


def add_metadata_to_mp3(
    file_path: str,
    title: str,
    author: str,
    track_number: int,
    year: str = ""
) -> None:
    try:
        try:
            audio = EasyID3(file_path)
        except Exception:
            audio = ID3()

        if isinstance(audio, EasyID3):
            audio["title"] = title
            audio["artist"] = author or "Desconhecido"
            audio["tracknumber"] = str(track_number)
            if year:
                audio["date"] = year
            audio.save(file_path)
        else:
            audio.add(TIT2(encoding=3, text=title))
            audio.add(TPE1(encoding=3, text=author or "Desconhecido"))
            audio.add(TRCK(encoding=3, text=str(track_number)))
            if year:
                audio.add(TDRC(encoding=3, text=year))
            audio.save(file_path)
    except Exception:
        pass


def generate_chapter_audio(
    chapter_text: str,
    voice: str,
    final_output_path: str
) -> Tuple[bool, str]:
    chunks = split_text_safely(chapter_text, MAX_TTS_CHARS)
    if not chunks:
        return False, "Texto vazio para geração."

    temp_parts = []

    try:
        for idx, chunk in enumerate(chunks, start=1):
            part_path = f"{final_output_path}.part{idx}.mp3"

            success_edge = generate_edge_audio_chunk(chunk, voice, part_path)
            if not success_edge:
                success_gtts = generate_gtts_audio_chunk(chunk, part_path)
                if not success_gtts:
                    return False, f"Falha ao gerar parte {idx} com edge-tts e gTTS."

            if not os.path.exists(part_path) or os.path.getsize(part_path) == 0:
                return False, f"Arquivo de áudio da parte {idx} não foi gerado corretamente."

            temp_parts.append(part_path)

        combined = combine_mp3_files(temp_parts, final_output_path)
        if not combined:
            return False, "Falha ao combinar partes do áudio."

        if not os.path.exists(final_output_path) or os.path.getsize(final_output_path) == 0:
            return False, "Arquivo final de áudio não foi gerado corretamente."

        return True, "OK"

    finally:
        for part in temp_parts:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except Exception:
                    pass


# =========================
# ZIP
# =========================
def create_zip_from_files(file_paths: List[str], zip_path: str) -> bool:
    try:
        valid_files = [fp for fp in file_paths if os.path.exists(fp) and os.path.getsize(fp) > 0]
        if not valid_files:
            return False

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in valid_files:
                zf.write(file_path, arcname=os.path.basename(file_path))

        return os.path.exists(zip_path) and os.path.getsize(zip_path) > 0
    except Exception:
        return False


# =========================
# Interface
# =========================
st.title("🎧 Conversor de PDF/EPUB para Audiobook")
st.write("Faça upload de um arquivo PDF ou EPUB, detecte capítulos automaticamente e gere um audiobook em MP3.")

with st.sidebar:
    st.header("Configurações")
    selected_voice_label = st.selectbox("Selecione a voz", list(VOICE_OPTIONS.keys()))
    selected_voice = VOICE_OPTIONS[selected_voice_label]

    book_title = st.text_input("Título", value="")
    author = st.text_input("Autor", value="")
    year = st.text_input("Ano (opcional)", value="")

uploaded_file = st.file_uploader("Envie um arquivo PDF ou EPUB", type=["pdf", "epub"])

if uploaded_file is not None:
    try:
        with st.spinner("Extraindo texto do arquivo..."):
            text = extract_text(uploaded_file)

        if not text.strip():
            st.error("Não foi possível extrair texto do arquivo enviado.")
            st.stop()

        chapters, method = detect_and_split_chapters(text)

        if not chapters:
            st.error("Não foi possível detectar conteúdo para geração de áudio.")
            st.stop()

        if not book_title.strip():
            inferred_title = Path(uploaded_file.name).stem
            book_title = inferred_title

        st.success("Texto extraído com sucesso.")

        col1, col2 = st.columns(2)
        with col1:
            st.info(f"**Método de divisão utilizado:** {method}")
        with col2:
            st.info(f"**Número de capítulos detectados:** {len(chapters)}")

        st.subheader("Preview dos primeiros capítulos")
        preview_limit = min(5, len(chapters))
        for i in range(preview_limit):
            st.markdown(f"**{i + 1}. {chapters[i]['title']}**")
            st.caption(chapters[i]["content"][:300].replace("\n", " ") + ("..." if len(chapters[i]["content"]) > 300 else ""))

        if st.button("Gerar Audiobook", type="primary"):
            progress_bar = st.progress(0)
            status_box = st.empty()
            log_box = st.empty()

            generated_files = []
            errors = []

            with tempfile.TemporaryDirectory() as tmpdir:
                status_box.info("Iniciando geração dos áudios...")

                for idx, chapter in enumerate(chapters, start=1):
                    filename = f"{idx:03d}.mp3"
                    output_path = os.path.join(tmpdir, filename)

                    chapter_title = chapter["title"].strip() or f"Capítulo {idx}"
                    chapter_text = chapter["content"].strip()

                    if not chapter_text:
                        errors.append(f"{filename}: capítulo vazio.")
                        progress_bar.progress(idx / len(chapters))
                        continue

                    status_box.info(f"Gerando {filename} - {chapter_title}")

                    success, message = generate_chapter_audio(
                        chapter_text=chapter_text,
                        voice=selected_voice,
                        final_output_path=output_path
                    )

                    if success:
                        add_metadata_to_mp3(
                            file_path=output_path,
                            title=f"{book_title} - {chapter_title}",
                            author=author,
                            track_number=idx,
                            year=year
                        )

                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            generated_files.append(output_path)
                        else:
                            errors.append(f"{filename}: arquivo final inválido após metadados.")
                    else:
                        errors.append(f"{filename}: {message}")

                    progress_bar.progress(idx / len(chapters))

                    if errors:
                        log_box.warning("Erros parciais detectados:\n\n" + "\n".join(errors[-5:]))

                if not generated_files:
                    st.error("Nenhum arquivo de áudio foi gerado. Verifique o arquivo enviado e tente novamente.")
                    if errors:
                        st.text_area("Detalhes dos erros", "\n".join(errors), height=200)
                    st.stop()

                zip_name = safe_filename(f"{book_title}_audiobook") + ".zip"
                zip_path = os.path.join(tmpdir, zip_name)

                status_box.info("Compactando arquivos em ZIP...")
                zip_success = create_zip_from_files(generated_files, zip_path)

                if not zip_success:
                    st.error("Falha ao gerar o arquivo ZIP final.")
                    if errors:
                        st.text_area("Detalhes dos erros", "\n".join(errors), height=200)
                    st.stop()

                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()

                if not zip_bytes:
                    st.error("O arquivo ZIP final ficou vazio.")
                    st.stop()

                status_box.success("Audiobook gerado com sucesso!")

                st.download_button(
                    label="📥 Baixar ZIP com os áudios",
                    data=zip_bytes,
                    file_name=zip_name,
                    mime="application/zip"
                )

                st.subheader("Resumo da geração")
                st.write(f"**Arquivos de áudio gerados:** {len(generated_files)}")
                st.write(f"**Falhas:** {len(errors)}")

                if errors:
                    st.text_area("Detalhes dos erros", "\n".join(errors), height=200)

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo: {e}")
else:
    st.info("Envie um arquivo PDF ou EPUB para começar.")
```

---

## `requirements.txt`

```txt
streamlit
edge-tts
PyPDF2
ebooklib
beautifulsoup4
mutagen
gTTS
lxml
```

---

## Observações rápidas
- O app foi feito para rodar no **Streamlit Cloud**.
- O fallback de TTS usa **gTTS** caso o **edge-tts** falhe.
- O ZIP só é liberado se houver arquivos válidos.
- O app mostra:
  - método de divisão
  - quantidade de capítulos
  - preview
  - progresso
  - erros parciais, se existirem

Se quiser, eu também posso te entregar uma **versão melhorada com `packages.txt` para ffmpeg** e junção de áudios mais confiável, caso você queira máxima compatibilidade.
