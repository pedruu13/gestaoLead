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
* 🔎 **Descoberta modular**: Quando configurado, combina Google Places API (New) e OpenStreetMap, usa consultas alternativas, paginação, cache, quotas e retomada de tarefas.
* ✅ **Validação por evidências**: Classifica existência e presença de site como `CONFIRMADO`, `PROVÁVEL` ou `NÃO VERIFICADO`, sem tratar ausência de resultado como prova definitiva.
* 🎯 **Score explicável 0–100**: Organiza os leads em prioridade alta, média ou baixa e mostra os sinais usados; a nota não é probabilidade de compra.
* 📈 **Aprendizado comercial controlado**: Calcula conversão por nicho, cidade e origem usando resultados registrados no CRM, mas só recalibra o score com amostra mínima de 10 contatos.

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

### Deploy automático no Oracle
O workflow `.github/workflows/deploy-oracle.yml` atualiza o servidor a cada push na `main`. Configure estes secrets no GitHub:

- `ORACLE_HOST`: IP ou domínio do servidor.
- `ORACLE_USER`: usuário SSH, normalmente `ubuntu`.
- `ORACLE_SSH_KEY`: chave SSH privada autorizada no servidor.
- `ORACLE_APP_PATH`: opcional; padrão `/home/ubuntu/gestaoLead`.
- `ORACLE_SERVICE`: opcional; padrão `gestaolead`.

### WhatsApp Cloud API
Para enviar dentro do CRM, configure em **Configurações** o token permanente, o Phone Number ID e um template aprovado com uma variável no corpo. A plataforma usa somente a API oficial da Meta e registra o envio no histórico do lead.

### Motor modular de descoberta
- Defina `GOOGLE_PLACES_API_KEY` ou informe a chave em **Configurações**. A chave deve ter acesso à Places API (New).
- Ajuste o limite diário, o número de consultas alternativas e o período de cache antes de buscas grandes.
- O OpenStreetMap complementa apenas nichos com categorias compatíveis; ele não substitui a cobertura do Google Places.
- Sem chave do Google, o coletor legado permanece disponível para preservar o funcionamento atual.
- O painel **Estatísticas** mostra requisições, candidatos, erros, estimativa interna de custo, validação e amostras comerciais.
- A aplicação não contorna CAPTCHA, autenticação, bloqueios ou limites de provedores.
- A cobrança real do Google depende dos campos e SKUs habilitados na conta; o valor exibido pelo sistema é apenas estimativa operacional.

## 🛠️ Tecnologias Utilizadas
- **Python 3**
- **Flask**: Interface Web e APIs.
- **Playwright (Sync)**: Automação e Web Scraping seguro.
- **Pandas & OpenPyxl**: Tratamento de dados e exportação para Excel.

---
*Feito com 💡 para facilitar a prospecção ativa de clientes.*
