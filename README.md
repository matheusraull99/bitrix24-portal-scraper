# bitrix24-portal-scraper

Raspa um portal legado que não tem API e leva os dados para o Bitrix24 — com
seletores que resistem a mudança de layout e uma âncora que **para o robô**
quando a página não é a esperada.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Playwright](https://img.shields.io/badge/playwright-1.45%2B-green)
![Testes](https://img.shields.io/badge/testes-22%20passando-brightgreen)
![Licença](https://img.shields.io/badge/licença-MIT-lightgrey)

---

## O problema

Nem todo sistema tem API. Distribuidor, transportadora, órgão público — o
dado está lá, atrás de um login, numa tabela HTML. RPA de navegador é a única
saída, e ele quebra de dois jeitos:

**Barulhento:** o seletor não acha nada, o robô estoura, alguém conserta.
Chato, mas visível.

**Silencioso:** o portal insere uma coluna no meio da tabela. O seletor por
posição continua achando *algo* — e o robô passa a gravar a data de emissão
no campo de valor. Isso roda por semanas até alguém estranhar um relatório.

O segundo é o caro. Este projeto é construído em torno de evitá-lo.

---

## Cadeia de seletores, do estável ao frágil

```python
alvo("botao_buscar",
     testid="btn-buscar",      # ATRIBUTO_DE_TESTE — só muda de propósito
     id="busca",               # ID
     rotulo="Buscar",          # ROTULO (aria-label)
     texto="Buscar",           # TEXTO — quebra com revisão de copy
     css=".btn-primary")       # CSS — quebra com refatoração
```

O robô tenta na ordem e **avisa no log** quando cai num seletor frágil: o
elemento ainda foi achado, mas o caminho bom quebrou — é hora de consertar,
não de esperar a parada total.

Quando nada bate, a exceção lista tudo que foi tentado. Quem for consertar
precisa saber o que já não funciona.

---

## Âncoras: parar é melhor que raspar lixo

```python
Ancora(
    descricao="lista de pedidos",
    texto_esperado="Pedidos",      # sessão expirada devolve a tela de login
    minimo_de_linhas=1,            # tabela vazia é suspeita, não conclusão
    colunas_esperadas=("Cliente",),
)
```

O modo de falha mais caro dessa categoria de robô é raspar zero linha da tela
de login e concluir, com toda a confiança, que o cliente não tem pedidos. A
âncora barra isso antes de qualquer escrita no CRM.

---

## Colunas por cabeçalho, nunca por posição

```python
CAMPOS = {
    "numero": ("Nº Pedido", "N. Pedido", "Numero do Pedido", "Pedido"),
    "valor":  ("Valor Total", "Total", "Valor"),
}
```

O índice de cada coluna é **descoberto** a cada execução. Coluna nova inserida
no meio da tabela — a mudança que ninguém avisa — não desloca nada.

Um detalhe que só apareceu no teste: `º` (indicador ordinal) decompõe para
`o` no NFKD. Sem tratar isso, `Nº Pedido` normaliza para `no_pedido` e **não**
casa com `N. Pedido` — exatamente a convergência que a normalização existia
para garantir.

---

## Uso

```bash
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env

raspar-portal --url https://portal.exemplo.com.br            # simula
raspar-portal --url https://portal.exemplo.com.br --visivel  # vê o navegador
raspar-portal --url https://portal.exemplo.com.br --executar # grava no CRM
```

---

## Decisões técnicas

**Nunca `sleep`.** Esperar 3 segundos é apostar que a rede está boa hoje.
Esperar o elemento aparecer é determinístico: rápido quando dá certo,
explícito quando não dá.

**Espera pela primeira linha de dados, não pela tag `<table>`.** Muitos
portais renderizam a tabela vazia e preenchem por AJAX. Quem espera só pelo
elemento raspa zero linha achando que terminou.

**Sessão persistida em `storage_state`.** Login a cada execução multiplica o
risco de bloqueio e é a parte mais lenta do fluxo. O login só acontece quando
a sessão realmente expirou.

**Print e HTML salvos em toda falha.** Depurar RPA que quebrou às 3h sem
prova é adivinhação sobre um portal que já mudou de novo. O `__exit__` salva
a prova automaticamente quando o bloco sai por exceção.

**Salvar a prova nunca mascara o erro real.** O `except` ali é largo de
propósito e só loga: se o screenshot falhar, quem sobe é a exceção original.

**Valor em formato brasileiro tem conversão própria.** `8.500,00` passado
direto para `Decimal` estoura — ou, pior, `8.500` vira oito e meio.

---

## Testes

```bash
pytest -q
```

22 testes, nenhum navegador envolvido. O que se testa é a parte que decide
**se dá para confiar** no que o navegador trouxe: ordem dos seletores,
casamento de colunas com coluna nova no meio, linha curta que não estoura
índice, e cada modo de falha da âncora.

## Licença

MIT.
