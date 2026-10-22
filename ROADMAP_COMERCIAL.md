# Roadmap Comercial — GestãoLead PRO

## Objetivo

Transformar a plataforma de um coletor/CRM individual em uma ferramenta de inteligência comercial que prioriza qualidade, registra evidências, ajuda a executar follow-ups e mede fechamento real.

## Ordem comercial aprovada

| Prioridade | Melhoria | Objetivo |
|---:|---|---|
| 1 | Qualificação inteligente de leads | Encontrar empresas com oportunidades reais. |
| 2 | Pitches comerciais personalizados | Melhorar a taxa de resposta. |
| 3 | Prévia automática de sites | Mostrar valor antes da negociação. |
| 4 | CRM com follow-ups | Evitar perder contatos interessados. |
| 5 | Dashboard de conversão | Descobrir quais nichos e cidades funcionam melhor. |

As correções P0 de segurança, backup e produção continuam como trava técnica antes de qualquer publicação, sem alterar essa ordem de valor comercial.

O roadmap usa **gates de resultado**, não datas rígidas. Uma fase só avança quando os critérios de saída forem comprovados.

## Princípios

1. Mais leads não significa mais vendas; qualidade e capacidade de acompanhamento vêm primeiro.
2. Score organiza a fila, nunca garante compra e nunca apaga automaticamente leads menores.
3. Toda mensagem usa fatos verificáveis e exige revisão humana.
4. Nenhuma abordagem é enviada automaticamente sem autorização explícita.
5. Métricas só usam eventos e valores reais.
6. Segurança, backup e reversibilidade precedem migrações e escala.

## Fase 0 — Base segura e recuperável

**Prioridade:** P0  
**Itens:** SEG-01, SEG-02, SEG-03, OPS-01, DEP-01.

### Entregas

- HTTPS, proxy e porta interna protegida.
- Sessão/CSRF/login endurecidos.
- Navegação externa do coletor protegida contra SSRF.
- Backup automático e restauração testada.
- Migrações versionadas e imagem auditada/reproduzível.

### Gate de saída

- Restauração completa comprovada em ambiente limpo.
- Produção não aceita autenticação por HTTP.
- Testes de segurança essenciais automatizados.
- Dependências da imagem sem vulnerabilidade alta conhecida não aceita.

## Fase 1 — Verdade do lead

**Prioridade:** P1  
**Itens:** LEAD-02, LEAD-03, LEAD-04 e correções B1/B4/B5.

### Entregas

- Estado confiável de presença digital, inclusive “inconclusivo”.
- Diagnóstico mínimo de site existente.
- Campanhas e fontes persistidas.
- Deduplicação por place ID, telefone, domínio e identidade comercial.
- Correção dos textos corrompidos e linguagem de evidência.

### Métricas a iniciar

- Leads encontrados por campanha.
- Percentual com site confirmado, sem site confirmado, site com oportunidade e inconclusivo.
- Duplicatas exatas/suspeitas.
- Contatos válidos por canal.
- Tempo e erros por lead coletado.

### Gate de saída

- Amostra manual define precisão mínima aceita para classificação de site.
- Todo lead novo mostra fonte e data de verificação.
- Nenhuma ausência de site é apresentada como absoluta sem evidência suficiente.

## Fase 2 — Priorização comercial

**Prioridade:** P1  
**Itens:** LEAD-01 e CRM-02.

### Entregas

- Lead Score v2 com pesos configuráveis e versão registrada.
- Explicação por dimensão e nível de confiança.
- Filas Prioridade, Secundária e Exploração sem exclusão automática.
- CRM paginado com filtros no servidor e índices.

### Score proposto

| Dimensão | Peso inicial | Exemplos de evidência |
|---|---:|---|
| Necessidade digital | 0–30 | sem site confirmado; site inacessível; problemas objetivos do site atual |
| Adequação ao serviço | 0–25 | segmento e objetivo compatíveis com site/landing page |
| Capacidade de contato | 0–20 | canal comercial válido, fonte e confiança |
| Sinais de atividade | 0–15 | perfil atualizado, avaliações recentes/volume sem extrapolar recorrência |
| Qualidade da evidência | 0–10 | dados confirmados em fonte primária e data recente |

Os pesos são ponto de partida e devem ser calibrados com resposta e fechamento reais. O score não é probabilidade de compra.

### Gate de saída

- Casos de referência aprovados manualmente.
- Primeira tela do CRM permanece leve com 10 mil leads sintéticos.
- Operador entende por que um lead está em cada fila.

## Fase 3 — Abordagem que aprende

**Prioridade:** P1  
**Itens:** COPY-01, COPY-02 e correção B2.

### Entregas

- Mensagens por canal, idioma, segmento, evidência e receptor.
- Assunto e corpo próprios para e-mail; versão curta para WhatsApp.
- Tratamento específico quando o número parece ser de recepção/agendamento.
- Registro manual do texto realmente enviado.
- Resultado da regeneração com contagem de sucesso, fallback e erro.

### Experimento comercial responsável

- Comparar no máximo duas variações por contexto semelhante.
- Não misturar segmentos/países no mesmo resultado.
- Medir resposta, interesse, proposta e fechamento; não apenas abertura de link.
- Revisar mensagens com taxa de bloqueio/recusa alta.

