import streamlit as st
import os
import re
import asyncio
import edge_tts
import zipfile
import io
import nest_asyncio
from PyPDF2 import PdfReader
from ebooklib import epub
import ebooklib
from bs4 import BeautifulSoup
import tempfile

# Aplica nest_asyncio para resolver problemas de event loop
nest_asyncio.apply()

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
    try:
        if arquivo.name.endswith('.pdf'):
            reader = PdfReader(arquivo)
            textos = []
            for p in reader.pages:
                t = p.extract_text()
                if t:
                    textos.append(t)
            return "\n".join(textos)
        else:  # EPUB
            with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
                tmp.write(arquivo.getvalue())
                tmp_path = tmp.name

            livro = epub.read_epub(tmp_path)
            texto = ""

            for item in livro.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    texto += soup.get_text(separator='\n') + "\n"

            os.unlink(tmp_path)
            return texto
    except Exception as e:
        st.error(f"Erro na extração do texto: {str(e)}")
        return ""

# ---------------- SUMÁRIO MELHORADO ---------------- #
def extrair_sumario(texto):
    linhas = texto.split('\n')
    sumario = []
    encontrou = False
    count_sumario = 0
    
    # Padrões mais flexíveis para identificar sumário
    padroes_sumario = [
        r'sum[áa]rio', r'índice', r'conteúdo', 
        r'contents?', r'table of contents'
    ]
    
    for i, linha in enumerate(linhas):
        linha = linha.strip()
        
        # Verifica se é início do sumário
        if not encontrou:
            for padrao in padroes_sumario:
                if re.search(padrao, linha, re.IGNORECASE):
                    encontrou = True
                    break
            continue
        
        # Fim do sumário (marcadores comuns)
        if encontrou:
            # Verifica se chegou ao fim do sumário
            if count_sumario > 5 and (len(linha) > 100 or re.match(r'^[IVXLCDM]+\.', linha)):
                break
            
            # Pula linhas vazias
            if not linha:
                if count_sumario > 0:
                    continue
                else:
                    continue
            
            # Filtra possíveis entradas de sumário
            if len(linha) > 5 and len(linha) < 100:
                # Remove números de página no final
                linha = re.sub(r'\s+\.{2,}\s+\d+$', '', linha)
                linha = re.sub(r'\s+\d+$', '', linha)
                sumario.append(linha)
                count_sumario += 1
            
            # Limite de itens
            if len(sumario) >= 50:
                break
    
    return sumario

# ---------------- DIVISÃO POR SUMÁRIO ---------------- #
def dividir_por_sumario(texto, sumario):
    if len(sumario) < 2:
        return []
    
    capitulos = []
    texto_lower = texto.lower()
    posicoes = []

    for item in sumario:
        # Busca de forma mais flexível
        pos = texto_lower.find(item.lower())
        if pos == -1:
            # Tenta buscar apenas a primeira palavra
            primeira_palavra = item.split()[0].lower() if item.split() else ""
            if primeira_palavra:
                pos = texto_lower.find(primeira_palavra)
        
        if pos != -1:
            posicoes.append((pos, item))

    if not posicoes:
        return []
    
    posicoes.sort()
    
    # Remove duplicatas próximas
    posicoes_filtradas = []
    for i, (pos, tit) in enumerate(posicoes):
        if i == 0 or pos - posicoes[i-1][0] > 100:
            posicoes_filtradas.append((pos, tit))
    
    if len(posicoes_filtradas) < 2:
        return []
    
    for i in range(len(posicoes_filtradas)):
        inicio = posicoes_filtradas[i][0]
        titulo = posicoes_filtradas[i][1]
        fim = posicoes_filtradas[i+1][0] if i+1 < len(posicoes_filtradas) else len(texto)
        
        conteudo = texto[inicio:fim].strip()
        
        # Valida tamanho mínimo do capítulo
        if len(conteudo) > 300:
            # Limpa o título
            titulo_limpo = re.sub(r'\d+$', '', titulo).strip()
            capitulos.append((titulo_limpo, conteudo))
    
    return capitulos

