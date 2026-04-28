import os
import re
import io
import zipfile
import shutil
import tempfile
import traceback
from typing import List, Tuple, Optional, Dict

import streamlit as st
from PyPDF2 import PdfReader

from ebooklib import epub
from bs4 import BeautifulSoup

from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3

import edge_tts
from gtts import gTTS


# ---------------------------
# Utilidades de UI/Estado
# ---------------------------

def init_session_state():
    if "output_dir" not in st.session_state:
        st.session_state.output_dir = None
    if "chapters" not in st.session_state:
        st.session_state.chapters = []
    if "audio_files" not in st.session_state:
        st.session_state.audio_files = []
    if "method" not in st.session_state:
        st.session_state.method = None
    if "log_messages" not in st.session_state:
        st.session_state.log_messages = []


def log_msg(message: str):
    st.session_state.log_messages.append(message)
    # Mostra no app também
    st.info(message)


# ---------------------------
# Extração de texto
# ---------------------------

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    texts = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        texts.append(page_text)
    return "\n".join(texts).strip()


def extract_text_from_epub(epub_bytes: bytes) -> str:
    book = epub.read_epub(io.BytesIO(epub_bytes))
    texts = []

    for item in book.get_items():
        if item.get_type() == epub.ITEM_DOCUMENT:
            try:
                html_content = item.get_content()
            except Exception:
                continue
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove scripts/styles
            for tag in soup(["script", "style", "noscript"]):
                try:
                    tag.decompose()
                except Exception:
                    pass

            text = soup.get_text(separator="\n")
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if text:
                texts.append(text)

    return "\n".join(texts).strip()


def extract_text(file_name: str, file_bytes: bytes) -> str:
    lower = file_name.lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    if lower.endswith(".epub"):
        return extract_text_from_epub(file_bytes)
    raise ValueError("Formato não suportado. Use PDF ou EPUB.")


# ---------------------------
# Normalização de texto
# ---------------------------

def normalize_whitespace(s: str) -> str:
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ---------------------------
# Detecção de capítulos
# ---------------------------

