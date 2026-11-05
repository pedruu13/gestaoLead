# Auditoria e reconstrução da sugestão de nichos

## Causa raiz encontrada

- O catálogo fixo em `target_intelligence.py` era tratado como universo completo, não como ponto de partida.
- A classificação antiga misturava notas heurísticas de ticket e necessidade com poucos dados observados.
- A contingência pesquisava uma amostra muito pequena por combinação e podia apresentar ausência de link como ausência de site.
- Não existia histórico específico de recomendações, equivalência entre nomes de nichos ou comparação de evidências entre rodadas.
- A interface mostrava sugestões compactas sem tamanho real da amostra, fontes, descartes ou empresas verificadas.

## Arquitetura implementada

1. `niche_research.py` descobre categorias públicas observadas no OpenStreetMap e incorpora nichos já existentes no CRM.
2. `niche_intelligence.py` normaliza nichos equivalentes, monta um conjunto diversificado de candidatos e ranqueia apenas pesquisas com empresas verificadas.
3. Com Google Places configurado, o motor modular usa fila, cache, quotas, consultas alternativas, deduplicação e validação individual existentes no projeto.
4. Sem serviço pago, o coletor atual continua disponível como contingência. Seus resultados sem site ficam como não confirmados, nunca como ausência comprovada.
5. Cada pesquisa persiste métricas, fontes, exemplos e o hash das evidências. Recomendações repetidas sem novas evidências recebem penalização.
6. Conversões do CRM só alteram o ranking a partir de dez resultados comerciais explícitos no mesmo nicho. Antes disso, a interface informa que o potencial é estimado.

## Métricas registradas

- Empresas encontradas e efetivamente verificadas.
- Site próprio, ausência confirmada, ausência provável, site fraco e situação desconhecida.
- Contato comercial, atividade pública e qualificação.
- Duplicidades, descartes, fontes e exemplos da amostra.
- Saturação observada, confiança pelo tamanho da amostra e comparação com a pesquisa anterior.

## Limitações honestas

- Uma meta de 50 não garante 50 verificações: a interface sempre mostra o total realmente alcançado.
- OpenStreetMap depende da cobertura colaborativa da região e serve para descobrir candidatos, não para provar demanda de compra.
- A contingência gratuita não confirma ausência de site somente porque um perfil não exibe link.
- Google Places exige chave, quota disponível e ativação da API. O sistema não contorna CAPTCHA, autenticação ou bloqueios.
- O nível de confiança representa cobertura da amostra, não probabilidade estatística de contratação.
