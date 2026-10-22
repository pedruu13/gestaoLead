# Plano de Melhorias — GestãoLead PRO

Este documento converte a auditoria em itens implementáveis. Complexidade considera uma pessoa trabalhando no projeto atual: **B** baixa, **M** média, **A** alta.

## P0 — Estabilidade e segurança de produção

### SEG-01 — HTTPS, proxy e isolamento da porta 5000

- **Problema identificado:** aplicação acessível diretamente por HTTP.
- **Evidência encontrada:** produção respondeu em `http://144.22.185.21:5000`; HSTS ausente; proxy não está versionado.
- **Impacto esperado:** elimina exposição de credenciais/cookies em trânsito e reduz superfície pública.
- **Solução técnica:** Nginx ou Caddy com TLS automático; liberar publicamente apenas 80/443; aplicação vinculada a loopback/rede privada; redirecionar HTTP para HTTPS.
- **Arquivos envolvidos:** novo `deploy/Caddyfile` ou `deploy/nginx.conf`, serviço/compose e `README.md`.
- **Complexidade:** M.
- **Dependências:** domínio apontado para Oracle, acesso ao firewall e servidor.
- **Critérios de aceitação:** login e APIs somente por HTTPS; HTTP redireciona; porta 5000 não responde externamente; certificado válido; HSTS presente.

### SEG-02 — Sessões, CSRF e proteção do login

- **Problema identificado:** cookie não exige HTTPS, segredo tem fallback, mutações não têm token CSRF e login não limita tentativas.
- **Evidência encontrada:** `app.py:32`–`app.py:35`, `app.py:724`–`app.py:752`.
- **Impacto esperado:** reduz sequestro de sessão, ataques de força bruta e requisições forjadas.
- **Solução técnica:** falhar startup sem segredo em produção; `SESSION_COOKIE_SECURE`; CSRF por token; rate limit por IP/usuário; logout por POST; expiração e rotação documentadas.
- **Arquivos envolvidos:** `app.py`, templates com formulários, `.env.example`, testes.
- **Complexidade:** M.
- **Dependências:** HTTPS concluído.
- **Critérios de aceitação:** mutação sem token retorna 403; cookie contém Secure/HttpOnly/SameSite; segredo ausente impede produção; bloqueio temporário após tentativas repetidas; testes cobrem login/logout.

### SEG-03 — Bloqueio de SSRF na inspeção de sites

- **Problema identificado:** servidor abre URL coletada sem validar destino de rede.
- **Evidência encontrada:** `urllib.request.urlopen` de URL do lead em `app.py:1294`–`app.py:1340`.
- **Impacto esperado:** impede acesso induzido a localhost, metadados cloud e rede interna.
- **Solução técnica:** aceitar somente HTTP/HTTPS; resolver DNS e rejeitar IP privado, loopback, link-local e reservado; validar cada redirecionamento; limitar bytes, tempo e tipo de conteúdo.
- **Arquivos envolvidos:** novo serviço de rede, `app.py`, testes de segurança.
- **Complexidade:** M.
- **Dependências:** nenhuma.
- **Critérios de aceitação:** URLs públicas válidas funcionam; localhost, `169.254.169.254`, IPs privados, esquemas alternativos e redirecionamentos privados são bloqueados e auditados.

### OPS-01 — Backup, restauração e migrações versionadas

- **Problema identificado:** SQLite e PNGs não têm backup/restauração comprovados; schema muda no startup.
- **Evidência encontrada:** `init_db()` executa `ALTER TABLE` e atualização de registros durante import; nenhuma rotina de backup no repositório.
- **Impacto esperado:** evita perda de CRM e torna deploy reversível.
- **Solução técnica:** Alembic ou migrações próprias versionadas; snapshot consistente do SQLite e `generated_previews`; retenção; restauração ensaiada; migração fora do startup web.
- **Arquivos envolvidos:** `migrations/`, scripts de backup, configuração de deploy, `app.py`.
- **Complexidade:** A.
- **Dependências:** acesso ao volume de produção.
- **Critérios de aceitação:** backup automático monitorado; restauração em ambiente limpo documentada e testada; startup não altera schema; rollback definido.

