import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import shutil
import re
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime
import pdfplumber
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from pathlib import Path
from typing import List, Dict
import time
import gc
import traceback

# --- CONFIGURAÇÃO ---
st.set_page_config(
    page_title="Narrador.AI Pro | Audiobook Inteligente",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS SIMPLIFICADO E LEVE ---
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        margin-bottom: 1.5rem;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.6rem 1.5rem;
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.3s;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    .info-box {
        background: #f0f2f6;
        padding: 1rem;
        border-radius: 10px;
        margin: 0.5rem 0;
    }
    
    .success-box {
        background: #d4edda;
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
</style>
""", unsafe_allow_html=True)

# --- DIRETÓRIOS ---
OUTPUT_DIR = Path("audiobook_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# --- VOZES VALIDADAS ---
VOICES = {
    "🇧🇷 Português": {
        "Antonio (Masculino)": "pt-BR-AntonioNeural",
        "Francisca (Feminina)": "pt-BR-FranciscaNeural",
        "Brenda (Feminina)": "pt-BR-BrendaNeural",
        "Donato (Masculino)": "pt-BR-DonatoNeural",
        "Thalita (Feminina)": "pt-BR-ThalitaNeural"
    },
    "🌍 Multilíngue": {
        "Alessio (Italiano)": "it-IT-AlessioMultilingualNeural",
        "Andrew (Inglês)": "en-US-AndrewMultilingualNeural",
        "Emma (Inglês)": "en-US-EmmaMultilingualNeural",
        "Ava (Inglês)": "en-US-AvaMultilingualNeural"
    },
    "🇺🇸 Inglês": {
        "Jenny (Feminina)": "en-US-JennyNeural",
        "Guy (Masculino)": "en-US-GuyNeural"
    }
}

# --- FUNÇÕES AUXILIARES ---
def limpar_texto(texto: str) -> str:
    """Limpa texto removendo caracteres problemáticos"""
    # Remove caracteres de controle exceto newlines e tabs
    texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', texto)
    # Normaliza espaços
    texto = re.sub(r'\n\s*\n\s*\n+', '\n\n', texto)
    # Remove linhas muito curtas repetidas
    linhas = texto.split('\n')
    linhas_filtradas = []
    for linha in linhas:
        linha = linha.strip()
        if len(linha) > 2 or (len(linha) == 0 and len(linhas_filtradas) > 0 and linhas_filtradas[-1] != ''):
            linhas_filtradas.append(linha)
    return '\n'.join(linhas_filtradas)

def normalizar_nome(texto: str) -> str:
    """Normaliza nome do arquivo"""
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII')
    texto = re.sub(r'[^\w\s-]', '', texto).strip()
    texto = re.sub(r'[-\s]+', '_', texto)
    return texto[:80]

async def narrar_async(texto: str, voz: str, arquivo_saida: str) -> bool:
    """Narração assíncrona simplificada"""
    try:
        # Limita tamanho do texto por chunk para evitar problemas
        if len(texto) > 5000:
            texto = texto[:5000]
        
        comunicacao = edge_tts.Communicate(
            text=texto,
            voice=voz
        )
        await comunicacao.save(arquivo_saida)
        return os.path.exists(arquivo_saida) and os.path.getsize(arquivo_saida) > 0
    except Exception as e:
        st.error(f"Erro detalhado: {str(e)}")
        return False

def executar_narracao(texto: str, voz: str, arquivo_saida: str) -> bool:
    """Wrapper síncrono para narração"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        resultado = loop.run_until_complete(narrar_async(texto, voz, arquivo_saida))
        loop.close()
        return resultado
    except Exception as e:
        st.error(f"Erro na execução: {str(e)}")
        return False

# --- PROCESSAMENTO DE PDF (OTIMIZADO) ---
@st.cache_data(ttl=3600)
def extrair_pdf(conteudo_bytes: bytes, nome_arquivo: str) -> str:
    """Extrai texto de PDF com cache"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            tmp.write(conteudo_bytes)
            tmp_path = tmp.name
        
        texto_completo = []
        with pdfplumber.open(tmp_path) as pdf:
            # Processa em lotes para não sobrecarregar memória
            total_paginas = len(pdf.pages)
            for i, pagina in enumerate(pdf.pages):
                if i % 50 == 0:  # Log a cada 50 páginas
                    st.write(f"Processando página {i+1} de {total_paginas}...")
                
                texto = pagina.extract_text()
                if texto:
                    texto_completo.append(texto)
                
                # Libera memória periodicamente
                if i % 100 == 0:
                    gc.collect()
        
        os.unlink(tmp_path)
        return '\n'.join(texto_completo)
    except Exception as e:
        st.error(f"Erro ao extrair PDF: {str(e)}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return ""

@st.cache_data(ttl=3600)
def extrair_epub(conteudo_bytes: bytes) -> str:
    """Extrai texto de EPUB com cache"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.epub') as tmp:
            tmp.write(conteudo_bytes)
            tmp_path = tmp.name
        
        texto_completo = []
        book = epub.read_epub(tmp_path)
        
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for script in soup(["script", "style"]):
                    script.decompose()
                texto = soup.get_text()
                if texto.strip():
                    texto_completo.append(texto)
            except:
                continue
        
        os.unlink(tmp_path)
        return '\n'.join(texto_completo)
    except Exception as e:
        st.error(f"Erro ao extrair EPUB: {str(e)}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return ""

def dividir_em_partes(texto: str, tamanho_max: int = 3000) -> List[Dict]:
    """Divide texto em partes menores para processamento"""
    if len(texto) <= tamanho_max:
        return [{"titulo": "Completo", "conteudo": texto}]
    
    # Tenta dividir por parágrafos
    paragrafos = texto.split('\n\n')
    partes = []
    parte_atual = ""
    contador = 1
    
    for paragrafo in paragrafos:
        if len(parte_atual) + len(paragrafo) > tamanho_max and parte_atual:
            partes.append({
                "titulo": f"Parte {contador}",
                "conteudo": parte_atual.strip()
            })
            parte_atual = paragrafo
            contador += 1
        else:
            parte_atual += ('\n\n' if parte_atual else '') + paragrafo
    
    if parte_atual:
        partes.append({
            "titulo": f"Parte {contador}",
            "conteudo": parte_atual.strip()
        })
    
    return partes

# --- INTERFACE PRINCIPAL ---
def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🎧 Narrador.AI Pro</h1>
        <p>Transforme documentos em audiobooks com vozes neurais</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📁 Entrada")
        
        metodo_entrada = st.radio(
            "Escolha o método:",
            ["📄 Upload de Arquivo", "✍️ Texto Manual"],
            key="metodo"
        )
        
        arquivo = None
        texto_manual = ""
        
        if metodo_entrada == "📄 Upload de Arquivo":
            arquivo = st.file_uploader(
                "Selecione o arquivo",
                type=["pdf", "epub", "txt"],
                help="PDF, EPUB ou TXT"
            )
            
            if arquivo:
                st.info(f"📄 Arquivo: {arquivo.name}")
                
                # Mostra tamanho do arquivo
                tamanho_mb = len(arquivo.getvalue()) / (1024*1024)
                st.write(f"Tamanho: {tamanho_mb:.1f} MB")
                
                if tamanho_mb > 50:
                    st.warning("⚠️ Arquivo grande detectado. O processamento pode ser mais lento.")
        else:
            texto_manual = st.text_area(
                "Digite ou cole o texto:",
                height=200,
                placeholder="Seu texto aqui...",
                help="Mínimo de 50 caracteres"
            )
        
        st.markdown("---")
        st.markdown("### 🎤 Voz")
        
        categoria = st.selectbox("Categoria:", list(VOICES.keys()))
        voz_nome = st.selectbox("Voz:", list(VOICES[categoria].keys()))
        
        voz_id = VOICES[categoria][voz_nome]
        
        # Preview da voz
        if st.button("🔊 Testar Voz", use_container_width=True):
            with st.spinner("Testando voz..."):
                texto_teste = "Olá, esta é uma demonstração da voz selecionada."
                arquivo_teste = OUTPUT_DIR / "teste_voz.mp3"
                
                sucesso = executar_narracao(texto_teste, voz_id, str(arquivo_teste))
                
                if sucesso:
                    st.audio(str(arquivo_teste))
                    st.success("✅ Voz funcionando corretamente!")
                else:
                    st.error("❌ Erro ao testar voz. Verifique sua conexão com a internet.")
        
        if st.button("🗑️ Limpar Tudo", use_container_width=True):
            if OUTPUT_DIR.exists():
                shutil.rmtree(OUTPUT_DIR)
            OUTPUT_DIR.mkdir()
            st.cache_data.clear()
            st.rerun()
    
    # Área principal
    st.markdown("### 📚 Processamento")
    
    # Determina se há conteúdo
    tem_conteudo = False
    
    if metodo_entrada == "📄 Upload de Arquivo" and arquivo:
        tem_conteudo = True
    elif metodo_entrada == "✍️ Texto Manual" and len(texto_manual.strip()) > 50:
        tem_conteudo = True
        # Cria arquivo virtual
        arquivo = io.BytesIO(texto_manual.encode('utf-8'))
        arquivo.name = "texto_manual.txt"
    
    if tem_conteudo:
        # Processa o texto (com cache)
        chave_cache = f"{arquivo.name}_{len(arquivo.getvalue())}"
        
        if 'texto_processado' not in st.session_state or st.session_state.get('cache') != chave_cache:
            with st.spinner("📖 Extraindo texto do documento..."):
                try:
                    if arquivo.name.endswith('.pdf'):
                        texto_bruto = extrair_pdf(arquivo.getvalue(), arquivo.name)
                    elif arquivo.name.endswith('.epub'):
                        texto_bruto = extrair_epub(arquivo.getvalue())
                    elif arquivo.name.endswith('.txt') or arquivo.name == "texto_manual.txt":
                        texto_bruto = arquivo.getvalue().decode('utf-8', errors='ignore')
                    else:
                        st.error("Formato não suportado")
                        return
                    
                    # Limpa e prepara
                    texto_limpo = limpar_texto(texto_bruto)
                    
                    if len(texto_limpo) < 50:
                        st.error("❌ Texto muito curto ou não foi possível extrair conteúdo.")
                        return
                    
                    st.session_state.texto_processado = texto_limpo
                    st.session_state.cache = chave_cache
                    st.session_state.partes = None
                    
                except Exception as e:
                    st.error(f"Erro no processamento: {str(e)}")
                    return
        
        texto = st.session_state.texto_processado
        
        # Informações do texto
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📝 Caracteres", f"{len(texto):,}")
        with col2:
            palavras = len(texto.split())
            st.metric("📊 Palavras", f"{palavras:,}")
        with col3:
            tempo_estimado = len(texto) / 1000 * 0.3
            st.metric("⏱️ Tempo Estimado", f"{tempo_estimado:.1f} min")
        
        # Preview do texto
        with st.expander("👁️ Visualizar Texto Extraído"):
            st.text_area(
                "Conteúdo:",
                texto[:5000] + ("..." if len(texto) > 5000 else ""),
                height=200,
                disabled=True
            )
        
        # Divisão em partes
        if st.session_state.partes is None:
            st.session_state.partes = dividir_em_partes(texto)
        
        partes = st.session_state.partes
        
        st.info(f"📑 Documento dividido em {len(partes)} parte(s) para processamento")
        
        # Narração
        if st.button("🎬 Gerar Audiobook", use_container_width=True, type="primary"):
            if len(texto) > 100000:
                st.warning("⚠️ Texto muito longo. O processamento pode levar vários minutos.")
            
            barra_progresso = st.progress(0)
            status = st.empty()
            
            # Limpa diretório de saída
            for arquivo in OUTPUT_DIR.glob("*.mp3"):
                try:
                    arquivo.unlink()
                except:
                    pass
            
            inicio = time.time()
            arquivos_gerados = []
            
            for i, parte in enumerate(partes):
                progresso = (i + 1) / len(partes)
                barra_progresso.progress(progresso)
                
                status.info(f"🎙️ Narrando {parte['titulo']}... ({i+1}/{len(partes)})")
                
                nome_arquivo = f"{i+1:03d}_{normalizar_nome(parte['titulo'])}.mp3"
                caminho_saida = OUTPUT_DIR / nome_arquivo
                
                sucesso = executar_narracao(parte['conteudo'], voz_id, str(caminho_saida))
                
                if sucesso:
                    arquivos_gerados.append(caminho_saida)
                else:
                    st.error(f"❌ Falha ao narrar {parte['titulo']}")
                    break
                
                # Libera memória
                gc.collect()
                
                # Pequena pausa para evitar sobrecarga
                time.sleep(0.5)
            
            barra_progresso.progress(1.0)
            tempo_total = time.time() - inicio
            
            if arquivos_gerados:
                # Sucesso
                status.markdown(f"""
                <div class="success-box">
                <h4>✅ Audiobook Gerado com Sucesso!</h4>
                <p>📁 {len(arquivos_gerados)} arquivos<br>
                ⏱️ Tempo total: {tempo_total/60:.1f} minutos</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Criar ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for arquivo in sorted(arquivos_gerados):
                        zf.write(arquivo, arquivo.name)
                
                # Download
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.download_button(
                        "📥 Baixar Audiobook (ZIP)",
                        zip_buffer.getvalue(),
                        f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        "application/zip",
                        use_container_width=True
                    )
                
                # Preview
                with st.expander("🎵 Ouvir Capítulos"):
                    for arquivo in sorted(arquivos_gerados):
                        st.write(f"📁 {arquivo.name}")
                        st.audio(str(arquivo))
            else:
                status.error("❌ Nenhum arquivo foi gerado. Verifique sua conexão.")
    
    else:
        # Instruções
        st.markdown("""
        <div class="info-box">
        <h4>👋 Bem-vindo ao Narrador.AI Pro!</h4>
        <p>Para começar:</p>
        <ol>
            <li>Escolha o método de entrada (upload ou texto manual)</li>
            <li>Selecione a voz desejada</li>
            <li>Clique em "Testar Voz" para verificar</li>
            <li>Processe e gere seu audiobook</li>
        </ol>
        </div>
        """, unsafe_allow_html=True)
        
        # Cards informativos
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("#### 📄 Formatos")
            st.write("- PDF (até 500 págs)")
            st.write("- EPUB")
            st.write("- TXT")
        
        with col2:
            st.markdown("#### 🎤 Vozes")
            st.write("- 12+ vozes neurais")
            st.write("- 3 idiomas")
            st.write("- Voz Alessio Multilíngue")
        
        with col3:
            st.markdown("#### ⚡ Recursos")
            st.write("- Texto manual")
            st.write("- Preview de voz")
            st.write("- Download em ZIP")

# --- RODAPÉ ---
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: #888;'>Narrador.AI Pro v2.1 | Edge TTS | Streamlit</p>",
    unsafe_allow_html=True
)

if __name__ == "__main__":
    main()
