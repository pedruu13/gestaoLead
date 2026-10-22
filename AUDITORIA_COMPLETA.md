# Auditoria Completa — GestãoLead PRO

**Data da auditoria:** 22/10/2026  
**Escopo:** repositório local, banco SQLite local, aplicação Flask em ambiente temporário, interface desktop/mobile e verificação somente leitura do endereço de produção.  
**Regra aplicada:** nenhuma alteração funcional, exclusão de dados ou mudança em produção foi realizada.

## 1. Resumo executivo

A plataforma já entrega um fluxo útil de ponta a ponta: pesquisa no Google Maps, filtros, classificação, geração revisável de mensagens, CRM, histórico de interações, bloqueio de contato, Studio de Prévias com HTML/CSS responsivo e exportação PNG. Os quatro testes automatizados existentes passaram, inclusive a criação de uma prévia real e seu PNG.

O sistema, porém, ainda tem quatro limites centrais:

1. **Qualificação comercial rasa:** o score usa poucos sinais, não avalia adequação do segmento, qualidade ou idade do site, fonte/confiança de cada contato nem intenção observável.
2. **Escala limitada:** CRM e métricas carregam todos os leads e geram HTML proporcional à base; tarefas longas vivem em threads do próprio servidor.
3. **Segurança de produção incompleta:** aplicação pública em HTTP na porta 5000, sessão sem exigência de cookie seguro, ausência de proteção CSRF completa, segredo com fallback aleatório e credencial Gemini opcionalmente gravada em arquivo.
4. **Gestão comercial incompleta:** não existem campanhas de prospecção, lembretes executáveis, histórico de mudança de etapa, receita, custo por lead ou atribuição de conversão.

**Conclusão:** a base atual é boa para operação individual e volume baixo. Antes de aumentar a coleta, a prioridade deve ser melhorar a precisão do lead, tornar o CRM paginado e seguro, registrar o resultado comercial e só então escalar os robôs.

## 2. Como a auditoria foi feita

### Verificações executadas

- Leitura integral da estrutura, rotas, templates, banco, Docker, configuração, IA, Studio e testes.
- Compilação dos módulos Python: concluída sem erro.
- `pip check`: nenhuma dependência quebrada no ambiente local.
- Testes automatizados: **4 de 4 passaram** em 4,85 segundos.
- Teste de rotas autenticadas com cliente Flask: `/`, `/crm`, `/crm/descartados`, `/estatisticas` e `/configuracoes` retornaram 200.
- Teste controlado de escala com banco temporário: 100, 1.000 e 2.500 leads.
- Navegação automatizada em base temporária: login, mercados, CRM, central de abordagem, detalhe do lead, Studio, métricas e configurações.
- Responsividade verificada em viewport de 390 × 844.
- Consulta somente leitura de produção: `/health` retornou 200; `/` redirecionou para login.
- Auditoria local de dependências com `pip-audit --local`.

### O que não foi executado

- Busca completa no Google Maps, para não gerar carga externa nem coletar novos dados durante a auditoria.
- Chamada real ao Gemini, para não consumir cota nem transmitir dados.
- Login na produção, testes destrutivos, carga contra produção ou alterações no servidor Oracle.
- Inspeção de firewall, proxy, serviço `systemd`, volumes e backups da Oracle, pois esses arquivos/acessos não estão no repositório.

## 3. Arquitetura atual

| Camada | Estado atual | Avaliação |
|---|---|---|
| Aplicação | Flask/Jinja em `app.py` | Funcional, porém monolítica: coleta, banco, autenticação, IA, CRM e APIs no mesmo arquivo. |
| Banco | SQLite local | Adequado ao volume atual; faltam índices, migrações versionadas e estratégia de backup. |
| Coleta | Playwright síncrono + leitura HTML | Funciona por seletores e heurísticas frágeis; sem fila durável ou retomada precisa. |
| IA | Gemini com fallback local | Boa separação entre evidência e inferência; falta observabilidade, avaliação por resultado e idiomas/canais específicos. |
| Frontend | Jinja + Tailwind por CDN + JavaScript inline | Visual consistente, mas dependente de CDNs, com tabelas pesadas e manutenção difícil. |
| Studio | HTML/CSS local + Playwright screenshot | Implementação real e testada; geração síncrona pode bloquear requisições. |
| Produção | Docker/Gunicorn, 1 worker e 4 threads | Coerente com SQLite, mas insuficiente para tarefas longas e sem configuração versionada de HTTPS/deploy. |