### Gate de saída

- Toda mensagem cita apenas fatos autorizados pelo contrato de evidências.
- Variações passam verificação de similaridade e revisão amostral.
- Dashboard atribui resposta e avanço à versão registrada.

## Fase 4 — Cadência e fechamento

**Prioridade:** P1  
**Itens:** CRM-01 e MET-01.

### Entregas

- Linha do tempo de etapa e contato.
- Tarefas hoje, próximas e atrasadas.
- Motivos padronizados de perda e não contato.
- Proposta, valor estimado, valor fechado e receita.
- Funil por período, segmento, cidade e campanha.

### Definições mínimas das métricas

- **Taxa de resposta:** leads com resposta ÷ leads marcados como contatados.
- **Taxa de interesse:** leads interessados ÷ leads com resposta.
- **Taxa de proposta:** propostas enviadas ÷ leads interessados.
- **Taxa de fechamento:** clientes fechados ÷ leads contatados, com período explícito.
- **Custo por lead:** custo operacional real da campanha ÷ leads únicos válidos.
- **Receita:** soma de valores fechados, nunca projeção misturada com realizado.

### Gate de saída

- Nenhum lead vencido fica invisível.
- Mudanças de etapa são auditáveis.
- Métricas exibem definição, período e denominador.

## Fase 5 — Escala operacional

**Prioridade:** P2  
**Itens:** JOB-01, OBS-01, EXP-01 e ARC-01.

### Entregas

- Jobs persistentes de busca, IA, screenshot e exportação.
- Retry, cancelamento e retomada após reinício.
- Logs estruturados e painel de falhas.
- Exportação em streaming.
- Separação gradual do monólito por fatias verticais.

### Gate de saída

- Reinício controlado durante job não perde estado.
- Falha de um lead não encerra a campanha.
- Operador identifica causa e alcance de cada erro.
- Teste de carga controlado atende metas definidas para o servidor Oracle.

## Fase 6 — Produto premium

**Prioridade:** P2/P3  
**Itens:** UX-01, UX-02, PREV-01 e CHAN-01.

### Entregas

- CRM mobile em cards e mesa comercial mais objetiva.
- Assets locais, design system e acessibilidade.
- Biblioteca de prévias por segmento/objetivo.
- Pacote comercial exportável.
- Integração oficial de canais, se o volume justificar custo e governança.

### Gate de saída

- Fluxo principal executável em celular sem rolagem horizontal.
- Nenhum asset crítico depende de CDN runtime.
- Prévia continua não oficial e não usa material de terceiros sem autorização.
- Integração nunca envia sem ação explícita e respeita “não contatar”.

## Backlog priorizado

| Ordem | Entrega | Prioridade | Resultado comercial esperado |
|---:|---|---|---|
| 1 | Segurança, HTTPS e backup | P0 | Protege acesso, dados e continuidade da operação. |
| 2 | Verificação de site + diagnóstico | P1 | Remove falsos “sem site” e recupera oportunidades de redesign. |
| 3 | Score v2 + CRM paginado | P1 | Direciona esforço aos melhores leads sem perder o restante. |
| 4 | Campanhas + deduplicação | P1 | Revela quais pesquisas geram contatos úteis e evita repetição. |
| 5 | Pitch por canal/idioma/evidência | P1 | Aumenta relevância da primeira abordagem. |
| 6 | Registro de envio e resultado | P1 | Cria aprendizado real sobre mensagem e segmento. |
| 7 | Tarefas, atrasos e histórico | P1 | Reduz oportunidades esquecidas. |
| 8 | Métricas de funil, receita e custo | P1 | Permite decidir onde investir tempo e dinheiro. |
| 9 | Fila durável e observabilidade | P2 | Aumenta volume sem tornar o sistema instável. |
| 10 | CRM mobile e design system | P2 | Melhora velocidade de uso e percepção premium. |
| 11 | Studio avançado | P3 | Fortalece demonstrações para leads realmente qualificados. |
| 12 | Integrações oficiais de canal | P3 | Reduz troca de contexto quando houver escala suficiente. |

## As cinco melhorias com maior chance de aumentar fechamentos

1. **Confirmar presença e qualidade do site com evidência.** Evita perder tempo com lead inadequado e cria argumentos legítimos para redesign.
2. **Lead Score v2 focado em necessidade, fit e contato.** Prioriza quem tem problema solucionável e canal comercial acessível.
3. **Mensagens por segmento, canal, idioma e receptor.** Faz a abordagem parecer diagnóstico útil, não oferta genérica.
4. **Registrar envio, resposta e conversão por versão.** Permite aprender com resultados reais e parar de escolher copy por opinião.
5. **Fila de próximas ações e leads parados.** Garante que interesse e proposta recebam follow-up no momento certo.

## Próxima decisão recomendada

Iniciar pela **Fase 0** e, em paralelo de planejamento, detalhar os contratos de dados de **campanha**, **evidência**, **score** e **evento comercial**. Não começar uma reestruturação ampla do frontend ou trocar SQLite antes de medir o volume e estabilizar esses contratos.
