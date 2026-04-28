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

def extrair_texto(arquivo):
    if arquivo.name.endswith('.pdf'):
        reader = PdfReader(arquivo)
        return "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
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

async def gerar_zip(texto, voz, t, a, y):
    padrao = r'\n\s*([A-ZÀ-Ú0-9\s]{3,60}|Capítulo\s\d+|CAPÍTULO\s\d+|Sumário|Índice)\s*\n'
    partes = re.split(padrao, texto)
    capitulos = []
    for i in range(0, len(partes), 2):
        tit = partes[i].strip() if i > 0 else "Início"
        cont = partes[i+1].strip() if (i+1) < len(partes) else partes[i].strip()
        if len(cont) > 100: capitulos.append((tit, cont))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        barra = st.progress(0)
        for i, (tit, cont) in enumerate(capitulos, start=1):
            num = f"{i:03d}"
            # Nome temporário do arquivo
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
                caminho_tmp = tmp_mp3.name
            
            communicate = edge_tts.Communicate(f"{tit}. {cont}", VOZES[voz])
            await communicate.save(caminho_tmp)
            
            # Adicionar Metadados
            try:
                audio = ID3(caminho_tmp)
                audio.add(TIT2(encoding=3, text=num))
                audio.add(TPE1(encoding=3, text=a))
                audio.add(TALB(encoding=3, text=t))
                audio.add(TRCK(encoding=3, text=str(i)))
                if y: audio.add(TYER(encoding=3, text=y))
                audio.save()
            except: pass
            
            zip_file.write(caminho_tmp, f"{num}.mp3")
            os.unlink(caminho_tmp)
            barra.progress(i / len(capitulos))
            
    return zip_buffer

st.title("☁️ Audiobook Cloud Lab")
arquivo = st.file_uploader("Livro (PDF/EPUB)", type=['pdf', 'epub'])
voz_sel = st.selectbox("Voz", list(VOZES.keys()))
t = st.text_input("Título")
a = st.text_input("Autor")
y = st.text_input("Ano")

if st.button("🚀 Gerar Audiobook para Download"):
    if arquivo and t and a:
        texto = extrair_texto(arquivo)
        st.info("Convertendo... Aguarde a barra de progresso.")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        zip_data = loop.run_until_complete(gerar_zip(texto, voz_sel, t, a, y))
        
        st.success("Conversão concluída!")
        st.download_button(
            label="⬇️ Baixar Tudo (.zip)",
            data=zip_data.getvalue(),
            file_name=f"{t.replace(' ', '_')}.zip",
            mime="application/zip"
        )