# ---------------- FALLBACK MELHORADO ---------------- #
def dividir_capitulos(texto):
    texto = texto.replace('\r', '\n')
    
    # Padrões mais abrangentes para capítulos
    padroes = [
        r'\n\s*CAP[IÍ]TULO\s+(\d+|[IVXLCDM]+)\s*\n',
        r'\n\s*PARTE\s+(\d+|[IVXLCDM]+)\s*\n',
        r'\n\s*(\d+)\.\s+\w+',
        r'\n\s*([IVXLCDM]+)\.\s+\w+'
    ]
    
    capitulos = []
    
    for padrao in padroes:
        matches = list(re.finditer(padrao, texto, re.IGNORECASE))
        if len(matches) >= 2:
            for i, match in enumerate(matches):
                inicio = match.start()
                titulo = match.group().strip()
                fim = matches[i+1].start() if i+1 < len(matches) else len(texto)
                
                conteudo = texto[inicio:fim].strip()
                if len(conteudo) > 300:
                    capitulos.append((titulo, conteudo))
            break
    
    # Fallback final: divisão por parágrafos
    if len(capitulos) < 2:
        paragrafos = texto.split('\n\n')
        capitulo_atual = ""
        contador = 1
        
        for paragrafo in paragrafos:
            if len(capitulo_atual) + len(paragrafo) < 3000:
                capitulo_atual += paragrafo + "\n\n"
            else:
                if capitulo_atual.strip():
                    capitulos.append((f"Capítulo {contador}", capitulo_atual.strip()))
                    contador += 1
                    capitulo_atual = paragrafo + "\n\n"
        
        if capitulo_atual.strip():
            capitulos.append((f"Capítulo {contador}", capitulo_atual.strip()))
    
    return capitulos

# ---------------- ESCOLHA INTELIGENTE ---------------- #
def dividir_inteligente(texto):
    if not texto:
        return [], "erro"
    
    sumario = extrair_sumario(texto)
    
    if len(sumario) >= 3:
        capitulos = dividir_por_sumario(texto, sumario)
        if len(capitulos) >= 3:
            return capitulos, "sumario"
    
    capitulos = dividir_capitulos(texto)
    
    # Validação final
    capitulos_validos = [(tit, cont) for tit, cont in capitulos if len(cont) > 200]
    
    return capitulos_validos, "fallback"

# 🔥 DIVISÃO PARA TTS OTIMIZADA
def dividir_texto_tts(texto, max_chars=800):
    """Divide texto em partes menores e mais gerenciáveis para TTS"""
    if not texto:
        return []
    
    # Remove quebras de linha excessivas
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    
    partes = []
    frases = re.split(r'(?<=[.!?])\s+', texto)
    
    parte_atual = ""
    
    for frase in frases:
        if len(parte_atual) + len(frase) + 1 <= max_chars:
            parte_atual += frase + " "
        else:
            if parte_atual.strip():
                partes.append(parte_atual.strip())
            parte_atual = frase + " "
    
    if parte_atual.strip():
        partes.append(parte_atual.strip())
    
    return partes if partes else [texto[:max_chars]]

# ---------------- GERAÇÃO CORRIGIDA ---------------- #
async def gerar_audio_parte(texto, voz, caminho):
    """Gera áudio para uma parte do texto"""
    try:
        communicate = edge_tts.Communicate(texto, VOZES[voz])
        stream = communicate.stream()
        
        with open(caminho, "ab") as f:
            async for chunk in stream:
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
        return True
    except Exception as e:
        st.warning(f"Erro na geração: {str(e)[:100]}")
        return False

