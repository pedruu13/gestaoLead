# 🕵️‍♂️ Buscador de Leads PRO

Uma ferramenta completa de extração e qualificação de Leads B2B a partir do Google Maps, construída em Python com interface Web (Streamlit) e automação de navegador (Playwright).

O principal objetivo desta ferramenta é identificar negócios locais que **não possuem um site profissional próprio** (ou que usam apenas Linktree/Instagram) para oferecer serviços de Web Design e Desenvolvimento.

---

## ✨ Funcionalidades Premium

* 🌐 **Interface Web Amigável**: Painel completo e fácil de usar construído com Streamlit.
* 🎛️ **Filtros de Qualificação Inteligentes**: Salva apenas leads que atendam aos seus critérios de **Nota Mínima** e **Mínimo de Avaliações** no Google, além de permitir exigir contato via WhatsApp.
* 🤖 **Gerador de Copy (WhatsApp Automático)**: Cria um link direto para o WhatsApp do lead já com um texto de vendas hiper-personalizado (cruzando Nome, Bairro e Elogio sobre a nota no Google).
* 🎨 **Gerador de Prompts (UI/UX)**: Gera automaticamente um *prompt* em inglês pronto para você jogar no Midjourney, DALL-E ou v0.dev e criar um protótipo de site para impressionar o cliente!
* 🕵️ **Caçador Profundo (E-mails e Redes Sociais)**: Entra nas páginas de redes sociais dos leads e extrai **E-mails**, **Instagram**, **Facebook** e **LinkedIn** automaticamente via Regex.
* 📊 **Dashboard em Tempo Real**: Gráficos de barra e placar de métricas ao vivo.
* 📥 **Exportação Nativa**: Baixe os resultados consolidados diretamente em **Excel (.xlsx)** ou CSV.

---

## 🚀 Como Instalar e Rodar

### 1. Faça o Clone do Repositório
```bash
git clone https://github.com/pedruu13/gestaoLead.git
cd gestaoLead
```

### 2. Instale as Dependências
Recomenda-se o uso de um ambiente virtual (venv), mas você pode instalar diretamente rodando:
```bash
python -m pip install -r requirements.txt
```

### 3. Instale os Navegadores do Playwright
O motor de busca precisa do navegador invisível para varrer o Google Maps:
```bash
python -m playwright install chromium
```

### 4. Inicie o Aplicativo
```bash
python -m streamlit run web_leads.py
```
*O seu navegador padrão abrirá automaticamente na página da ferramenta (geralmente `http://localhost:8501`).*

---

## 🛠️ Tecnologias Utilizadas
- **Python 3**
- **Streamlit**: Criação da Interface e Dashboard.
- **Playwright (Sync)**: Automação e Web Scraping seguro.
- **Pandas & OpenPyxl**: Tratamento de dados e exportação para Excel.

---
*Feito com 💡 para facilitar a prospecção ativa de clientes.*
