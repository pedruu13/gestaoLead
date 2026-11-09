# Busca, mensagens e propostas — 9 de novembro de 2026

## Constatações locais

- Gemini e Google Places estavam sem chaves configuradas no ambiente carregado pela aplicação. Isso não verifica a configuração da Oracle.
- A busca Google Maps aguardava um segundo e lia apenas os cartões inicialmente carregados. Falhas de navegador eram devolvidas como resultados vazios.
- O cache podia preservar uma busca vazia por sete dias.
- O validador de mensagens exigia referências à ausência de site. Isso favorecia textos repetitivos e afirmações sem evidência.
- As propostas são renderizadas a partir de modelos HTML/CSS locais, não por um modelo de geração de imagens. Sem material autorizado, utilizam composição gráfica.
- Textos de direção de arte apareciam na página destinada ao cliente. A captura mostrou corte na composição arredondada e baixo contraste em botões claros.

## Correções

- Espera por resultados e rolagem limitada a oito etapas; erros de fonte explícitos; nome acessível do cartão e tratamento de fechamento permanente.
- Resultados vazios/parciais não entram no cache; versão da consulta evita reutilizar extrações antigas. Trabalho com erros e nenhum candidato termina como falha.
- Origem e modelo das novas mensagens são persistidos e apresentados; configuração da IA fica visível na busca.
- Removida a exigência de alegar ausência de site. Contexto registrado e URL passam para a geração. Mensagem de prévia mais curta.
- Conteúdo de visitante por segmento, composição de serviços quando não há fotografia, contraste dinâmico dos botões e correção do corte.
- Inputs de busca com tamanho legível e área de toque adequada no celular.

## Evidências

- 112 testes automatizados aprovados.
- Consulta real Google Maps: Dentista, Campinas/SP, limite de cinco empresas; cinco retornadas, uma consulta, sem avisos. As três primeiras tinham URL de site. Não foram apresentadas como leads qualificados nem inseridas no CRM por esse teste.
- `py tests/render_preview_examples.py`: três empresas fictícias explicitamente de teste; odontologia, advocacia e academia; desktop, mobile e compartilhamento. Relatórios e imagens em `artifacts/preview-quality/`.
- Inspeção visual das capturas de odontologia e academia; correções de texto, corte e contraste após a primeira captura.

## Limites

- Não houve geração Gemini ao vivo porque não existe chave local configurada. Configuração de chave não equivale a chamada validada.
- Sem fotografia/logo autorizado, o sistema não representa a identidade real da empresa. A interface passa a informar isso.
- As composições ainda são modelos locais; não há pesquisa criativa individual automática ou geração de fotos nesta alteração.
- Validação automática de renderização não mede qualidade artística ou probabilidade de venda.
- Não foi feita auditoria visual completa de todas as interações da busca em todas as resoluções neste ciclo.
- Não houve publicação na Oracle.
