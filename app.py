# --- SUBSTITUA APENAS ESTAS FUNÇÕES NO SEU CÓDIGO ---

# 🔥 NOVA FUNÇÃO: divisão inteligente (~10 partes)
def split_text(text):
    if not isinstance(text, str):
        text = str(text)

    total_len = len(text)
    target_parts = 10

    chunk_size = total_len // target_parts
    chunk_size = max(3000, chunk_size)
    chunk_size = min(15000, chunk_size)

    chunks = []
    i = 0

    while i < total_len:
        end = i + chunk_size

        if end < total_len:
            last_dot = text.rfind(".", i, end)
            if last_dot != -1 and last_dot > i + 1000:
                end = last_dot + 1

        part = text[i:end].strip()

        if part:
            chunks.append({
                "title": f"Parte {len(chunks)+1}",
                "content": part
            })

        i = end

    return chunks


# 🔥 NOVA FUNÇÃO HÍBRIDA
def split_hybrid(text):
    chapters = split_by_chapters(text)

    # poucos capítulos → provavelmente falhou
    if len(chapters) < 3:
        return split_text(text)

    # capítulos demais → reduz automaticamente
    if len(chapters) > 50:
        full_text = "\n\n".join([c["content"] for c in chapters])
        return split_text(full_text)

    return chapters


# 🔥 EPUB COM SPINE CORRETO
def extract_text_epub(file):
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())

    try:
        book = epub.read_epub("temp.epub")

        texts = []

        # 🔥 USANDO SPINE (ordem real do livro)
        for item_id, _ in book.spine:
            item = book.get_item_with_id(item_id)

            if item:
                soup = BeautifulSoup(item.get_content(), "html.parser")

                for tag in soup(["script", "style", "img", "svg"]):
                    tag.decompose()

                text = soup.get_text(separator="\n").strip()

                if len(text) > 200:
                    texts.append(text)

        full_text = "\n\n".join(texts)

        # 🔥 aplica modo híbrido
        return split_hybrid(full_text)

    finally:
        if os.path.exists("temp.epub"):
            os.remove("temp.epub")