def is_likely_heading(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    # evita coisas muito curtas e ruidosas
    if len(t) < 4:
        return False
    # sugere título por padrão
    if re.search(r"^(cap[ií]tulo|parte|chapter|part)\s+\w+", t, flags=re.I):
        return True
    # títulos comuns
    if re.match(r"^[0-9IVXLCDM]+\s*[\.\-]?\s*.+", t):
        return True
    return False


def clean_toc_title(s: str) -> str:
    s = s.strip()
    # remove pontos de preenchimento tipo "Capítulo 1 .... 12"
    s = re.sub(r"\.{2,}", " ", s)
    # remove trailing numbers/years
    s = re.sub(r"\s+(\d{1,5}|[ivxlcdm]{1,10})\s*$", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detect_sumario_sections(text: str) -> Dict[str, str]:
    """
    Procura por seções no texto contendo "Sumário" ou "Índice" e retorna
    recortes aproximados para ajudar a extrair títulos.
    """
    # Heurísticas: pega até certo tamanho após o cabeçalho.
    patterns = [
        r"(sum[aá]rio)\b",
        r"(índice)\b",
        r"(indice)\b",
        r"(table of contents)\b",
        r"(contents)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            start = m.start()
            # recorte limitado para evitar o livro inteiro
            window = text[start:start + 120000]
            return {"section": window, "match": pat}
    return {}


def extract_titles_from_toc_block(toc_block: str) -> List[str]:
    """
    Tenta extrair linhas com possíveis títulos do sumário.
    Estratégia: pegar linhas curtas/médias, que começam com Capítulo/Parte
    ou têm padrões romanos/numéricos.
    """
    lines = [ln.strip() for ln in toc_block.splitlines()]
    titles = []

    for ln in lines:
        if not ln:
            continue

        # remove linhas muito longas
        if len(ln) > 140:
            continue

        # normaliza
        ln_norm = clean_toc_title(ln)

        # padrões principais
        if re.search(r"^(cap[ií]tulo|parte|chapter|part)\b", ln_norm, flags=re.I):
            if is_likely_heading(ln_norm):
                titles.append(ln_norm)
                continue

        # padrões "1. Título", "1 - Título"
        if re.match(r"^[0-9]{1,3}\s*[\.\-:]\s*\S", ln_norm):
            if is_likely_heading(ln_norm):
                titles.append(ln_norm)
                continue

        # padrões romanos "I. Título" ou "Capítulo I"
        if re.match(r"^[ivxlcdm]{1,8}\s*[\.\-:]\s*\S", ln_norm, flags=re.I):
            if is_likely_heading(ln_norm):
                titles.append(ln_norm)
                continue

    # dedup simples preservando ordem
    seen = set()
    out = []
    for t in titles:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)

    return out


def find_occurrences_indices(text: str, titles: List[str]) -> List[Tuple[int, str]]:
    """
    Encontra onde os títulos aparecem no texto, tentando variações.
    Retorna lista (posição, título).
    """
    candidates = []
    lower_text = text.lower()

    for title in titles:
        if len(title) < 4:
            continue

        # tenta pesquisar com o título e também sem prefixos comuns
        variants = [title]
        t = title
        t = re.sub(r"^(cap[ií]tulo|chapter|parte|part)\s+", "", t, flags=re.I).strip()
        if t and t != title:
            variants.append(t)

        # remove pontuação extra
        variants = [v.strip() for v in variants if v.strip()]

        best_pos = None
        best_len = 0

        for v in variants:
            # busca por substring direta
            v_low = v.lower()
            pos = lower_text.find(v_low)
            if pos != -1:
                if len(v_low) > best_len:
                    best_pos = pos
                    best_len = len(v_low)

        if best_pos is not None:
            candidates.append((best_pos, title))

    # ordena por posição
    candidates.sort(key=lambda x: x[0])

    # remove candidatos muito próximos (pode repetir pelo mesmo trecho)
    filtered = []
    last_pos = None
    for pos, title in candidates:
        if last_pos is None or abs(pos - last_pos) > 50:
            filtered.append((pos, title))
            last_pos = pos

    return filtered


def split_by_indices(text: str, indices: List[Tuple[int, str]]) -> List[Tuple[str, str]]:
    """
    Divide o texto em capítulos/trechos usando índices de início.
    Retorna lista de (titulo, conteudo).
    """
    if not indices:
        return []

    # adiciona sentinela final
    starts = [(pos, title) for pos, title in indices]
    starts.sort(key=lambda x: x[0])

    # limites
    results = []
    for i, (pos, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        chunk = text[pos:end].strip()
        if not chunk:
            continue

        # remove título duplicado no começo se existir
        # (heurística: remove primeiro line match)
        chunk_lines = chunk.splitlines()
        if chunk_lines:
            first_line = chunk_lines[0].strip()
            if title.lower() in first_line.lower() or first_line.lower() == title.lower():
                chunk = "\n".join(chunk_lines[1:]).strip()

        results.append((title, chunk))
    return results


def detect_chapters(text: str) -> Tuple[List[Tuple[str, str]], str]:
    """
    Retorna (capítulos, método_usado).
    Capítulos: lista de (titulo, conteudo).
    """
    text = normalize_whitespace(text)

    # 1) Prioridade SUMÁRIO / ÍNDICE
    # Tenta pegar janela do sumário e extrair títulos
    toc_info = detect_sumario_sections(text)
    if toc_info and toc_info.get("section"):
        toc_block = toc_info["section"]
        titles = extract_titles_from_toc_block(toc_block)
        # critério: número mínimo de títulos razoável
        if len(titles) >= 3:
            indices = find_occurrences_indices(text, titles)

            # validação: precisamos de pelo menos 2 índices para separar
            if len(indices) >= 2:
                chapters = split_by_indices(text, indices)
                # validação: evita "chapters" vazios
                chapters = [(t, c) for (t, c) in chapters if c.strip()]
                if len(chapters) >= 2:
                    return chapters, "sumário"

    # 2) Prioridade padrões "Capítulo/Parte"
    # Cria uma lista de marcadores usando regex multiline
    markers = []
    # Tenta encontrar títulos no início de linhas
    # Aceita: "Capítulo 1", "Capítulo I", "Capítulo - 1", "Parte 1", "Chapter 1"
    cap_re = re.compile(
        r"^(?P<prefix>(cap[ií]tulo|chapter|parte|part))\s*(?P<num>[0-9]+|[ivxlcdm]+)\s*[\.\-:–]?\s*(?P<title>.+)?$",
        flags=re.IGNORECASE | re.MULTILINE,
    )

    for m in cap_re.finditer(text):
        prefix = m.group("prefix").strip()
        num = m.group("num").strip()
        tail = (m.group("title") or "").strip()
        title = f"{prefix.capitalize()} {num}"
        if tail:
            # limita comprimento do título
            tail = re.sub(r"\s+", " ", tail)
            if len(tail) <= 90:
                title = f"{title}: {tail}"
        # início do marcador = posição do match
        markers.append((m.start(), title))

    # remove duplicados por título/posição muito próxima
    markers.sort(key=lambda x: x[0])
    cleaned = []
    last_pos = None
    seen_titles = set()
    for pos, title in markers:
        if last_pos is not None and abs(pos - last_pos) < 30:
            continue
        key = title.lower()
        if key in seen_titles and last_pos is not None:
            continue
        seen_titles.add(key)
        cleaned.append((pos, title))
        last_pos = pos

    # só aceita se quantidade razoável
    if len(cleaned) >= 2:
        chapters = split_by_indices(text, cleaned)
        chapters = [(t, c) for (t, c) in chapters if c.strip()]
        if len(chapters) >= 2:
            return chapters, "padrão"

    # 3) Fallback por blocos (~3000 caracteres) sem cortar no meio de frase
    # Heurística: tenta quebrar em últimos separadores (".", "!", "?" ou "\n\n") perto do limite.
    target = 3000
    chunks = []
    remaining = text.strip()

    while len(remaining) > 0:
        if len(remaining) <= target:
            chunks.append(("Bloco", remaining))
            break

        segment = remaining[:target]
        # tenta encontrar último separador natural
        sep_positions = []
        for sep in ["\n\n", ". ", "! ", "? ", "; ", ":", "\n"]:
            idx = segment.rfind(sep)
            if idx != -1:
                sep_positions.append(idx)

        if sep_positions:
            cut = max(sep_positions)
            # cut pode ficar cedo demais
            if cut < 800:
                cut = target
        else:
            cut = target

        piece = remaining[:cut].strip()
        if piece:
            chunks.append(("Bloco", piece))
        remaining = remaining[cut:].strip()

        # evita loop infinito
        if not remaining or (len(piece) == 0):
            break

    # titula por número sequencial
    chapters = []
    for i, (_, c) in enumerate(chunks, start=1):
        chapters.append((f"Capítulo {i}", c))
    return chapters, "fallback"


# ---------------------------
# Chunking para TTS
# ---------------------------

def split_text_for_tts(text: str, max_chars: int = 1500) -> List[str]:
    text = normalize_whitespace(text)
    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    parts = []
    remaining = text

    while len(remaining) > 0:
        if len(remaining) <= max_chars:
            parts.append(remaining.strip())
            break

        segment = remaining[:max_chars]
        # procura separadores naturais
        seps = ["\n\n", ". ", "! ", "? ", "; ", ": ", ", "]
        cut_candidates = []
        for sep in seps:
            idx = segment.rfind(sep)
            if idx != -1:
                cut_candidates.append(idx)

        if cut_candidates:
            cut = max(cut_candidates)
            if cut < 400:
                cut = max_chars
        else:
            cut = max_chars

        chunk = remaining[:cut].strip()
        if chunk:
            parts.append(chunk)
        remaining = remaining[cut:].strip()

        if not chunk and not remaining:
            break

    # remove vazios
    parts = [p for p in parts if p.strip()]
    return parts


# ---------------------------
# TTS edge-tts (com retry)
# ---------------------------

async def edge_tts_speak_to_file(text: str, voice: str, output_mp3: str, rate: str = "0%") -> None:
    """
    Gera MP3 via edge-tts.
    Observação: edge-tts escreve em chunks/stream; aqui usamos comunicações padrão.
    """
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch="0st")
    # edge-tts gera áudio no formato do endpoint; o arquivo final aqui será mp3
    # edge-tts utiliza formato MP3 quando codec apropriado.
    # Na prática, edge-tts .save retorna bytes stream para mp3.
    # Vamos gravar em arquivo.
    with open(output_mp3, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])


async def edge_tts_try_with_retry(text: str, voice: str, output_mp3: str, retries: int = 3) -> bool:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # remove arquivo anterior para garantir que não existe resíduo
            if os.path.exists(output_mp3):
                os.remove(output_mp3)

            await edge_tts_speak_to_file(text=text, voice=voice, output_mp3=output_mp3)
            # valida existência e tamanho
            if os.path.exists(output_mp3) and os.path.getsize(output_mp3) > 0:
                return True
            last_err = RuntimeError("edge-tts gerou arquivo vazio.")
        except Exception as e:
            last_err = e
        # backoff simples
        await asyncio_sleep_safely(0.5 * attempt)
    # fallback falhou
    raise RuntimeError(f"edge-tts falhou após {retries} tentativas: {last_err}")


async def asyncio_sleep_safely(seconds: float) -> None:
    # Evita import repetido e mantém compatibilidade
    import asyncio
    await asyncio.sleep(seconds)


# ---------------------------
# Fallback gTTS (pt)
# ---------------------------

def gtts_speak_to_file(text: str, output_mp3: str) -> None:
    tts = gTTS(text=text, lang="pt", slow=False)
    # gTTS cria mp3 via gravação em arquivo
    tts.save(output_mp3)


def validate_audio_file(path: str) -> bool:
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) <= 0:
        return False
    # valida metadados mínimos (MP3)
    try:
        _ = MP3(path)
        return True
    except Exception:
        # mesmo que MP3 falhe, tamanho > 0 pode existir (mas é arriscado)
        return False


