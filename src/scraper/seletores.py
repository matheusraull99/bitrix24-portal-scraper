"""Estratégia de seletores para portal legado que não foi feito para robô.

A causa nº 1 de RPA quebrado não é o site cair — é o site mudar de leve. Um
`div` a mais no layout e todo seletor tipo
``body > div:nth-child(3) > table > tr:nth-child(2)`` aponta para outro lugar.
Pior: às vezes aponta para um lugar *válido*, e o robô passa a raspar a coluna
errada em silêncio.

A defesa é uma cadeia de tentativas, da mais estável para a mais frágil, e uma
**âncora** que falha alto quando nada bate. Falhar é barato; raspar dado errado
por três semanas não é.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum


class Estabilidade(IntEnum):
    """Quanto um tipo de seletor resiste a mudança de layout."""

    ATRIBUTO_DE_TESTE = 0  # data-testid: só muda se alguém decidir mudar
    ID = 1                 # id: estável, mas às vezes gerado
    ROTULO = 2             # label/aria-label: acompanha o texto visível
    TEXTO = 3              # texto visível: quebra com tradução e revisão
    CSS = 4                # classe: quebra a cada refatoração de CSS
    POSICAO = 5            # nth-child: quebra com qualquer div nova


@dataclass(frozen=True)
class Alvo:
    """Um elemento descrito por várias formas de encontrá-lo.

    Args:
        nome: identificação legível, usada no log e na mensagem de erro.
        tentativas: seletores em ordem de preferência.
        obrigatorio: quando ``True``, não encontrar aborta a raspagem.
    """

    nome: str
    tentativas: tuple[tuple[Estabilidade, str], ...]
    obrigatorio: bool = True

    def ordenadas(self) -> list[tuple[Estabilidade, str]]:
        """Tentativas da mais estável para a mais frágil."""
        return sorted(self.tentativas, key=lambda t: t[0])

    def descrever_falha(self) -> str:
        formas = "\n".join(f"    [{e.name}] {s}" for e, s in self.ordenadas())
        return (
            f"nao encontrei '{self.nome}'. Tentei, nesta ordem:\n{formas}\n"
            "  O portal provavelmente mudou de layout — atualize os seletores."
        )


def alvo(nome: str, **formas: str) -> Alvo:
    """Açúcar para declarar um alvo.

    >>> a = alvo("botao_buscar", testid="btn-buscar", texto="Buscar")
    >>> a.ordenadas()[0][1]
    '[data-testid="btn-buscar"]'
    """
    mapa = {
        "testid": (Estabilidade.ATRIBUTO_DE_TESTE, lambda v: f'[data-testid="{v}"]'),
        "id": (Estabilidade.ID, lambda v: f"#{v}"),
        "rotulo": (Estabilidade.ROTULO, lambda v: f'[aria-label="{v}"]'),
        "texto": (Estabilidade.TEXTO, lambda v: f"text={v}"),
        "css": (Estabilidade.CSS, lambda v: v),
        "posicao": (Estabilidade.POSICAO, lambda v: v),
    }
    tentativas = tuple(
        (mapa[chave][0], mapa[chave][1](valor))
        for chave, valor in formas.items()
        if chave in mapa
    )
    if not tentativas:
        raise ValueError(f"alvo {nome!r} sem nenhuma forma de localizacao")
    return Alvo(nome, tentativas)


@dataclass
class Ancora:
    """Verificação de sanidade da página antes de raspar qualquer coisa.

    Se o portal devolveu a tela de login, uma página de manutenção ou um
    layout novo, a âncora não bate — e o robô para **antes** de gravar lixo
    no CRM. Sem isso o modo de falha típico é raspar 400 linhas vazias e
    concluir, com toda a confiança, que o cliente não tem pedidos.
    """

    descricao: str
    texto_esperado: str | None = None
    minimo_de_linhas: int = 0
    colunas_esperadas: tuple[str, ...] = ()

    def conferir(self, texto_da_pagina: str, linhas: int, colunas: list[str]) -> str | None:
        """Devolve o motivo da falha, ou ``None`` quando está tudo certo."""
        if self.texto_esperado and self.texto_esperado.lower() not in texto_da_pagina.lower():
            return (
                f"ancora '{self.descricao}': nao achei {self.texto_esperado!r} na pagina. "
                "Sessao expirada ou layout novo?"
            )
        if linhas < self.minimo_de_linhas:
            return (
                f"ancora '{self.descricao}': {linhas} linhas, esperava ao menos "
                f"{self.minimo_de_linhas}. Filtro errado ou tabela vazia?"
            )
        if self.colunas_esperadas:
            faltando = [c for c in self.colunas_esperadas if c not in colunas]
            if faltando:
                return (
                    f"ancora '{self.descricao}': colunas ausentes {faltando}. "
                    f"Encontradas: {colunas}"
                )
        return None


@dataclass
class Mapa:
    """Conjunto de alvos e âncoras de uma tela do portal."""

    tela: str
    alvos: dict[str, Alvo] = field(default_factory=dict)
    ancora: Ancora | None = None

    def __getitem__(self, nome: str) -> Alvo:
        if nome not in self.alvos:
            raise KeyError(f"alvo {nome!r} nao declarado no mapa da tela {self.tela!r}")
        return self.alvos[nome]


#: Indicadores ordinais e o símbolo de grau. Precisam sair **antes** do NFKD:
#: a decomposição de compatibilidade transforma "º" em "o", então "Nº Pedido"
#: viraria "no_pedido" e deixaria de casar com "N. Pedido" — justamente a
#: convergência que esta função existe para garantir.
_ORDINAIS = str.maketrans({"º": "", "ª": "", "°": "", "º".upper(): ""})


def normalizar_cabecalho(bruto: str) -> str:
    """Achata o cabeçalho de tabela para comparação estável.

    Portal legado troca ``Nº Pedido`` por ``N. Pedido`` numa atualização
    qualquer. Comparar a versão achatada evita que isso vire incidente.

    >>> normalizar_cabecalho("Nº Pedido") == normalizar_cabecalho("N. Pedido")
    True
    """
    import unicodedata

    limpo = bruto.strip().lower().translate(_ORDINAIS)
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", limpo) if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "_", sem_acento).strip("_")


def casar_colunas(
    cabecalho: list[str], desejadas: dict[str, tuple[str, ...]]
) -> dict[str, int]:
    """Descobre o índice de cada coluna de interesse.

    Trabalhar por índice descoberto — e não por posição fixa — é o que faz a
    raspagem sobreviver a uma coluna nova inserida no meio da tabela, que é o
    tipo de mudança que ninguém avisa.

    Args:
        cabecalho: textos do cabeçalho, na ordem em que aparecem.
        desejadas: mapa ``campo -> sinônimos aceitos de cabeçalho``.

    Returns:
        Mapa ``campo -> índice``, só com os campos encontrados.
    """
    achatado = [normalizar_cabecalho(c) for c in cabecalho]
    indices: dict[str, int] = {}
    for campo, sinonimos in desejadas.items():
        alvos = {normalizar_cabecalho(s) for s in sinonimos}
        for posicao, coluna in enumerate(achatado):
            if coluna in alvos:
                indices[campo] = posicao
                break
    return indices


def extrair_linhas(
    cabecalho: list[str], linhas: list[list[str]], desejadas: dict[str, tuple[str, ...]]
) -> tuple[list[dict[str, str]], list[str]]:
    """Converte a tabela crua em registros, reportando o que não achou.

    Returns:
        Os registros e a lista de campos ausentes. Devolver os ausentes em vez
        de ignorá-los deixa a decisão de abortar com quem chamou — alguns
        campos são opcionais, outros não.
    """
    indices = casar_colunas(cabecalho, desejadas)
    ausentes = [c for c in desejadas if c not in indices]

    registros = []
    for bruta in linhas:
        registro = {
            campo: bruta[posicao].strip()
            for campo, posicao in indices.items()
            if posicao < len(bruta)
        }
        if any(registro.values()):  # descarta linha de separador/total vazia
            registros.append(registro)
    return registros, ausentes