## 4. Funcionalidades existentes e estado real

| Funcionalidade | Estado | Evidência/observação |
|---|---|---|
| Login e sessão | Parcial | Login funciona; autenticação é compartilhada e não há limitação de tentativas. |
| Prospecção por nicho e cidade | Funcional com risco | Mercados Brasil/EUA/Europa ficaram alinhados no teste visual; seletores do Google podem quebrar sem aviso estruturado. |
| Excluir leads com site | Funcional por heurística | Verifica o link do perfil; não confirma domínio em outras fontes e não mede se o site está desatualizado. |
| Deduplicação | Parcial | Usa `place_id`; fallback pode usar URL inteira ou valor aleatório quando o identificador não existe. |
| Lead Score | Parcial | Score é calculado e organiza filas, mas não é configurável nem comercialmente completo. |
| Preservar leads menores | Funcional | Leads são classificados em filas, não eliminados pelo score. |
| Pitches por segmento | Funcional | Três versões e uma versão com prévia; regras de qualidade existem. |
| Mensagem para agendamento | Parcial | Perfis de saúde/estética orientam agendamento, mas não há detecção explícita do tipo de canal/receptor. |
| Central de contato | Funcional | Mensagem editável e link de WhatsApp testados; WhatsApp continua externo por limitação do canal. |
| Studio de Prévias | Funcional | HTML responsivo, histórico, desktop/mobile e PNG; teste automatizado passou. |
| CRM/funil | Parcial | Etapas, resposta e próxima ação existem; faltam lembrete ativo, histórico de etapa e visão Kanban. |
| Não contatar | Funcional | Bloqueia ações e preserva histórico. |
| Dashboard | Parcial | Métricas básicas e gráficos existem; não mede resposta, proposta, receita, custo ou coortes. |
| Exportação CSV | Funcional com risco de escala | Exporta toda a tabela em memória. |
| Cancelamento de busca | Parcial | Solicita parada após o lead atual; estado em arquivo não garante retomada ou encerramento robusto. |
| Saúde da aplicação | Funcional | `/health` valida banco e tabelas, sem expor leads. |

## 5. Bugs confirmados

### B1 — Textos corrompidos no fallback de sugestões

- **Evidência:** a lista fallback contém strings como `CirurgiÃ...`, `ClÃ...` e cidades corrompidas em `app.py:1737`.
- **Impacto:** sugestões sem aparência profissional quando a IA falha.
- **Causa provável:** conteúdo salvo com codificação duplicada.
- **Prioridade:** P1.

### B2 — Estado de regeneração pode informar sucesso mesmo com falhas

- **Evidência:** erros individuais apenas são impressos; ao final, a mensagem afirma que todas as copys foram atualizadas em `app.py:1891` e `app.py:1915`.
- **Impacto:** operador acredita que a base foi atualizada integralmente.
- **Prioridade:** P1.

### B3 — Favicon gera 404

- **Evidência:** navegador local registrou `GET /favicon.ico` com 404 após o login.
- **Impacto:** baixo, mas passa sensação de produto inacabado e gera ruído em logs.
- **Prioridade:** P3.

### B4 — Score chamado de 0–100 não alcança 100

- **Evidência:** soma máxima atual é 95: sem site 30, nota 20, avaliações 20, telefone 10, e-mail 10 e rede social 5 em `app.py:279`.
- **Impacto:** escala inconsistente e baixa transparência para configuração futura.
- **Prioridade:** P1.

