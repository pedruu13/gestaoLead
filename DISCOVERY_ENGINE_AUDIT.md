# Auditoria e arquitetura do motor de descoberta

## Diagnóstico da versão anterior

1. **Fonte única**: a descoberta dependia do Google Maps operado por Playwright. Uma lentidão, mudança visual ou bloqueio afetava toda a campanha.
2. **Ausência de site superestimada**: não encontrar um link no resultado era usado como sinal forte demais. Isso gerava falsos positivos.
3. **Processamento sem retomada durável**: o progresso existia em arquivo, mas não havia checkpoint por fonte, consulta e página no banco.
4. **Deduplicação parcial**: o histórico evitava alguns `place_id` repetidos, porém não conciliava de forma consistente domínio, telefone, e-mail e nome/local entre fontes.
5. **Pontuação com pouca rastreabilidade**: a nota não considerava confiança da validação, quantidade de fontes ou resultados comerciais com amostra mínima.
6. **Aprendizado comercial implícito**: etapas genéricas do funil eram interpretadas como resposta ou interesse, o que podia inventar sinais de conversão.
7. **Observabilidade incompleta**: não existia visão por fonte de requisições, erros, candidatos e custo estimado.

## Arquitetura implementada

### Descoberta

- `discovery_sources.py`: contrato de fontes, Google Places API (New), OpenStreetMap/Nominatim/Overpass e expansão de consultas por segmento.
- `discovery_engine.py`: fila SQLite, checkpoint, cache com validade, paginação, duas tentativas por fonte, continuidade após falha, quotas e contagem de uso.
- O coletor Playwright anterior permanece como fallback quando a Places API não está configurada.

### Validação

- `lead_validation.py` verifica sinais de existência, atividade, contato e site.
- URLs são limitadas a destinos públicos HTTP/HTTPS para reduzir risco de SSRF.
- Site encontrado é testado quanto a resposta e sinais de pertencimento ao negócio.
- Site não retornado por uma única fonte fica como `NÃO VERIFICADO`; duas fontes sem site elevam apenas para `PROVÁVEL`.
- Redes sociais e diretórios não são tratados como site próprio.

### Deduplicação

- Candidatos são conciliados por domínio, telefone, e-mail ou combinação normalizada de nome e localização.
- Registros da base atual também são comparados pelos mesmos identificadores antes da gravação.
- O identificador original da fonte e as evidências permanecem armazenados para auditoria.

### Qualificação

- `lead_scoring.py` usa cinco dimensões configuráveis que somam 100 pontos.
- O score incorpora necessidade digital, adequação ao serviço, contato, atividade pública e qualidade das evidências.
- A saída inclui justificativa, prioridade e aviso explícito de que não representa probabilidade estatística de compra.

### Aprendizado

- `conversion_intelligence.py` utiliza somente resultados comerciais explícitos.
- Conversão é agrupada por nicho, local e origem.
- Ajustes nas recomendações exigem no mínimo 10 contatos no grupo.
- Grupos menores continuam visíveis como amostra insuficiente, sem alterar o score.

### Interface e operação

- CRM: filtros por score mínimo, origem e status de validação.
- Lead: evidências, justificativa, confiança do site e resultado comercial detalhado.
- Estatísticas: uso por fonte, erros, custo estimado, tarefas, validações e conversão.
- Configurações: chave Google Places, ativação das fontes, consultas alternativas, quotas e cache.
- Retomada: `POST /api/discovery/jobs/<job_id>/resume` continua tarefas pendentes ou interrompidas.

## Migrações compatíveis

As tabelas e colunas são criadas por `init_db()` sem apagar a base atual:

- Colunas de origem, validação, evidência, resultado comercial e última verificação em `leads`.
- `lead_evidence` para evidências estruturadas.
- `discovery_jobs`, `discovery_candidates`, `discovery_cache` e `source_usage` para execução durável.

## Limitações conhecidas

- Google Places exige chave, faturamento e quota configurados pelo operador.
- A estimativa de custo é operacional; a fatura do provedor é a referência real.
- OpenStreetMap não possui cobertura uniforme nem classificação para todos os nichos.
- E-mail público raramente está presente nas fontes de descoberta e pode exigir enriquecimento posterior permitido.
- Confirmação absoluta de ausência de site não é tecnicamente garantida; por isso o sistema preserva níveis de confiança.
- A verificação de pertencimento de domínio é heurística e mantém casos ambíguos para revisão humana.
- SQLite atende a implantação atual com um processo; alto volume concorrente exigirá fila externa e banco servidor.
