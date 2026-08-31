"""Testes da estratégia de seletores e do casamento de colunas.

Tudo aqui é lógica pura: nenhum navegador sobe. O que se testa é justamente
a parte que decide *se dá para confiar* no que o navegador trouxe.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from scraper.seletores import (
    Ancora,
    Estabilidade,
    Mapa,
    alvo,
    casar_colunas,
    extrair_linhas,
    normalizar_cabecalho,
)


class TestAlvo:
    def test_ordena_do_mais_estavel_para_o_mais_fragil(self):
        a = alvo("botao", posicao="tr:nth-child(2) td", texto="Buscar", testid="btn-buscar")
        ordem = [e for e, _ in a.ordenadas()]
        assert ordem == [
            Estabilidade.ATRIBUTO_DE_TESTE,
            Estabilidade.TEXTO,
            Estabilidade.POSICAO,
        ]

    def test_monta_o_seletor_certo_por_tipo(self):
        a = alvo("x", testid="btn", id="campo", rotulo="Buscar", texto="Ir", css=".classe")
        seletores = {e.name: s for e, s in a.ordenadas()}
        assert seletores["ATRIBUTO_DE_TESTE"] == '[data-testid="btn"]'
        assert seletores["ID"] == "#campo"
        assert seletores["ROTULO"] == '[aria-label="Buscar"]'
        assert seletores["TEXTO"] == "text=Ir"
        assert seletores["CSS"] == ".classe"

    def test_alvo_sem_forma_de_localizacao_e_erro_de_programacao(self):
        with pytest.raises(ValueError, match="sem nenhuma forma"):
            alvo("orfao")

    def test_mensagem_de_falha_lista_tudo_que_foi_tentado(self):
        a = alvo("tabela", testid="tbl", texto="Pedidos")
        msg = a.descrever_falha()
        assert "tbl" in msg and "Pedidos" in msg
        assert "mudou de layout" in msg


class TestMapa:
    def test_alvo_nao_declarado_falha_com_mensagem_util(self):
        mapa = Mapa("pedidos", {"busca": alvo("busca", id="q")})
        with pytest.raises(KeyError, match="pedidos"):
            mapa["inexistente"]


class TestNormalizarCabecalho:
    @pytest.mark.parametrize(
        "bruto,esperado",
        [
            ("Nº Pedido", "n_pedido"),
            ("N. Pedido", "n_pedido"),
            ("  VALOR TOTAL  ", "valor_total"),
            ("Data de Emissão", "data_de_emissao"),
        ],
    )
    def test_variacoes_convergem(self, bruto, esperado):
        assert normalizar_cabecalho(bruto) == esperado


class TestCasarColunas:
    CABECALHO: ClassVar[list[str]] = [
        "Nº Pedido",
        "Cliente",
        "Data de Emissão",
        "Valor Total",
        "Situação",
    ]
    DESEJADAS: ClassVar[dict[str, tuple[str, ...]]] = {
        "numero": ("Nº Pedido", "Numero do Pedido"),
        "cliente": ("Cliente",),
        "valor": ("Valor Total", "Total"),
    }

    def test_acha_os_indices(self):
        indices = casar_colunas(self.CABECALHO, self.DESEJADAS)
        assert indices == {"numero": 0, "cliente": 1, "valor": 3}

    def test_coluna_nova_no_meio_nao_quebra(self):
        """O tipo de mudanca que ninguem avisa e que derruba indice fixo."""
        com_coluna_nova = ["Nº Pedido", "Filial", "Cliente", "Data", "Valor Total"]
        indices = casar_colunas(com_coluna_nova, self.DESEJADAS)
        assert indices["cliente"] == 2, "seguiu o cabecalho, nao a posicao antiga"
        assert indices["valor"] == 4

    def test_sinonimo_alternativo_funciona(self):
        indices = casar_colunas(["Numero do Pedido", "Total"], self.DESEJADAS)
        assert indices == {"numero": 0, "valor": 1}

    def test_coluna_ausente_simplesmente_nao_aparece(self):
        indices = casar_colunas(["Cliente"], self.DESEJADAS)
        assert indices == {"cliente": 0}


class TestExtrairLinhas:
    CABECALHO: ClassVar[list[str]] = ["Nº Pedido", "Cliente", "Valor Total"]
    DESEJADAS: ClassVar[dict[str, tuple[str, ...]]] = {
        "numero": ("Nº Pedido",),
        "cliente": ("Cliente",),
        "valor": ("Valor Total",),
    }

    def test_converte_linhas_em_registros(self):
        linhas = [["1001", "Aurora", "8.500,00"], ["1002", "Delta", "3.200,00"]]
        registros, ausentes = extrair_linhas(self.CABECALHO, linhas, self.DESEJADAS)
        assert ausentes == []
        assert registros[0] == {"numero": "1001", "cliente": "Aurora", "valor": "8.500,00"}

    def test_linha_de_total_vazia_e_descartada(self):
        linhas = [["1001", "Aurora", "8.500,00"], ["", "", ""]]
        registros, _ = extrair_linhas(self.CABECALHO, linhas, self.DESEJADAS)
        assert len(registros) == 1

    def test_linha_curta_nao_estoura_indice(self):
        """Portal legado emite <tr> com menos <td> em linha de agrupamento."""
        linhas = [["1001", "Aurora"]]
        registros, _ = extrair_linhas(self.CABECALHO, linhas, self.DESEJADAS)
        assert registros[0] == {"numero": "1001", "cliente": "Aurora"}

    def test_reporta_campo_ausente_em_vez_de_ignorar(self):
        registros, ausentes = extrair_linhas(["Cliente"], [["Aurora"]], self.DESEJADAS)
        assert set(ausentes) == {"numero", "valor"}
        assert registros == [{"cliente": "Aurora"}]


class TestAncora:
    def test_pagina_correta_passa(self):
        ancora = Ancora("lista de pedidos", texto_esperado="Pedidos", minimo_de_linhas=1)
        assert ancora.conferir("Meus Pedidos - Portal", 5, ["Cliente"]) is None

    def test_tela_de_login_e_pega(self):
        """O modo de falha mais caro: raspar 0 linhas e concluir 'sem pedidos'."""
        ancora = Ancora("lista de pedidos", texto_esperado="Pedidos")
        motivo = ancora.conferir("Informe seu usuario e senha", 0, [])
        assert motivo and "Sessao expirada" in motivo

    def test_tabela_curta_demais_e_pega(self):
        ancora = Ancora("lista", minimo_de_linhas=10)
        motivo = ancora.conferir("Pedidos", 2, [])
        assert motivo and "2 linhas" in motivo

    def test_coluna_esperada_ausente_e_pega(self):
        ancora = Ancora("lista", colunas_esperadas=("Cliente", "Valor Total"))
        motivo = ancora.conferir("Pedidos", 5, ["Cliente"])
        assert motivo and "Valor Total" in motivo

    def test_ancora_vazia_nao_reclama_de_nada(self):
        assert Ancora("qualquer").conferir("", 0, []) is None
