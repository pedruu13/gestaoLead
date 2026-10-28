# GestãoLead PRO

Plataforma de inteligência comercial para encontrar, qualificar e acompanhar empresas que podem se beneficiar de um site profissional.

O principal objetivo desta ferramenta é identificar negócios locais que **não possuem um site profissional próprio** (ou que usam apenas Linktree/Instagram) para oferecer serviços de Web Design e Desenvolvimento.

---

## ✨ Funcionalidades Premium

* 🌐 **Interface Web Amigável**: Painel completo e fácil de usar construído com Flask.
* 🎛️ **Filtros de Qualificação Inteligentes**: Prioriza empresas sem site próprio, com filtros de nota, WhatsApp, região e grandes redes.
* 🕵️ **Investigação de mercados**: Testa nichos e cidades no Google Maps, mede presença de site e atividade local, guarda o histórico e explora combinações diferentes em cada rodada.
* 🤖 **Inteligência comercial baseada em evidências**: Separa dados verificados, inferências e informações desconhecidas antes de gerar uma abordagem.
* ✍️ **Pitches revisáveis**: Gera versões consultiva, direta e personalizada. A versão com prévia só é liberada quando existe uma demonstração real.
* 🎨 **Studio de Prévias**: Cria homepage HTML/CSS responsiva, visualização desktop/mobile, histórico de versões e exportação PNG.
* 📋 **Acompanhamento comercial**: Registra respostas, sentimento, próxima ação, prazo e histórico do lead.
* 🛡️ **Preferência de não contato**: Bloqueia ações de abordagem sem apagar o histórico comercial.
* 🕵️ **Caçador Profundo (E-mails e Redes Sociais)**: Entra nas páginas de redes sociais dos leads e extrai **E-mails**, **Instagram**, **Facebook** e **LinkedIn** automaticamente via Regex.
* 📊 **Dashboard em Tempo Real**: Placar de métricas durante a busca, CRM e funil comercial completo.
* 📥 **Exportação Nativa**: Baixe os resultados consolidados em CSV.

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
py app.py
```
*Após iniciar o servidor, abra o seu navegador e acesse `http://localhost:5000`.*

---

## 🔐 Configuração de produção
- Copie `.env.example` para `.env` e defina `APP_USER`, `APP_PASS` e uma `FLASK_SECRET_KEY` forte.
- Em produção, configure `GEMINI_API_KEY` como variável de ambiente e publique o app atrás de um proxy HTTPS (Nginx ou Caddy).
- Depois de ativar HTTPS no proxy, use `SESSION_COOKIE_SECURE=true` e `TRUST_PROXY_HEADERS=true`. Não ative o cookie seguro enquanto o acesso ainda estiver apenas em HTTP, pois o login não será mantido.
- O Docker executa Gunicorn com um único worker, pois a busca usa SQLite e um processo de navegador.
- O servidor cria diariamente um backup compactado em `backups/` e mantém os 14 mais recentes. Copie essa pasta para outro servidor ou armazenamento para proteção contra perda da máquina Oracle.
- O endpoint `GET /health` permite verificar banco, Studio de Prévias e acompanhamento comercial sem expor dados de leads.

## 🛠️ Tecnologias Utilizadas
- **Python 3**
- **Flask**: Interface Web e APIs.
- **Playwright (Sync)**: Automação e Web Scraping seguro.
- **Pandas & OpenPyxl**: Tratamento de dados e exportação para Excel.

---
*Feito com 💡 para facilitar a prospecção ativa de clientes.*