### B5 — Regra “clientela recorrente” não é sustentada pela evidência

- **Evidência:** 30 avaliações públicas são convertidas diretamente em “clientela recorrente” em `app.py:299`.
- **Impacto:** diagnóstico pode transformar um sinal público em afirmação não comprovada.
- **Prioridade:** P1.

## 6. Inteligência de prospecção

### Pontos fortes

- O filtro de site é aplicado antes de salvar quando ativado.
- Redes sociais e diretórios não são tratados como site próprio.
- O sistema mantém leads de menor score para revisão.
- A deduplicação principal usa o identificador do Google Maps.
- EUA e Europa têm listas próprias e o e-mail é habilitado visualmente no mercado internacional.

### Limites encontrados

- Ausência de site é inferida principalmente pelo link visível no perfil; falta segunda fonte e data da verificação.
- O fallback de link percorre links HTTP genéricos da página e pode capturar um destino que não seja o site oficial.
- Não há avaliação do site existente: responsividade, HTTPS, velocidade, clareza de contato, conteúdo antigo ou erros.
- Score ignora valor potencial do segmento, fit com landing page/site, distância/área real, tipo de contato e qualidade do e-mail.
- E-mail capturado é o primeiro encontrado por regex, sem validação de domínio, papel comercial ou fonte persistida.
- Não existe campanha/pesquisa como entidade; nicho, cidade, filtros, duração e resultados não formam histórico comparável.
- Deduplicação não cobre telefone, domínio, nome+endereço ou filiais relacionadas.
- Cidades são texto livre; não há normalização geográfica nem confirmação de país.
- Não há orçamento de coleta por fonte, backoff central, limite diário ou controle formal de taxa.

## 7. Inteligência comercial e pitches

### Pontos fortes

- `commercial_intelligence.py` separa dados verificados, inferidos e desconhecidos.
- A frase sobre ausência de site é limitada ao perfil consultado.
- A prévia só é mencionada quando uma versão real existe.
- O validador exige nome do lead, menção a site, tamanho mínimo/máximo e bloqueia alguns clichês.
- Existem versões consultiva, direta e personalizada, todas editáveis antes do envio.

### Limites encontrados

- Ainda existe um motor antigo completo em `app.py:330`–`app.py:629`, substituído por alias em `app.py:690`; isso duplica regras e dificulta manutenção.
- O validador mede forma, mas não verifica aderência factual de cada frase contra as evidências.
- As variações são aprovadas mesmo que sejam semanticamente muito parecidas; a comparação atual só detecta igualdade exata.
- Europa recebe mensagem internacional em inglês; não há idioma por país nem formato específico para e-mail.
- WhatsApp, e-mail e recepção/agendamento usam essencialmente a mesma estrutura, sem assunto, assinatura ou CTA próprio do canal.
- Não há registro de qual versão foi enviada, resposta obtida e conversão atribuída; portanto o sistema não aprende quais abordagens funcionam.
- A confiança cresce pela quantidade de itens “verificados”, sem ponderar confiabilidade da fonte.
- Exceções do provedor são parcialmente armazenadas em nota de processamento e algumas rotas retornam erro técnico ao navegador.

## 8. Studio de Prévias

### Confirmado como funcional

- Gera HTML/CSS real, sem scripts ou recursos externos na prévia.
- Layout responsivo e alternância desktop/mobile.
- Salva versões no banco e captura PNG real.
- Usa textos escapados e iframe com sandbox.
- Regenera o pitch depois que a prévia passa a existir.

### Melhorias necessárias

- Screenshot e regeneração de pitch ocorrem dentro da mesma requisição HTTP.
- Não há estado de “processando”, fila, retry ou recuperação após reinício.
- Histórico cresce sem retenção ou paginação.
- Não há duplicação de versão, comparação lado a lado, restauração ou exclusão controlada.
- O template é único; falta biblioteca de estruturas por segmento e objetivo.
- Não existe pacote comercial exportável com capa, diagnóstico e prévia.

## 9. CRM, funil e métricas

