import streamlit as st
import os
import re
import asyncio
import edge_tts
import zipfile
import io
from PyPDF2 import PdfReader
from ebooklib import epub
import ebooklib
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, TRCK
import tempfile

st.set_page_config(page_title="Audiobook Cloud", page_icon="☁️")

VOZES = {
    "Francisca (Padrão - Fem)": "pt-BR-FranciscaNeural",
    "Antonio (Padrão - Masc)": "pt-BR-AntonioNeural",
    "Thalita (Jovem - Fem)": "pt-BR-ThalitaNeural",
    "Brenda (Clara - Fem)": "pt-BR-BrendaNeural",
    "Donato (Profunda - Masc)": "pt-BR-DonatoNeural",
    "Fabio (Madura - Masc)": "pt-BR-FabioNeural"
}

# ---------------- EXTRAÇÃO DE TEXTO ---------------- #
def extrair_texto(arquivo):
    if arquivo.name.endswith('.pdf'):
        reader = PdfReader(arquivo)
        textos = []
        for p in reader.pages:
            t = p.extract_text()
            if t:
                textos.append(t)
        return "\n".join(textos)

    else:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
            tmp.write(arquivo.getvalue())
            tmp_path = tmp.name

        livro = epub.read_epub(tmp_path)
        texto = ""

        for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            texto += soup.get_text(separator='\n') + "\n"

        os.unlink(tmp_path)
        return texto


# ---------------- DIVISÃO DE CAPÍTULOS ---------------- #
def dividir_capitulos(texto):
    # Normaliza quebras
    texto = texto.replace('\r', '\n')

    # 🔹 Padrões mais completos
    padrao = re.compile(
        r'\n\s*(CAP[IÍ]TULO\s+\d+|Cap[ií]tulo\s+\d+|'
        r'PARTE\s+\d+|Parte\s+\d+|'
        r'CAP[IÍ]TULO\s+[IVXLCDM]+|Cap[ií]tulo\s+[IVXLCDM]+|'
        r'PARTE\s+[IVXLCDM]+|Parte\s+[IVXLCDM]+)\s*\n',
        re.IGNORECASE
    )

    partes = padrao.split(texto)

    capitulos = []

    # 🔹 Caso encontrou capítulos formais
    if len(partes) > 2:
        for i in range(1, len(partes), 2):
            titulo = partes[i].strip()
            conteudo = partes[i+1].strip() if i+1 < len(partes) else ""

            if len(conteudo) > 300:
                capitulos.append((titulo, conteudo))

    # 🔹 FALLBACK (muito importante!)
    else:
        st.warning("⚠️ Não encontrei capítulos claros. Dividindo automaticamente...")

        tamanho_max = 5000  # caracteres por bloco
        texto_limpo = texto.strip()

        blocos = []
        inicio = 0

        while inicio < len(texto_limpo):
            fim = inicio + tamanho_max

            # tenta quebrar em ponto final próximo
            trecho = texto_limpo[inicio:fim]
            ultimo_ponto = trecho.rfind('.')

            if ultimo_ponto != -1 and ultimo_ponto > 1000:
                fim = inicio + ultimo_ponto + 1

            bloco = texto_limpo[inicio:fim].strip()
            if bloco:
                blocos.append(bloco)

            inicio = fim

        for i, bloco in enumerate(blocos, 1):
            capitulos.append((f"Parte {i}", bloco))

    return capitulos

def extrair_sumario(texto):
    linhas = texto.split('\n')

    sumario = []
    encontrou = False

    for linha in linhas:
        linha = linha.strip()

        # Detecta início
        if re.search(r'sum[áa]rio|índice', linha, re.IGNORECASE):
            encontrou = True
            continue

        if encontrou:
            if re.search(r'cap[ií]tulo|parte', linha, re.IGNORECASE):
                sumario.append(linha)

            elif linha == "":
                break

    return sumario
    
# ---------------- GERAÇÃO DO ZIP ---------------- #
async def gerar_zip(texto, voz, titulo, autor, ano):
    capitulos = dividir_capitulos(texto)

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        barra = st.progress(0)

        for i, (tit, cont) in enumerate(capitulos, start=1):
            num = f"{i:03d}"

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
                caminho_tmp = tmp_mp3.name

            try:
                communicate = edge_tts.Communicate(f"{tit}. {cont}", VOZES[voz])
                await communicate.save(caminho_tmp)
            except Exception as e:
                st.error(f"Erro ao gerar áudio no capítulo {num}: {e}")
                continue

            # Verifica se o áudio foi gerado
            if not os.path.exists(caminho_tmp) or os.path.getsize(caminho_tmp) == 0:
                st.warning(f"Áudio vazio no capítulo {num}")
                continue

            # Metadados
            try:
                audio = ID3()
                audio.add(TIT2(encoding=3, text=f"{titulo} - Parte {num}"))
                audio.add(TPE1(encoding=3, text=autor))
                audio.add(TALB(encoding=3, text=titulo))
                audio.add(TRCK(encoding=3, text=str(i)))
                if ano:
                    audio.add(TYER(encoding=3, text=ano))
                audio.save(caminho_tmp)
            except Exception as e:
                st.warning(f"Erro ao adicionar metadados: {e}")

            zip_file.write(caminho_tmp, f"{num}.mp3")
            os.unlink(caminho_tmp)

            barra.progress(i / len(capitulos))

    zip_buffer.seek(0)
    return zip_buffer


# ---------------- INTERFACE ---------------- #
st.title("☁️ Audiobook Cloud Lab")

arquivo = st.file_uploader("Livro (PDF/EPUB)", type=['pdf', 'epub'])
voz_sel = st.selectbox("Escolha a voz", list(VOZES.keys()))
titulo = st.text_input("Título do livro")
autor = st.text_input("Autor")
ano = st.text_input("Ano (opcional)")

if st.button("🚀 Gerar Audiobook para Download"):
    if not arquivo:
        st.warning("Envie um arquivo.")
    elif not titulo or not autor:
        st.warning("Preencha título e autor.")
    else:
texto = extrair_texto(arquivo)

if not texto.strip():
    st.error("Não foi possível extrair texto do arquivo.")
else:
    # 🔹 NOVO: detectar sumário
    sumario = extrair_sumario(texto)

    if sumario:
        st.write("📑 Sumário detectado:")
        for linha in sumario[:10]:
            st.write(linha)
    else:
        st.write("📑 Nenhum sumário detectado.")

    # 🔹 Preview de capítulos
    capitulos_preview = dividir_capitulos(texto)

    st.write(f"📚 Capítulos detectados: {len(capitulos_preview)}")

    for i, (tit, _) in enumerate(capitulos_preview[:5], 1):
        st.write(f"{i}. {tit}")

    st.info("Convertendo... isso pode levar alguns minutos.")

            try:
                zip_data = asyncio.run(
                    gerar_zip(texto, voz_sel, titulo, autor, ano)
                )

                st.success("Conversão concluída!")

                st.download_button(
                    label="⬇️ Baixar Audiobook (.zip)",
                    data=zip_data.getvalue(),
                    file_name=f"{titulo.replace(' ', '_')}.zip",
                    mime="application/zip"
                )

            except Exception as e:
                st.error(f"Erro geral: {e}")
