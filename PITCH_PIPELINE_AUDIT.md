# Auditoria do pipeline de pitches

## Causa raiz confirmada

1. A mensagem ruim era produzida literalmente pelo fallback fixo de `commercial_intelligence.py`.
2. No ambiente local, nenhuma chave Gemini está configurada. Por isso, o fallback era o caminho efetivo para todas as mensagens.
3. O fallback inseria nome completo, categoria bruta do Google e frases técnicas diretamente no texto comercial.
4. O validador anterior aprovava a mensagem ruim com nota 100 porque verificava apenas tamanho, menção a site e presença do nome.
5. O prompt recebia o objeto técnico inteiro, incluindo evidências escritas como relatório, e não havia uma etapa própria de planejamento comercial.
6. Quando a IA era usada, a primeira opção era o modelo `flash-lite`; uma resposta reprovada não recebia os motivos da reprovação na tentativa seguinte.
7. Os pitches antigos já salvos não eram regenerados porque a migração só reconhecia uma versão legada mais antiga.

## Pipeline implementado

1. **Normalização:** transforma categoria bruta, nome, localização, canais e situação do site em contexto comercial seguro.
2. **Planejamento:** escolhe público, dúvida anterior ao contato, benefício, gancho e valor do site por segmento.
3. **Geração:** produz cinco abordagens diferentes sem copiar os campos técnicos; usa IA quando disponível e fallback contextual quando não está.
4. **Revisão:** rejeita linguagem de relatório, nome completo na saudação, categoria bruta, repetição excessiva, promessa, prévia inexistente, falta de benefício específico e encerramentos duplicados.
5. **Recuperação:** a segunda tentativa da IA recebe os motivos exatos da reprovação; se continuar ruim, entra o fallback contextual já validado.

## Antes e depois — caso real

### Antes

> Oi, equipe da Dra. Rosiene Silva de Brito. Quem compara opções de Dentista costuma precisar entender o serviço e o próximo passo antes de entrar em contato. No perfil público consultado, não identifiquei um site próprio no perfil do Google consultado. A oportunidade mais clara é organizar tratamentos, orientações iniciais e o caminho para agendamento. Um site objetivo pode organizar essas respostas e levar a pessoa interessada ao canal que vocês já usam. Posso compartilhar a estrutura que recomendaria para avaliação?

### Depois

> Oi, tudo bem? Muita gente escolhe onde marcar uma consulta depois de entender os tratamentos e como funciona o primeiro atendimento. Um site bem organizado pode explicar essas etapas com clareza e conduzir o paciente ao agendamento sem transformar o WhatsApp em um balcão de dúvidas. Se fizer sentido, posso te mandar três ideias práticas para essa página?

### Outros exemplos gerados pelo sistema

**Estética**

> Oi, tudo bem? Antes de agendar um procedimento, é comum a pessoa querer entender opções, cuidados e como será atendida. Um site bem organizado pode organizar essas respostas, valorizar a forma de atendimento e encurtar o caminho até o agendamento. Se fizer sentido, posso te mandar três ideias práticas para essa página?

**Advocacia**

> Oi, tudo bem? Quem busca orientação jurídica primeiro precisa saber se o escritório atua naquele tipo de caso e como iniciar a conversa. Um site bem organizado pode apresentar as áreas de atuação com sobriedade e direcionar o contato inicial. Se fizer sentido, posso te mandar três ideias práticas para essa página?

**Restaurante**

> Oi, tudo bem? Cardápio, horário e forma de pedir costumam definir se o cliente avança ou procura outra opção. Um site bem organizado pode concentrar essas informações e reduzir etapas até a reserva ou o pedido. Se fizer sentido, posso te mandar três ideias práticas para essa página?

**Fotografia**

> Oi, tudo bem? Quem contrata fotografia decide muito pelo estilo dos trabalhos anteriores e pela segurança no primeiro contato. Um site bem organizado pode valorizar o portfólio e preparar um pedido de orçamento mais completo. Se fizer sentido, posso te mandar três ideias práticas para essa página?

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