### O que existe

- Etapas desde Novo até Fechado/Perdido.
- Registro de resposta, sentimento, próxima ação e prazo.
- Histórico de interações e preferência de não contato.
- Filtros por nome, status, fila e nicho.
- Indicadores básicos de volume, site, WhatsApp e fechamento.

### O que falta

- Histórico imutável de cada mudança de etapa.
- Lembretes reais e fila “vence hoje/atrasado”.
- Responsável pelo lead, notas livres, tags e motivo de perda padronizado.
- Registro de mensagem enviada, canal, versão e horário.
- Proposta, valor estimado, valor fechado e data de fechamento.
- Receita, custo operacional, custo por lead e margem.
- Taxas de resposta, interesse, proposta e conversão por campanha, nicho, cidade e período.
- Detecção de leads parados e tempo médio em cada etapa.
- Kanban e ações em lote seguras.
- Separação entre “Descartado”, “Perdido” e “Não contatar” no relatório executivo.

## 10. Performance e escalabilidade

### Evidência do teste controlado

| Base temporária | `load_leads` | Rota `/crm` | HTML entregue |
|---:|---:|---:|---:|
| 100 leads | 6,63 ms | 13,90 ms | 0,49 MB |
| 1.000 leads | 32,25 ms | 108,64 ms | 4,52 MB |
| 2.500 leads | 63,46 ms | 244,47 ms | 11,23 MB |

Esses tempos são locais e não representam a latência da Oracle. O crescimento do HTML confirma que o navegador, rede e memória serão o gargalo antes da consulta SQLite.

### Gargalos

- `load_leads()` traz todos os registros, processa JSON e score em Python e ordena sem índice de `data_adicao`.
- CRM e estatísticas enviam a base inteira ao template.
- Consulta de prévia usa subconsulta correlacionada por lead.
- Interações e versões não têm índices explícitos por `place_id`/data.
- Exportação monta todo o CSV em memória com pandas.
- Busca e regeneração rodam em threads daemon; reinício perde tarefa e progresso.
- Estado da busca fica em JSON e estado de regeneração fica apenas em memória.
- Migração e atualização de pitches antigos ocorrem durante import/startup em `app.py:85`–`app.py:144`.
- Studio abre Chromium e chama IA dentro da requisição.
- Um único worker limita disponibilidade quando tarefas síncronas são longas.
- Logs são `print`, sem correlação, nível, arquivo estruturado ou retenção.

## 11. UX/UI e acessibilidade

### Resultado visual

- Todas as telas principais abriram em desktop e em 390 × 844 sem overflow global.
- Navegação lateral recolhe no celular.
- Formulários de prospecção estão mais claros que o modelo antigo e mercados mudam os presets corretamente.
- Central de abordagem abriu com mensagem editável e link de WhatsApp válido.

### Problemas

- No celular, a tabela do CRM mantém 920 px e exige rolagem horizontal; ações ficam fora da primeira visão.
- Muitas informações usam 9–10 px, prejudicando leitura e toque.
- Filtros do CRM são apenas no navegador e dependem de toda a base carregada.
- Há uso de `alert()` nativo na busca, enquanto outras telas usam toast/modal próprio.
- Páginas compartilham o mesmo `<title>`, reduzindo orientação em abas e histórico.
- Tailwind por CDN em produção gerou aviso explícito no console em todas as telas auditadas.
- CSS e JavaScript inline dificultam cache, CSP forte, testes e manutenção.
- Ícones dependem de fonte externa; se o CDN falhar, rótulos visuais perdem sentido.
- Não foi identificado link “pular para o conteúdo”; foco de modais não é gerenciado/restaurado.
- O texto visual usa termos agressivos como “caça de leads” e “dispare abordagens”, menos adequados para um produto premium e responsável.

## 12. Segurança e produção

### Riscos altos

