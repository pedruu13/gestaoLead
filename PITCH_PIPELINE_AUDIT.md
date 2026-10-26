# Auditoria do pipeline de pitches

## Causa raiz confirmada

1. A mensagem ruim era produzida literalmente pelo fallback fixo de `commercial_intelligence.py`.
2. No ambiente local, nenhuma chave Gemini está configurada. Por isso, o fallback era o caminho efetivo para todas as mensagens.
3. O fallback inseria nome completo, categoria bruta do Google e frases técnicas diretamente no texto comercial.
4. O validador anterior aprovava a mensagem ruim com nota 100 porque verificava apenas tamanho, menção a site e presença do nome.
5. O prompt recebia o objeto técnico inteiro, incluindo evidências escritas como relatório, e não havia uma etapa própria de planejamento comercial.
6. Quando a IA era usada, a primeira opção era o modelo `flash-lite`; uma resposta reprovada não recebia os motivos da reprovação na tentativa seguinte.
7. Os pitches antigos já salvos não eram regenerados porque a migração só reconhecia uma versão legada mais antiga.
8. A primeira correção ficou segura, porém comercialmente fraca: não apresentava o vendedor, não formulava a necessidade do site e terminava com pedidos vagos como “três ideias práticas”.

## Pipeline implementado

1. **Normalização:** transforma categoria bruta, nome, localização, canais e situação do site em contexto comercial seguro.
2. **Planejamento:** escolhe público, dúvida anterior ao contato, impacto comercial, escopo do site e valor específico por segmento.
3. **Geração:** apresenta o vendedor ou agência, registra a evidência segura, explica a necessidade e oferece explicitamente a criação do site.
4. **Revisão:** rejeita texto sem apresentação comercial, sem proposta explícita, sem justificativa do site, com linguagem fraca, erro gramatical, promessa, repetição ou encerramento genérico.
5. **Recuperação:** a segunda tentativa da IA recebe os motivos exatos da reprovação; se continuar ruim, entra o fallback contextual já validado.

## Antes e depois — caso real

Os exemplos abaixo usam “Pedro” e “Norte Digital” apenas para demonstrar os campos de vendedor e agência configuráveis na plataforma.

### Antes

> Oi, equipe da Dra. Rosiene Silva de Brito. Quem compara opções de Dentista costuma precisar entender o serviço e o próximo passo antes de entrar em contato. No perfil público consultado, não identifiquei um site próprio no perfil do Google consultado. A oportunidade mais clara é organizar tratamentos, orientações iniciais e o caminho para agendamento. Um site objetivo pode organizar essas respostas e levar a pessoa interessada ao canal que vocês já usam. Posso compartilhar a estrutura que recomendaria para avaliação?

### Depois

> Olá, tudo bem? Sou Pedro, da Norte Digital, e desenvolvo sites para empresas. Ao pesquisar a presença digital da clínica, não encontrei um site próprio vinculado ao perfil do Google. Sem uma página própria, o potencial cliente pode chegar ao WhatsApp ainda com dúvidas sobre tratamentos, primeira consulta e agendamento. Minha proposta é desenvolver um site profissional para explicar essas etapas com clareza e conduzir o paciente ao agendamento sem transformar o WhatsApp em um balcão de dúvidas. Posso encaminhar um escopo inicial para vocês avaliarem?

### Outros exemplos gerados pelo sistema

**Estética**

> Olá, tudo bem? Sou Pedro, da Norte Digital, e desenvolvo sites para empresas. Ao pesquisar a presença digital da clínica, não encontrei um site próprio vinculado ao perfil do Google. Sem uma página própria, o potencial cliente pode chegar ao WhatsApp ainda com dúvidas sobre procedimentos, cuidados e forma de agendamento. Minha proposta é desenvolver um site profissional para organizar essas respostas, valorizar a forma de atendimento e encurtar o caminho até o agendamento. Posso encaminhar um escopo inicial para vocês avaliarem?

**Advocacia**

> Olá, tudo bem? Sou Pedro, da Norte Digital, e desenvolvo sites para empresas. Ao pesquisar a presença digital do escritório, não encontrei um site próprio vinculado ao perfil do Google. Sem uma página própria, o potencial cliente pode chegar ao WhatsApp ainda com dúvidas sobre áreas de atuação e como iniciar o atendimento. Minha proposta é desenvolver um site profissional para apresentar as áreas de atuação com sobriedade e direcionar o contato inicial. Posso encaminhar um escopo inicial para vocês avaliarem?

**Restaurante**

> Olá, tudo bem? Sou Pedro, da Norte Digital, e desenvolvo sites para empresas. Ao pesquisar a presença digital do restaurante, não encontrei um site próprio vinculado ao perfil do Google. Sem uma página própria, o potencial cliente pode chegar ao WhatsApp ainda com dúvidas sobre cardápio, horários, reservas e pedidos. Minha proposta é desenvolver um site profissional para concentrar essas informações e reduzir etapas até a reserva ou o pedido. Posso encaminhar um escopo inicial para vocês avaliarem?

**Fotografia**

> Olá, tudo bem? Sou Pedro, da Norte Digital, e desenvolvo sites para empresas. Ao pesquisar a presença digital do estúdio, não encontrei um site próprio vinculado ao perfil do Google. Sem uma página própria, o potencial cliente pode chegar ao WhatsApp ainda com dúvidas sobre estilo, trabalhos anteriores e orçamento. Minha proposta é desenvolver um site profissional para valorizar o portfólio e preparar um pedido de orçamento mais completo. Posso encaminhar um escopo inicial para vocês avaliarem?

## Validação com 20 segmentos

| # | Segmento | Nota do revisor | Resultado |
|---:|---|---:|---|
| 1 | Odontologia | 100 | Aprovado |
| 2 | Estética | 100 | Aprovado |
| 3 | Advocacia | 100 | Aprovado |
| 4 | Arquitetura | 100 | Aprovado |
| 5 | Reformas | 100 | Aprovado |
| 6 | Contabilidade | 100 | Aprovado |
| 7 | Engenharia | 100 | Aprovado |
| 8 | Manutenção | 100 | Aprovado |
| 9 | Gastronomia | 100 | Aprovado |
| 10 | Veterinária | 100 | Aprovado |
| 11 | Imobiliária | 100 | Aprovado |
| 12 | Energia solar | 100 | Aprovado |
| 13 | Psicologia | 100 | Aprovado |
| 14 | Fisioterapia | 100 | Aprovado |
| 15 | Educação | 100 | Aprovado |
| 16 | Academia | 100 | Aprovado |
| 17 | Hotelaria | 100 | Aprovado |
| 18 | Fotografia | 100 | Aprovado |
| 19 | Serviços automotivos | 100 | Aprovado |
| 20 | Consultoria | 100 | Aprovado |

Além da matriz de 20 segmentos, foi testado o ciclo completo em que a IA gera uma mensagem artificial, o revisor rejeita e a segunda tentativa corrige o texto usando o feedback recebido.