# ---------------------------
# Concatenar chunks de TTS (edge/gTTS)
# ---------------------------

def concat_mp3_files(parts: List[str], output_mp3: str) -> None:
    """
    Concatena MP3s sequencialmente com simples append de bytes.
    Observação: MP3 frames geralmente permitem concatenação por append.
    Para robustez mínima, validamos arquivos antes.
    """
    with open(output_mp3, "wb") as out_f:
        for p in parts:
            if os.path.exists(p) and os.path.getsize(p) > 0:
                with open(p, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f)


async def synthesize_chapter_mp3(
    chapter_text: str,
    voice: str,
    output_mp3: str,
    progress_prefix: str,
    st_progress=None
) -> Tuple[bool, str]:
    """
    Retorna (ok, metodo).
    Metodo: "edge-tts", "gTTS", ou "erro".
    """
    chunks = split_text_for_tts(chapter_text, max_chars=1500)
    if not chunks:
        return False, "erro"

    # Se houver múltiplos chunks, geramos cada chunk em arquivo temporário e concatenamos.
    tmp_dir = tempfile.mkdtemp(prefix="tts_chunks_")
    tmp_files = []

    try:
        # Primeiro tenta edge-tts
        edge_ok = True
        edge_chunk_files = []

        # Vamos tentar edge chunk a chunk; se falhar, aborta e faz fallback do capítulo inteiro em gTTS
        for i, chunk in enumerate(chunks, start=1):
            tmp_path = os.path.join(tmp_dir, f"edge_{i:03d}.mp3")
            try:
                # retry dentro de cada chunk
                for attempt in range(1, 4):
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                        await edge_tts_speak_to_file(text=chunk, voice=voice, output_mp3=tmp_path)
                        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                            break
                        raise RuntimeError("Arquivo vazio após edge-tts")
                    except Exception:
                        if attempt >= 3:
                            raise
                        await asyncio_sleep_safely(0.4 * attempt)

                # valida
                if not validate_audio_file(tmp_path):
                    raise RuntimeError("Validação falhou para edge-tts chunk")

                edge_chunk_files.append(tmp_path)

                if st_progress is not None:
                    # pequena atualização interna
                    # (não excede o progresso principal)
                    pass

            except Exception:
                edge_ok = False
                break

        if edge_ok and edge_chunk_files:
            concat_mp3_files(edge_chunk_files, output_mp3)
            if validate_audio_file(output_mp3):
                return True, "edge-tts"

        # fallback para gTTS (capítulo inteiro, ou por chunks se necessário)
        gtts_chunk_files = []
        for i, chunk in enumerate(chunks, start=1):
            tmp_path = os.path.join(tmp_dir, f"gtts_{i:03d}.mp3")
            gtts_chunk_files.append(tmp_path)
            # gTTS pode ter limites por tamanho; como fazemos chunking, tende a funcionar
            gtts_speak_to_file(chunk, tmp_path)
            if not validate_audio_file(tmp_path):
                raise RuntimeError("Validação falhou para gTTS chunk")

        concat_mp3_files(gtts_chunk_files, output_mp3)
        if validate_audio_file(output_mp3):
            return True, "gTTS"
        return False, "erro"

    finally:
        # limpeza
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