### DEP-01 — Imagem reproduzível e dependências seguras

- **Problema identificado:** auditoria local encontrou vulnerabilidades e uma dependência usa faixa ampla.
- **Evidência encontrada:** alertas em Werkzeug, urllib3, Pillow e certifi; `pandas>=2.2.0,<3.0.0`; produção anuncia Werkzeug 3.1.8.
- **Impacto esperado:** reduz risco conhecido e divergência entre máquina, CI e Oracle.
- **Solução técnica:** lockfile/hashes; atualizar versões corrigidas; auditar dentro da imagem; gerar SBOM; executar container como usuário sem privilégio.
- **Arquivos envolvidos:** `requirements.txt`/lock, `Dockerfile`, workflow de CI.
- **Complexidade:** M.
- **Dependências:** validar compatibilidade com Python/Playwright.
- **Critérios de aceitação:** `pip-audit` da imagem sem vulnerabilidade alta conhecida aceita; build reproduzível; processo não roda como root; testes passam na imagem.

## P1 — Qualidade do lead e conversão

### LEAD-01 — Lead Score v2 explicável e configurável

- **Problema identificado:** score atual é fixo, não alcança 100 e mistura evidência com suposição.
- **Evidência encontrada:** `app.py:279`–`app.py:328`; “clientela recorrente” inferida apenas por avaliações.
- **Impacto esperado:** concentra tempo nos leads com melhor fit sem excluir oportunidades menores.
- **Solução técnica:** dimensões separadas: necessidade digital, fit do segmento, qualidade do contato, atividade/reputação e confiança da evidência; pesos em configuração; score total 0–100; guardar versão e detalhamento.
- **Arquivos envolvidos:** novo módulo de scoring, banco, busca, CRM, configurações e testes.
- **Complexidade:** A.
- **Dependências:** LEAD-02 e taxonomia de segmentos.
- **Critérios de aceitação:** total sempre 0–100; cada ponto é explicado; pesos configuráveis e versionados; nenhum lead é excluído somente pelo score; cenários de teste cobrem pelo menos 15 perfis.

### LEAD-02 — Verificação robusta de presença digital

- **Problema identificado:** “tem site” depende do link do perfil e não identifica site ruim/desatualizado.
- **Evidência encontrada:** `possui_site_proprio()` só classifica URL/domínio; fallback lê links HTTP genéricos.
- **Impacto esperado:** reduz falsos leads e abre oportunidade legítima de redesign para quem já tem site.
- **Solução técnica:** estado `sem_site_confirmado`, `site_identificado`, `site_inacessivel`, `site_com_oportunidade`, `inconclusivo`; segunda fonte; auditoria objetiva de HTTPS, mobile, status, contato, title/description e data de verificação.
- **Arquivos envolvidos:** coletor, banco, inteligência comercial, CRM e testes.
- **Complexidade:** A.
- **Dependências:** SEG-03.
- **Critérios de aceitação:** fonte e data visíveis; casos inconclusivos não viram afirmação absoluta; URL oficial validada; site existente recebe diagnóstico objetivo, não descarte automático.

### LEAD-03 — Campanhas e histórico de prospecção

- **Problema identificado:** não há registro da pesquisa como campanha.
- **Evidência encontrada:** status global em `search_status.json`; leads guardam nicho/bairro, mas não a execução que os encontrou.
- **Impacto esperado:** permite comparar cidades, nichos e filtros e parar pesquisas que só geram leads fracos.
- **Solução técnica:** tabelas `campaigns`, `search_jobs`, `lead_sources`; salvar filtros, mercado, horários, contagens, erros, custo e vínculo de cada lead.
- **Arquivos envolvidos:** banco/migrações, busca, dashboard, CRM.
- **Complexidade:** A.
- **Dependências:** OPS-01.
- **Critérios de aceitação:** toda busca recebe ID; cada lead mostra campanha/fonte; relatório compara rendimento por campanha sem números inventados.

### LEAD-04 — Deduplicação multissinal

