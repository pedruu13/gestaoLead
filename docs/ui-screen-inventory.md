# Inventario das telas renderizadas

Auditoria visual de 2026-11-07. O projeto usa Flask, Jinja2, CSS e JavaScript nativos. Nao existe bundle ou etapa de build frontend.

| Rota | Template real | Secoes e controles preservados |
|---|---|---|
| `/login` | `templates/login.html` | Usuario, senha, mostrar senha, validacao e feedback de acesso |
| `/` | `templates/search.html` | Formulario de campanha, modo geografico, estados, cidades, nichos, meta, configuracoes avancadas, botao `btn_start_campaign`, sugestao de alvos, progresso e resultados |
| `/crm` | `templates/crm.html` | Busca `filter_nome`, score minimo, qualidade, validacao, origem, oportunidade de site, follow-up, potencial, nicho, auditoria, regeneracao de copys, limpeza, exportacao CSV, tabela, funil e paginacao |
| `/crm/contatados` | `templates/crm.html` | Mesma tabela e filtros, limitados a contatos em andamento |
| `/crm/descartados` | `templates/crm.html` | Mesma tabela e filtros, limitados aos descartados |
| `/leads/<place_id>` | `templates/lead_detail.html` | Diagnostico, evidencias, score, canais, mensagens, copia, edicao, WhatsApp/e-mail, follow-up e historico |
| `/leads/<place_id>/studio` | `templates/studio.html` | Configuracao e geracao de previa visual |
| `/estatisticas` | `templates/estatisticas.html` | Metricas reais, historico de campanhas, uso de fontes, validacao, conversao, graficos Chart.js e exportacao CSV |
| `/configuracoes` | `templates/configuracoes.html` | Credenciais e configuracoes existentes, switches, campos e teste de integracao |

## Arquivos compartilhados auditados

| Arquivo | Funcao |
|---|---|
| `templates/layout.html` | App shell, sidebar, cabecalho, busca global, navegacao e carregamento dos assets |
| `templates/_components.html` | Macros reutilizaveis de avatar, copia e metrica |
| `templates/_icons.html` | Macros SVG locais usados na navegacao |

## Pontos de integracao que nao podem mudar

- IDs e nomes de campos do formulario de busca e dos filtros do CRM.
- URLs e metodos das rotas existentes.
- Funcoes JavaScript de busca, campanha, filtros, exportacao, status e mensagens.
- Estrutura do banco, scraping Playwright e regras de qualificacao.
- `Dockerfile`, `requirements.txt` e ausencia de build Node.