# ---------------------------
# Metadados com mutagen
# ---------------------------

def set_mp3_metadata(
    mp3_path: str,
    title: str,
    author: str,
    track_num: int,
    year: Optional[str] = None
) -> None:
    """
    Insere metadados básicos usando EasyID3.
    """
    try:
        audio = EasyID3(mp3_path)
    except Exception:
        # se não existir tag, cria
        audio = EasyID3()
        audio.save(mp3_path)

    audio["title"] = [title]
    audio["artist"] = [author]
    audio["tracknumber"] = [str(track_num)]
    if year:
        # frame "date" costuma ser aceito
        audio["date"] = [str(year)]
    audio.save(mp3_path)


# ---------------------------
# Vozes edge-tts
# ---------------------------

VOICE_OPTIONS = [
    ("pt-BR-FranciscaNeural", "Francisca (Feminina)"),
    ("pt-BR-AntonioNeural", "Antonio (Masculina)"),
    ("pt-BR-BrendaNeural", "Brenda"),
    ("pt-BR-DonatoNeural", "Donato"),
    ("pt-BR-FabioNeural", "Fabio"),
]

VOICE_MAP = {friendly: tech for tech, friendly in VOICE_OPTIONS}
TECH_BY_FRIENDLY = {friendly: tech for tech, friendly in VOICE_OPTIONS}


