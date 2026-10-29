# OptimistFi

Divulgações de empresas dos EUA como ferramentas para agentes e fluxos do Dify: negociações de insiders do Form 4 da SEC, negociações de ações de membros da Câmara dos EUA, eventos 8-K e verificações de sinais de alerta da SEC EDGAR, e datas de resultados projetadas. Sem chave de API.

**Autor:** [OptimistFi](https://optimistfi.com) · **Código-fonte:** [github.com/OptimistFi/dify-plugin-optimistfi](https://github.com/OptimistFi/dify-plugin-optimistfi) · **Contato:** hello@optimistfi.com

<div align="center">
    <img src="../_assets/screenshot-congress.png" alt="Resposta de um Chatflow: divulgações de negociações de NVDA por membros da Câmara, com compras, vendas, a conta de cada operação e cada registro com link" width="95%"/>
</div>

## Visão geral

A OptimistFi lê os registros de empresas na SEC EDGAR e as divulgações de negociações de ações no Escritório do Secretário da Câmara dos EUA. Cada negociação traz duas datas: o dia em que aconteceu e o dia em que o registro a tornou pública. Este plugin leva esses dados ao Dify como quatro ferramentas.

## Configuração

Não há nada a configurar: nenhuma chave de API, credencial ou etapa de autorização. Instale a **OptimistFi** pelo Marketplace do Dify e as quatro ferramentas ficam prontas em agentes, Chatflows e Workflows. O plugin se conecta a `https://mcp.optimistfi.com/mcp` por HTTPS, então um Dify auto-hospedado precisa de acesso de saída a esse endereço.

## Ferramentas

| Ferramenta | O que responde |
|---|---|
| **Negociações de insiders** | Os registros Form 4 de uma empresa dos EUA na SEC EDGAR: quem, cargo, código da operação, ações e valor em dólares, com a data do negócio e a data em que se tornou público. Compras e vendas no mercado vêm primeiro, depois concessões, exercícios de opções e doações. |
| **Negociações do Congresso** | Divulgações de ações da Câmara dos EUA sob o STOCK Act, por ticker ou por membro. Uma resposta por ticker começa com compras, vendas e os membros mais ativos; cada linha indica a conta em que a operação foi feita e leva ao registro. |
| **Registros na SEC** | Eventos 8-K, comunicados de resultados, o texto dos 8-Ks recentes e sinais de alerta de governança (registros atrasados, troca de auditor, concentração de vendas de insiders). |
| **Calendário de resultados** | A próxima data de resultados projetada pelo ritmo de registros da própria empresa, marcada como estimativa com a sua base, e as leituras de ensaios clínicos quando a empresa os tem. |

## Casos de uso

- **Monitor de insiders e do Congresso:** um Workflow agendado lê Negociações de insiders e Negociações do Congresso para uma lista e envia os registros novos ao Slack ou por e-mail.
- **Preparação da semana de resultados:** um agente lista quem divulga resultados na semana e traz os eventos 8-K recentes e as verificações de sinais de alerta de cada empresa.
- **Agente de due diligence:** um agente com as quatro ferramentas responde "alguém na Moderna vendeu ações neste trimestre", "quais membros da Câmara compraram NVDA" e "esta empresa trocou de auditor".

## Saídas nos Workflows

Cada nó de ferramenta retorna `text` (um resumo em markdown com unidades, horário da leitura e link da fonte), `json` (os registros completos), variáveis tipadas (como `company`, `count`, `acquired_usd`, `lean`, `next_earnings`) e `error`, preenchida quando a chamada não traz dados. A opção *Detalhe da resposta* pode deixar de fora os registros completos, o que mantém pequeno o contexto de um agente.

## Sobre os dados

Cada resposta traz o horário da leitura e a fonte: SEC EDGAR ou o Escritório do Secretário da Câmara dos EUA. Cada negociação mostra a data em que aconteceu e a data em que se tornou pública. Quando a OptimistFi não leu algo, a resposta diz isso em vez de retornar uma lista vazia. Datas projetadas são marcadas como estimativas.

## Privacidade

O plugin envia à OptimistFi apenas as entradas de cada ferramenta (um ticker ou nome de empresa, o nome de um membro da Câmara, um tipo de registro). Não coleta dados pessoais e não armazena nada. Veja [PRIVACY.md](../PRIVACY.md).

## Licença

[Licença MIT](../LICENSE).

**Aviso:** os dados são para pesquisa e informação. Não são recomendação de investimento, e o plugin não envia ordens nem movimenta dinheiro.