- **Problema identificado:** `place_id` não cobre duplicatas entre fontes, filiais e IDs instáveis.
- **Evidência encontrada:** `extrair_id_unico()` pode retornar URL ou número aleatório.
- **Impacto esperado:** reduz abordagem repetida e tempo desperdiçado.
- **Solução técnica:** chave canônica por place ID + telefone normalizado + domínio + nome/endereço; fila de possíveis duplicados; união manual auditável, nunca exclusão silenciosa.
- **Arquivos envolvidos:** coletor, banco, CRM e testes.
- **Complexidade:** M.
- **Dependências:** LEAD-03.
- **Critérios de aceitação:** duplicatas exatas são bloqueadas; suspeitas são agrupadas para revisão; histórico e interações são preservados.

### COPY-01 — Mensagens por evidência, canal, idioma e receptor

- **Problema identificado:** versões ainda compartilham estrutura e o modo internacional é sempre inglês.
- **Evidência encontrada:** `commercial_intelligence.py:130`–`commercial_intelligence.py:153`; mesma saída atende WhatsApp/e-mail/recepção.
- **Impacto esperado:** aumenta relevância e reduz aparência de mensagem automática.
- **Solução técnica:** contrato de mensagem com evidências permitidas, idioma do mercado, canal, tipo de receptor e objetivo; e-mail com assunto; WhatsApp curto; recepção/agendamento com pedido de encaminhamento opcional; similaridade semântica entre variações.
- **Arquivos envolvidos:** `commercial_intelligence.py`, `ai_provider.py`, CRM, configurações e testes.
- **Complexidade:** A.
- **Dependências:** LEAD-02 e taxonomia de segmentos.
- **Critérios de aceitação:** nenhuma afirmação fora das evidências; mensagens diferentes semanticamente; PT-BR, EN e idiomas europeus configuráveis; templates próprios por canal; revisão humana obrigatória.

### COPY-02 — Feedback de resultado e qualidade do pitch

- **Problema identificado:** sistema não sabe qual mensagem foi enviada nem qual converteu.
- **Evidência encontrada:** edição é salva, mas não existe evento de envio/versão escolhida.
- **Impacto esperado:** permite melhorar copy com dados reais, sem promessas de IA.
- **Solução técnica:** evento manual “marcar como enviada”; guardar versão, texto final, canal e horário; relacionar resposta/interesse/proposta/fechamento; dashboard por variante.
- **Arquivos envolvidos:** banco, detalhe do lead, central de contato, métricas.
- **Complexidade:** M.
- **Dependências:** CRM-01.
- **Critérios de aceitação:** cada envio autorizado gera evento; resposta e conversão podem ser atribuídas; nenhuma mensagem é enviada automaticamente.

### CRM-01 — Histórico de etapa, tarefas e leads parados

- **Problema identificado:** próxima ação é apenas um campo; não há agenda ativa ou histórico de mudança.
- **Evidência encontrada:** `next_action`/`next_action_at` existem, mas sem scheduler ou tabela de eventos de estágio.
- **Impacto esperado:** reduz follow-up esquecido e melhora consistência comercial.
- **Solução técnica:** eventos imutáveis, tarefas com estado, visão hoje/atrasadas, motivo de perda e regra de lead parado por etapa.
- **Arquivos envolvidos:** banco, CRM, detalhe, dashboard e job periódico.
- **Complexidade:** A.
- **Dependências:** OPS-01.
- **Critérios de aceitação:** mudança de etapa fica no histórico; tarefas vencidas aparecem em fila; fechamento/perda exige data e motivo; lembrete não envia mensagem sozinho.

### CRM-02 — Paginação, busca e filtros no servidor

- **Problema identificado:** toda a base é carregada, processada e renderizada.
- **Evidência encontrada:** 2.500 leads geraram 11,23 MB de HTML; `load_leads()` não pagina.
- **Impacto esperado:** CRM rápido em celular e servidor estável com bases maiores.
- **Solução técnica:** consulta paginada, filtros SQL, ordenação, contadores agregados e índices por status/data/faixa/nicho/próxima ação.
- **Arquivos envolvidos:** `app.py` ou camada de repositório, banco, `crm.html`, `estatisticas.html`.
- **Complexidade:** A.
- **Dependências:** OPS-01.
- **Critérios de aceitação:** resposta inicial limitada a 25–50 leads; filtros preservados na URL; base sintética de 10 mil leads entrega primeira página abaixo de 1 MB e meta de p95 definida no ambiente alvo.