1. **HTTPS não confirmado:** produção respondeu em `http://144.22.185.21:5000`; não houve HSTS. Credenciais e sessões não devem trafegar por HTTP.
2. **Cookie sem `Secure`:** `SESSION_COOKIE_SECURE` não é exigido.
3. **Segredo com fallback aleatório:** a aplicação inicia sem `FLASK_SECRET_KEY`, invalidando sessões após reinício e escondendo erro de configuração.
4. **CSRF incompleto:** validação de `Origin` só atua quando o cabeçalho existe; não há token por formulário/requisição.
5. **SSRF:** URLs coletadas são abertas pelo servidor sem bloqueio de IPs privados, loopback, esquemas redirecionados ou resolução DNS segura em `app.py:1294`.
6. **Dependências:** `pip-audit --local` encontrou avisos, incluindo Werkzeug 3.1.8, urllib3 2.7.0, Pillow 12.3.0 e certifi 2026.7.22. Como o ambiente local contém pacotes além do `requirements.txt`, a imagem Docker precisa de auditoria própria; produção informou Werkzeug 3.1.8 no header e deve ser tratada como potencialmente afetada até atualização/validação.

### Riscos médios

- Login sem rate limit, bloqueio temporário ou segundo fator.
- Usuário único compartilhado, sem papéis nem autoria de ações.
- Chave Gemini pode ser gravada em texto simples em `config.json`.
- Algumas respostas devolvem `str(error)` ao navegador.
- Aplicação geral sem CSP; depende de Tailwind, Google Fonts, Font Awesome e Chart.js externos.
- Docker não define usuário não privilegiado.
- Não há `MAX_CONTENT_LENGTH`, limites de JSON ou quotas por operação.
- “Limpar CRM” exclui toda a base e arquivos relacionados sem trilha de auditoria ou backup obrigatório.
- Não há política de retenção, consentimento, origem do dado ou governança de não contato por canal.

### Infraestrutura não comprovada

- Proxy HTTPS, renovação de certificado, firewall e restrição da porta 5000.
- Persistência/volume do SQLite e pasta de PNGs.
- Backups automáticos e teste de restauração.
- Serviço de inicialização, rotação de logs e alertas.
- Pipeline de deploy/rollback; não há workflow versionado no repositório.

## 13. Priorização consolidada

### P0 — Crítico

- Colocar produção atrás de HTTPS e fechar exposição direta da porta da aplicação.
- Corrigir sessão/segredos/CSRF/rate limit e armazenamento de chave.
- Bloquear SSRF no analisador de sites.
- Atualizar e auditar dependências na imagem efetivamente implantada.
- Implantar backup automático e restauração testada antes de evoluir dados/migrações.

### P1 — Alto impacto comercial

- Lead Score v2 configurável e explicável.
- Verificação robusta de site e diagnóstico de site desatualizado.
- Campanhas de prospecção, fontes e deduplicação multissinal.
- Pitches por evidência, canal, idioma e receptor, com aprendizado por resultado.
- Paginação e filtros no servidor.
- Lembretes, leads parados, histórico de etapa e métricas comerciais reais.
- Corrigir bugs de codificação e resultado falso de regeneração.

### P2 — Importante

- Extrair serviços do monólito e introduzir migrações versionadas.
- Fila durável para busca, IA e screenshots.
- Assets compilados localmente, CSP e melhorias de acessibilidade.
- CRM mobile em cards/Kanban e ações em lote.
- Exportação em streaming e observabilidade estruturada.

### P3 — Futuro

- Integração oficial de caixa de entrada por canal, respeitando autorização.
- Biblioteca avançada de prévias e pacote comercial exportável.
- Times, permissões, múltiplos workspaces e cobrança.
- Modelos de priorização calibrados por resultados históricos suficientes.

## 14. Recomendação final

Não aumente primeiro o número de leads coletados. A sequência correta é: **proteger produção → melhorar a verdade dos dados → medir o resultado comercial → acelerar a operação → escalar coleta**. O maior ganho não virá de encontrar mais empresas, mas de reduzir falso “sem site”, priorizar fit real e descobrir quais mensagens e segmentos geram resposta e fechamento.