# ---------------------------
# App principal
# ---------------------------

def main():
    init_session_state()

    st.set_page_config(page_title="PDF/EPUB → Audiobook (edge-tts + fallback)", layout="wide")
    st.title("📚 Transforme PDF/EPUB em Audiobooks (MP3)")

    st.markdown(
        """
        - Upload de **PDF** e **EPUB**
        - Detecta **capítulos** (Sumário → Padrões → Fallback)
        - Gera **MP3 por faixa** (`001.mp3`, `002.mp3`, ...)
        - Usa **edge-tts** com retry e **fallback para gTTS (pt)** se necessário
        """
    )

    uploaded = st.file_uploader("Envie um arquivo PDF ou EPUB", type=["pdf", "epub"])

    col1, col2 = st.columns(2)
    with col1:
        friendly_voice_default = "Francisca (Feminina)"
        selected_friendly_voice = st.selectbox(
            "Selecione a voz (edge-tts)",
            options=[friendly for _, friendly in VOICE_OPTIONS],
            index=[friendly for _, friendly in VOICE_OPTIONS].index(friendly_voice_default)
        )
        selected_voice_tech = TECH_BY_FRIENDLY[selected_friendly_voice]

    with col2:
        title = st.text_input("Título do livro", value="Meu Audiobook")
        author = st.text_input("Autor", value="Autor Desconhecido")
        year = st.text_input("Ano (opcional)", value="")

    st.divider()

    if uploaded is None:
        st.info("Faça upload de um arquivo PDF ou EPUB para começar.")
        return

    file_bytes = uploaded.read()
    file_name = uploaded.name
    st.write(f"**Arquivo:** {file_name} | **Tamanho:** {len(file_bytes)} bytes")

    if st.button("Gerar Audiobook", type="primary", disabled=not file_bytes):
        # reset state
        st.session_state.chapters = []
        st.session_state.audio_files = []
        st.session_state.method = None
        st.session_state.output_dir = None
        st.session_state.log_messages = []

        progress = st.progress(0, text="Preparando...")
        status = st.empty()

        # output dir temporário
        output_root = tempfile.mkdtemp(prefix="audiobook_out_")
        st.session_state.output_dir = output_root

        # Para preview
        preview_area = st.container()
        preview_area.subheader("🔎 Preview dos capítulos detectados")

        try:
            # 1) Extrair texto
            progress.progress(5, text="Extraindo texto do arquivo...")
            status.write("Extraindo texto...")
            text = extract_text(file_name, file_bytes)
            text = normalize_whitespace(text)

            if not text or len(text) < 200:
                st.error("Não foi possível extrair texto suficiente do arquivo.")
                return

            # 2) Detectar capítulos
            progress.progress(15, text="Detectando capítulos...")
            status.write("Detectando capítulos...")
            chapters, method = detect_chapters(text)
            st.session_state.chapters = chapters
            st.session_state.method = method

            if not chapters:
                st.error("Falha ao detectar capítulos. Tente outro arquivo/formatos.")
                return

            st.write(f"**Método de divisão:** {method}")
            st.write(f"**Número de capítulos detectados:** {len(chapters)}")

            # preview
            preview_limit = min(5, len(chapters))
            for i in range(preview_limit):
                ch_title, ch_text = chapters[i]
                snippet = normalize_whitespace(ch_text)[:500]
                if len(snippet) < len(ch_text):
                    snippet = snippet + "..."
                preview_area.markdown(f"**{i+1:02d}. {ch_title}**  \n> {snippet}\n")

            # 3) Gerar áudios
            progress.progress(18, text="Gerando MP3s... (isso pode levar alguns minutos)")
            status.write("Iniciando síntese de fala...")

            audio_files = []
            total = len(chapters)

            # Criar diretório de saída
            out_audio_dir = os.path.join(output_root, "audio")
            os.makedirs(out_audio_dir, exist_ok=True)

            # Para não travar: processa sequencial (sem paralelismo)
            for idx, (ch_title, ch_text) in enumerate(chapters, start=1):
                pct = 18 + int((idx / total) * 80)
                progress.progress(min(pct, 98), text=f"Gerando faixa {idx:03d}/{total:03d}...")

                out_mp3 = os.path.join(out_audio_dir, f"{idx:03d}.mp3")

                # Garantir texto mínimo
                ch_text_clean = normalize_whitespace(ch_text)
                if len(ch_text_clean) < 20:
                    log_msg(f"Capítulo {idx:03d} muito curto; pulando geração.")
                    continue

                try:
                    status.write(f"Sintetizando: {ch_title} (#{idx:03d})")
                    ok, metodo = synthesize_chapter_mp3(
                        chapter_text=ch_text_clean,
                        voice=selected_voice_tech,
                        output_mp3=out_mp3,
                        progress_prefix=f"{idx:03d}",
                        st_progress=progress
                    )

                    if not ok or not validate_audio_file(out_mp3):
                        raise RuntimeError("Áudio gerado inválido.")

                    # metadados
                    try:
                        year_val = year.strip() if year.strip() else None
                        set_mp3_metadata(
                            mp3_path=out_mp3,
                            title=ch_title,
                            author=author.strip() or "Autor Desconhecido",
                            track_num=idx,
                            year=year_val
                        )
                    except Exception as e:
                        # Não quebra o app por falha de metadata
                        log_msg(f"Aviso: falha ao inserir metadata no arquivo {idx:03d}.mp3: {e}")

                    audio_files.append(out_mp3)
                    log_msg(f"OK: faixa {idx:03d} gerada via {metodo}.")

                except Exception as e:
                    # robustez: não quebra app
                    err = "".join(traceback.format_exception_only(type(e), e)).strip()
                    log_msg(f"Erro na faixa {idx:03d}: {err}")

                    # se não gerou arquivo, não adiciona
                    if os.path.exists(out_mp3) and validate_audio_file(out_mp3):
                        audio_files.append(out_mp3)
                    else:
                        # remove arquivo corrompido se existir
                        try:
                            if os.path.exists(out_mp3):
                                os.remove(out_mp3)
                        except Exception:
                            pass

            # Validação final
            progress.progress(99, text="Finalizando...")
            status.write("Validando arquivos e compactando...")

            audio_files = [p for p in audio_files if validate_audio_file(p)]
            if not audio_files:
                st.error("Nenhum áudio válido foi gerado. Verifique o arquivo de entrada e tente novamente.")
                return

            # Criar ZIP
            zip_path = os.path.join(output_root, "audiobook.zip")
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for p in sorted(audio_files, key=lambda x: os.path.basename(x)):
                    arcname = os.path.join("audio", os.path.basename(p))
                    zf.write(p, arcname=arcname)

            if not os.path.exists(zip_path) or os.path.getsize(zip_path) <= 0:
                st.error("Falha ao criar ZIP final (ZIP vazio ou inválido).")
                return

            st.success("✅ Audiobook gerado com sucesso!")

            # Download
            with open(zip_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download do ZIP",
                    data=f,
                    file_name="audiobook.zip",
                    mime="application/zip",
                )

            # Mostrar contagem
            st.write(f"**Faixas válidas geradas:** {len(audio_files)}")

            # Mostrar logs resumidos
            with st.expander("Ver logs / detalhes"):
                for m in st.session_state.log_messages[-200:]:
                    st.write(m)

        except Exception as e:
            st.error(f"Erro inesperado: {e}")
            with st.expander("Detalhes do erro"):
                st.code(traceback.format_exc())
        finally:
            progress.progress(100, text="Concluído.")


if __name__ == "__main__":
    main()