### MET-01 — Métricas comerciais confiáveis

- **Problema identificado:** dashboard não mede resposta, proposta, receita, custo ou desempenho temporal.
- **Evidência encontrada:** `app.py:1115`–`app.py:1149` calcula contagens globais em memória.
- **Impacto esperado:** mostra quais nichos, cidades e campanhas realmente geram vendas.
- **Solução técnica:** registrar eventos, valores e custos; agregações SQL por período/campanha; funil com denominadores claros; separar volume de taxa.
- **Arquivos envolvidos:** banco, CRM, campanhas, dashboard.
- **Complexidade:** A.
- **Dependências:** LEAD-03, COPY-02 e CRM-01.
- **Critérios de aceitação:** métricas têm definição exibida; filtros por período/nicho/cidade/campanha; receita e custo vêm de campos reais; sem estimativas apresentadas como resultado.

## P2 — Arquitetura, escala e experiência

### ARC-01 — Separar o monólito e remover motor legado

- **Problema identificado:** `app.py` concentra responsabilidades e mantém implementação antiga de pitches.
- **Evidência encontrada:** aproximadamente 1.940 linhas; motor legado em `app.py:330`–`app.py:629`, substituído em `app.py:690`.
- **Impacto esperado:** reduz regressão e facilita testes/evolução.
- **Solução técnica:** blueprints/serviços para auth, leads, jobs, pitches, previews e métricas; repositórios de banco; remover código morto após testes de equivalência.
- **Arquivos envolvidos:** `app.py`, novos pacotes, testes.
- **Complexidade:** A.
- **Dependências:** testes ampliados e OPS-01.
- **Critérios de aceitação:** rotas mantêm contrato; nenhum motor duplicado; módulos com responsabilidade clara; cobertura dos fluxos críticos.

### JOB-01 — Fila durável para busca, IA e screenshots

- **Problema identificado:** threads daemon e estado em arquivo/memória perdem trabalho em reinício.
- **Evidência encontrada:** `app.py:1657`–`app.py:1668` e `app.py:1832`–`app.py:1936`.
- **Impacto esperado:** busca retomável, interface responsiva e concorrência controlada.
- **Solução técnica:** fila durável simples baseada em banco no primeiro estágio ou Redis/RQ/Celery quando necessário; jobs idempotentes; heartbeat, retry, cancelamento e progresso persistido.
- **Arquivos envolvidos:** workers, banco, APIs de status, deploy.
- **Complexidade:** A.
- **Dependências:** OPS-01; Redis se escolhida solução externa.
- **Critérios de aceitação:** reinício não perde job; retry tem limite; cancelamento é persistido; apenas concorrência configurada executa; erro por lead fica consultável.

### UX-01 — CRM mobile e mesa comercial premium

- **Problema identificado:** tabela de 920 px exige rolagem horizontal no celular e esconde ações.
- **Evidência encontrada:** teste em 390 px confirmou tabela interna de 920 px.
- **Impacto esperado:** operação mais rápida em celular e melhor percepção de produto.
- **Solução técnica:** cards no mobile, tabela no desktop, barra de ações fixa, filtros em drawer, destaque para próxima ação e canal; Kanban opcional.
- **Arquivos envolvidos:** `crm.html`, CSS/assets e APIs paginadas.
- **Complexidade:** M.
- **Dependências:** CRM-02.
- **Critérios de aceitação:** contato, etapa e próxima ação aparecem sem rolagem horizontal em 390 px; alvos de toque ≥44 px; teste de teclado e leitor de tela.

### UX-02 — Design system, acessibilidade e assets locais

- **Problema identificado:** Tailwind runtime CDN, scripts inline, texto muito pequeno e comportamento inconsistente de erros.
- **Evidência encontrada:** aviso do Tailwind em todas as telas; `alert()` em `search.html:371` e `search.html:373`.
- **Impacto esperado:** interface mais rápida, consistente, acessível e compatível com CSP.
- **Solução técnica:** build local de CSS/ícones, tokens, componentes de campo/modal/toast/loading/empty state, títulos por página, foco de modal, skip link e contraste/tamanho revisados.
- **Arquivos envolvidos:** templates, `static/`, pipeline frontend.
- **Complexidade:** A.
- **Dependências:** ARC-01 desejável.
- **Critérios de aceitação:** sem CDN runtime; sem warnings de produção; navegação por teclado; foco preso/restaurado em modal; mensagens sem `alert()`; auditoria WCAG básica aprovada.