async def gerar_zip(texto, voz, titulo, autor):
    if not texto:
        st.error("Texto extraído está vazio!")
        return io.BytesIO()
    
    capitulos, metodo = dividir_inteligente(texto)
    
    if not capitulos:
        st.error("Não foi possível dividir o livro em capítulos!")
        return io.BytesIO()
    
    st.write(f"📚 Método: {metodo} | Capítulos: {len(capitulos)}")
    
    zip_buffer = io.BytesIO()
    barra = st.progress(0)
    status = st.empty()
    
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        for i, (tit, cont) in enumerate(capitulos, 1):
            num = f"{i:03d}"
            status.text(f"Processando capítulo {i}/{len(capitulos)}: {tit[:50]}")
            
            # Verifica se o conteúdo é válido
            if not cont or len(cont) < 100:
                st.warning(f"Capítulo {num} ignorado (muito curto)")
                continue
            
            # Cria arquivo temporário
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                caminho = tmp.name
            
            # Divide o capítulo em partes
            partes = dividir_texto_tts(f"{tit}. {cont}")
            sucesso = False
            
            # Gera cada parte
            for j, parte in enumerate(partes):
                if not parte.strip():
                    continue
                
                # Adiciona título apenas na primeira parte
                if j > 0:
                    parte = parte
                
                for tentativa in range(3):
                    sucesso_parcial = await gerar_audio_parte(parte, voz, caminho)
                    if sucesso_parcial:
                        sucesso = True
                        break
                    await asyncio.sleep(0.5)
            
            # Verifica se o arquivo foi gerado com sucesso
            if sucesso and os.path.exists(caminho) and os.path.getsize(caminho) > 1000:
                zip_file.write(caminho, f"{num} - {tit[:30]}.mp3")
                st.success(f"✅ Capítulo {num} concluído")
            else:
                st.error(f"❌ Falha no capítulo {num}")
            
            # Limpeza
            if os.path.exists(caminho):
                os.unlink(caminho)
            
            barra.progress(i / len(capitulos))
    
    status.text("Processamento concluído!")
    zip_buffer.seek(0)
    return zip_buffer

# ---------------- FUNÇÃO SÍNCRONA PARA UI ---------------- #
def gerar_zip_sync(texto, voz, titulo, autor):
    """Wrapper síncrono para chamada assíncrona"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(gerar_zip(texto, voz, titulo, autor))
    finally:
        loop.close()

# ---------------- UI MELHORADA ---------------- #
st.title("☁️ Audiobook Cloud")
st.markdown("Converta seus livros em audiobooks com voz natural")

with st.sidebar:
    st.header("Instruções")
    st.markdown("""
    1. Faça upload do arquivo (PDF ou EPUB)
    2. Escolha a voz desejada
    3. Informe título e autor
    4. Clique em "Gerar Audiobook"
    
    **Nota:** Livros grandes podem levar alguns minutos.
    """)

col1, col2 = st.columns(2)

with col1:
    arquivo = st.file_uploader("📁 Arquivo do livro", type=["pdf", "epub"])
    voz = st.selectbox("🎙️ Selecione a voz", list(VOZES.keys()))

with col2:
    titulo = st.text_input("📖 Título do livro")
    autor = st.text_input("✍️ Autor")

if st.button("🚀 Gerar Audiobook", type="primary"):
    if not arquivo:
        st.error("Por favor, faça upload de um arquivo PDF ou EPUB")
    elif not titulo:
        st.error("Por favor, informe o título do livro")
    elif not autor:
        st.error("Por favor, informe o autor do livro")
    else:
        try:
            with st.spinner("Extraindo texto do arquivo..."):
                texto = extrair_texto(arquivo)
            
            if not texto or len(texto) < 500:
                st.error("Texto extraído muito curto ou inválido. Verifique o arquivo.")
            else:
                st.success(f"Texto extraído: {len(texto):,} caracteres")
                
                with st.spinner("Gerando audiobook. Isso pode levar alguns minutos..."):
                    zip_data = gerar_zip_sync(texto, voz, titulo, autor)
                
                if zip_data and zip_data.getbuffer().nbytes > 0:
                    st.success("✅ Audiobook gerado com sucesso!")
                    
                    st.download_button(
                        label="📥 Baixar ZIP com todos os capítulos",
                        data=zip_data.getvalue(),
                        file_name=f"{titulo.replace(' ', '_')}_{autor.replace(' ', '_')}.zip",
                        mime="application/zip"
                    )
                else:
                    st.error("Falha ao gerar o audiobook. ZIP vazio.")
                    
        except Exception as e:
            st.error(f"Erro durante o processamento: {str(e)}")
            st.exception(e)
