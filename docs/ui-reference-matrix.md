# Matriz de referencias do redesign

Auditoria realizada em 2026-11-06 sobre as rotas Flask e os templates Jinja realmente renderizados.

| Tela | Componente antigo identificado | Referencia exata examinada | Novo componente | Arquivo de destino |
|---|---|---|---|---|
| Estrutura global | `layout.html` com sidebar fixa, topbar sem busca e navegacao duplicada em classes utilitarias | [Linear](https://linear.app/) e [Dashboard Sidebar](https://profitize.com.br/build/componentes/dashboard-sidebar) | `AppShell`, sidebar recolhivel, busca global e atalhos | `templates/layout.html`, `static/css/redesign.css`, `static/js/ui-system.js` |
| Dashboard | Quatro cards grandes, cinco cards de taxa e quatro graficos isolados | [Spell Chart](https://spell.sh/docs/chart), [Progress Metric Card](https://profitize.com.br/build/componentes/progress-metric-card) e [Indicator Chart](https://profitize.com.br/build/componentes/indicator-chart) | Faixa compacta de metricas, progresso e graficos comerciais agrupados | `templates/estatisticas.html`, `static/css/redesign.css` |
| Busca e campanhas | Formulario de 57 KB com opcoes em blocos grandes e configuracoes misturadas | [Spell Label Input](https://spell.sh/docs/label-input), [Spell Rich Button](https://spell.sh/docs/rich-button) e [Spinner](https://spell.sh/docs/spinner) | Etapas compactas, resumo persistente, campos com label e estado real de execucao | `templates/search.html`, `static/css/redesign.css`, `static/js/ui-system.js` |
| CRM | Template de 73 KB com filtros ocupando a primeira dobra e tabela sem identidade visual por empresa | [Linear](https://linear.app/) e [Fallback Avatar](https://spell.sh/docs/fallback-avatar) | Barra de comando, filtros progressivos, tabela densa, avatar e painel lateral | `templates/crm.html`, `templates/_components.html`, `static/css/redesign.css` |
| Mensagens | Diagnostico e score antes das mensagens; editor aparece abaixo da primeira dobra | [Spell Copy Button](https://spell.sh/docs/copy-button) | Estudio de mensagens prioritario, diagnostico lateral, tres versoes e copia com confirmacao | `templates/lead_detail.html`, `templates/_components.html`, `static/css/redesign.css` |
| Configuracoes | Formularios longos com controles nativos inconsistentes | [Uiverse dark input](https://uiverse.io/danilppzz/tender-chicken-82), [Uiverse switch](https://uiverse.io/cuzpq/gentle-goat-72), [Uiverse checkbox](https://uiverse.io/andrew-manzyk/ancient-turtle-91) e [Uiverse tooltip](https://uiverse.io/mahiatlinux/honest-emu-97) | Inputs, switches, checkboxes e ajuda contextual unificados | `templates/configuracoes.html`, `static/css/design-system.css` |
| Feedback assincrono | Spinner e textos de carregamento diferentes por tela | [Spell Spinner](https://spell.sh/docs/spinner) e [Uiverse loader](https://uiverse.io/Shoh2008/clever-goose-73) | `LoadingState` unico, discreto e com movimento reduzido | `static/css/design-system.css`, `static/js/ui-system.js` |
| Navegacao rapida | Atalho visual sem comportamento global | [Spell Keyboard Shortcuts](https://spell.sh/docs/keyboard-shortcuts) e [Uiverse search shortcut](https://uiverse.io/mustafa7799/new-dolphin-33) | Paleta de comandos com `Ctrl/Cmd + K` e atalhos de navegacao | `templates/layout.html`, `static/js/ui-system.js` |

## Licencas e adaptacao

- Os componentes Spell UI examinados sao React/shadcn; apenas seus comportamentos e hierarquia foram adaptados para Jinja, CSS e JavaScript nativos.
- Os elementos individuais selecionados do Uiverse declaram licenca MIT nas paginas citadas. A implementacao usa controles proprios adaptados ao design system, sem copiar componentes pagos.
- Os itens Dashboard Sidebar, Progress Metric Card e Indicator Chart aparecem como gratuitos no catalogo Profitize consultado. Foram usados como referencia de organizacao, sem copiar marca, texto ou codigo proprietario.
