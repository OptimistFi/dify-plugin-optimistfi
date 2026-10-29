# OptimistFi

Futuros perpétuos em mais de 40 corretoras, mesas proprietárias de cripto e divulgações de empresas dos EUA, como ferramentas para agentes e workflows do Dify. Sem chave de API.

**Autor:** [OptimistFi](https://optimistfi.com) · **Código:** [github.com/OptimistFi/dify-plugin-optimistfi](https://github.com/OptimistFi/dify-plugin-optimistfi) · **Contato:** hello@optimistfi.com

<div align="center">
    <img src="../_assets/screenshot-chart.png" alt="Resposta de um Chatflow: preço e funding do BTC em sete dias" width="95%"/>
</div>

## Visão geral

A OptimistFi lê as principais corretoras de futuros perpétuos a cada hora, as regras e os preços das mesas proprietárias que financiam traders de perpétuos de cripto e ações, e as divulgações de empresas na SEC EDGAR e no Escritório do Secretário da Câmara dos EUA. Este plugin leva esses dados ao Dify como oito ferramentas.

## Configuração

Não há nada a configurar: nenhuma chave de API, credencial ou autorização. Instale a **OptimistFi** pelo Dify Marketplace e as oito ferramentas ficam prontas em agentes, Chatflows e Workflows. O plugin se conecta a `https://mcp.optimistfi.com/mcp` por HTTPS; um Dify auto-hospedado precisa de acesso de saída a esse endereço.

## Ferramentas

| Ferramenta | O que responde |
|---|---|
| **Mercado perpétuo** | Um mercado em todas as corretoras agora: preço, open interest, funding, alavancagem, níveis de liquidação, os maiores negócios e o posicionamento das grandes contas. |
| **Histórico do perpétuo** | Um mercado em 1, 7, 30 ou 90 dias: preço, open interest, funding, fluxo a mercado e a posição líquida das contas de US$10 mi+ na Hyperliquid. |
| **Screener de perpétuos** | 20 visões classificadas: open interest em alta, maiores variações, extremos e diferenças de funding, liquidações, faixa de liquidação máxima, negócios de US$100 mil+, posicionamento das contas de US$1 mi+, fluxos de ETFs à vista, opções, basis de futuros, medo e ganância, setores e mais. |
| **Mesas proprietárias** | Regras, o preço de cada desafio (com taxa de ativação após a aprovação), códigos de desconto ativos, país e alocação máxima, lidos das páginas de cada empresa. |
| **Negociações de insiders** | Registros Form 4 da SEC EDGAR, com a data do negócio e a data em que se tornou público. |
| **Negociações do Congresso** | Divulgações de ações da Câmara dos EUA sob o STOCK Act, por ticker ou por parlamentar, com link para o registro. |
| **Documentos na SEC** | Eventos 8-K, comunicados de resultados, texto do 8-K e alertas de governança. |
| **Calendário de resultados** | A próxima data de resultados projetada pelo ritmo de registros da própria empresa, marcada como estimativa e com a base. |

## Saídas nos Workflows

Cada nó de ferramenta retorna `text` (resumo em Markdown com unidades, horário e link da fonte), `json` (os registros completos), variáveis tipadas e `error` quando não há dados. As ferramentas de perpétuos também retornam `chart`: insira a variável `chart` do nó da ferramenta em um nó Answer e o Dify desenha o gráfico. A opção "Detalhe da resposta" pode trazer só o resumo, para manter pequeno o contexto do agente.

## Sobre os dados

Cada resposta traz o horário da leitura e a fonte: os dados públicos de cada corretora, a SEC EDGAR ou a Câmara dos EUA. O que não foi lido aparece como tal, nunca como lista vazia; datas projetadas são marcadas como estimativas.

## Privacidade

O plugin envia à OptimistFi apenas as entradas de cada ferramenta (um ticker, o nome de uma empresa, uma visão). Não coleta dados pessoais e não armazena nada. Veja [PRIVACY.md](../PRIVACY.md).

## Licença

[Licença MIT](../LICENSE).

**Aviso:** os dados servem para pesquisa e informação, não são recomendação de investimento. O plugin não envia ordens nem movimenta dinheiro.
