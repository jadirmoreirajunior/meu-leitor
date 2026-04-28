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


# ---------------- SUMÁRIO ---------------- #
def extrair_sumario(texto):
    linhas = texto.split('\n')
    sumario = []
    encontrou = False

    for linha in linhas:
        linha_limpa = linha.strip()

        if re.search(r'sum[áa]rio|índice', linha_limpa, re.IGNORECASE):
            encontrou = True
            continue

        if encontrou:
            if len(linha_limpa) > 80:
                break

            if not linha_limpa:
                continue

            if 3 < len(linha_limpa) < 60:
                sumario.append(linha_limpa)

            if len(sumario) > 100:
                break

    return sumario


# ---------------- DIVISÃO POR SUMÁRIO ---------------- #
def dividir_por_sumario(texto, sumario):
    capitulos = []
    texto_lower = texto.lower()

    posicoes = []

    for item in sumario:
        item_limpo = item.strip().lower()
        pos = texto_lower.find(item_limpo)

        if pos != -1:
            posicoes.append((pos, item.strip()))

    posicoes.sort()

    if len(posicoes) < 3:
        return []

    for i in range(len(posicoes)):
        inicio = posicoes[i][0]
        titulo = posicoes[i][1]

        if i + 1 < len(posicoes):
            fim = posicoes[i + 1][0]
        else:
            fim = len(texto)

        conteudo = texto[inicio:fim].strip()

        if len(conteudo) > 200:
            capitulos.append((titulo, conteudo))

    return capitulos


# ---------------- DIVISÃO POR PADRÃO ---------------- #
def dividir_capitulos(texto):
    texto = texto.replace('\r', '\n')

    padrao = re.compile(
        r'\n\s*(CAP[IÍ]TULO\s+\d+|Cap[ií]tulo\s+\d+|'
        r'PARTE\s+\d+|Parte\s+\d+|'
        r'CAP[IÍ]TULO\s+[IVXLCDM]+|Cap[ií]tulo\s+[IVXLCDM]+|'
        r'PARTE\s+[IVXLCDM]+|Parte\s+[IVXLCDM]+)\s*\n',
        re.IGNORECASE
    )

    partes = padrao.split(texto)
    capitulos = []

    if len(partes) > 2:
        for i in range(1, len(partes), 2):
            titulo = partes[i].strip()
            conteudo = partes[i+1].strip() if i+1 < len(partes) else ""

            if len(conteudo) > 300:
                capitulos.append((titulo, conteudo))

    else:
        st.warning("⚠️ Não encontrei capítulos claros. Dividindo automaticamente...")

        tamanho_max = 5000
        texto_limpo = texto.strip()

        inicio = 0
        i = 1

        while inicio < len(texto_limpo):
            fim = inicio + tamanho_max
            trecho = texto_limpo[inicio:fim]

            ultimo_ponto = trecho.rfind('.')
            if ultimo_ponto != -1 and ultimo_ponto > 1000:
                fim = inicio + ultimo_ponto + 1

            bloco = texto_limpo[inicio:fim].strip()

            if bloco:
                capitulos.append((f"Parte {i}", bloco))
                i += 1

            inicio = fim

    return capitulos


# ---------------- ESCOLHA INTELIGENTE ---------------- #
def dividir_inteligente(texto):
    sumario = extrair_sumario(texto)

    capitulos = dividir_por_sumario(texto, sumario)

    if capitulos:
        return capitulos, "sumario"

    capitulos = dividir_capitulos(texto)

    if capitulos:
        return capitulos, "padrao"

    return [], "erro"


# ---------------- GERAÇÃO DO ZIP ---------------- #
async def gerar_zip(texto, voz, titulo, autor, ano):
    capitulos, metodo = dividir_inteligente(texto)

    if metodo == "sumario":
        st.success(f"✅ Divisão por SUMÁRIO ({len(capitulos)} capítulos)")
    elif metodo == "padrao":
        st.warning(f"⚠️ Divisão por padrão ({len(capitulos)} partes)")
    else:
        st.error("❌ Não foi possível dividir o texto")
        return None

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
                st.error(f"Erro no capítulo {num}: {e}")
                continue

            if not os.path.exists(caminho_tmp) or os.path.getsize(caminho_tmp) == 0:
                st.warning(f"Áudio vazio no capítulo {num}")
                continue

            try:
                audio = ID3()
                audio.add(TIT2(encoding=3, text=f"{titulo} - Parte {num}"))
                audio.add(TPE1(encoding=3, text=autor))
                audio.add(TALB(encoding=3, text=titulo))
                audio.add(TRCK(encoding=3, text=str(i)))
                if ano:
                    audio.add(TYER(encoding=3, text=ano))
                audio.save(caminho_tmp)
            except:
                pass

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
            st.error("Erro ao extrair texto.")
        else:
            capitulos, metodo = dividir_inteligente(texto)

            st.write(f"📚 Método detectado: {metodo}")
            st.write(f"📊 Capítulos detectados: {len(capitulos)}")

            for i, (tit, _) in enumerate(capitulos[:5], 1):
                st.write(f"{i}. {tit}")

            st.info("Convertendo... aguarde.")

            zip_data = asyncio.run(
                gerar_zip(texto, voz_sel, titulo, autor, ano)
            )

            if zip_data:
                st.download_button(
                    label="⬇️ Baixar Audiobook (.zip)",
                    data=zip_data.getvalue(),
                    file_name=f"{titulo.replace(' ', '_')}.zip",
                    mime="application/zip"
                )