### OBS-01 — Logs, erros e telemetria operacional

- **Problema identificado:** logs por `print` e erros não correlacionados.
- **Evidência encontrada:** coletor e regeneração imprimem mensagens; alguns erros chegam ao cliente.
- **Impacto esperado:** diagnóstico rápido e operação mais confiável.
- **Solução técnica:** logs JSON com `job_id`/`campaign_id`/`lead_id`, níveis, duração e resultado; página de jobs; captura de exceção sem segredo; métricas de fila e integração.
- **Arquivos envolvidos:** aplicação, workers, deploy.
- **Complexidade:** M.
- **Dependências:** LEAD-03 e JOB-01.
- **Critérios de aceitação:** cada job pode ser rastreado ponta a ponta; segredo não aparece em log; falhas agregadas por causa; alertas para job travado e backup falho.

### EXP-01 — Exportação e históricos escaláveis

- **Problema identificado:** CSV, interações e versões são carregados sem limite.
- **Evidência encontrada:** pandas lê toda a tabela; consultas de histórico não paginam.
- **Impacto esperado:** evita pico de memória e detalhe lento.
- **Solução técnica:** CSV em streaming ou job de exportação; paginação de históricos; retenção configurável de screenshots.
- **Arquivos envolvidos:** exportação, repositórios, templates, storage.
- **Complexidade:** M.
- **Dependências:** JOB-01 opcional.
- **Critérios de aceitação:** exportação grande não duplica toda a base em memória; histórico carrega em páginas; arquivos órfãos são detectados.

## P3 — Evolução de produto

### PREV-01 — Biblioteca de prévias e pacote comercial

- **Problema identificado:** Studio usa uma única estrutura visual e o material de venda fica fragmentado.
- **Evidência encontrada:** um renderer em `preview_studio.py`; histórico simples.
- **Impacto esperado:** demonstrações mais adequadas ao segmento e apresentação comercial mais forte.
- **Solução técnica:** templates locais por objetivo/segmento, duplicar/restaurar versão, comparação desktop/mobile e exportação de pacote com diagnóstico e PNG.
- **Arquivos envolvidos:** `preview_studio.py`, Studio, banco, gerador de documento.
- **Complexidade:** A.
- **Dependências:** JOB-01 e design system.
- **Critérios de aceitação:** pelo menos quatro estruturas distintas; nenhuma imagem/logotipo sem autorização; versão restaurável; pacote claramente marcado como demonstração não oficial.

### CHAN-01 — Integração de canais com autorização

- **Problema identificado:** operador alterna entre plataforma e WhatsApp/e-mail.
- **Evidência encontrada:** central prepara link, mas o envio ocorre fora da plataforma.
- **Impacto esperado:** reduz troca de contexto e melhora registro das conversas.
- **Solução técnica:** primeiro, abertura em nova aba com marcação manual de envio; depois, integração oficial WhatsApp Business/e-mail apenas com consentimento, templates e auditoria. Não tentar embutir WhatsApp Web em iframe.
- **Arquivos envolvidos:** central de contato, integrações, banco, configurações.
- **Complexidade:** A.
- **Dependências:** contas oficiais, políticas do provedor, COPY-02 e SEG-02.
- **Critérios de aceitação:** nenhum envio sem ação explícita; opt-out respeitado; evento registrado; falha de canal não altera etapa indevidamente.

## Ordem recomendada

1. SEG-01, SEG-02, SEG-03, OPS-01 e DEP-01.
2. CRM-02 e LEAD-02.
3. LEAD-01, LEAD-03 e LEAD-04.
4. CRM-01, COPY-01 e COPY-02.
5. MET-01, JOB-01 e OBS-01.
6. UX-01, UX-02, EXP-01 e ARC-01 em fatias seguras.
7. PREV-01 e CHAN-01 após métricas mostrarem necessidade.
