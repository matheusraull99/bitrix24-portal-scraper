"""Raspagem do portal legado e envio dos pedidos para o Bitrix24.

O fluxo completo: entra no portal, confere a âncora, raspa a tabela, converte
para o formato do CRM e cria/atualiza os negócios em lote.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bitrix24_client import from_env
from bitrix24_client.errors import BitrixError

from .navegador import Config, Portal, PortalMudou, SessaoExpirada, sessao_valida
from .seletores import Ancora, alvo

#: Campos que interessam na tabela do portal, com os sinônimos de cabeçalho
#: já observados em atualizações anteriores dele.
CAMPOS = {
    "numero": ("Nº Pedido", "N. Pedido", "Numero do Pedido", "Pedido"),
    "cliente": ("Cliente", "Razao Social"),
    "emissao": ("Data de Emissão", "Emissao", "Data"),
    "valor": ("Valor Total", "Total", "Valor"),
    "situacao": ("Situação", "Status"),
}

ANCORA = Ancora(
    descricao="lista de pedidos",
    texto_esperado="Pedidos",
    minimo_de_linhas=1,
    colunas_esperadas=("Cliente",),
)

CAMPO_USUARIO = alvo("usuario", testid="login-user", id="usuario", rotulo="Usuário")
CAMPO_SENHA = alvo("senha", testid="login-pass", id="senha", rotulo="Senha")
BOTAO_ENTRAR = alvo("entrar", testid="login-submit", texto="Entrar")


def valor_br(bruto: str) -> Decimal:
    """Converte ``8.500,00`` em ``Decimal("8500.00")``.

    O formato brasileiro inverte ponto e vírgula em relação ao que o
    ``Decimal`` espera. Passar direto dá ``InvalidOperation`` ou, pior,
    interpreta ``8.500`` como oito e meio.
    """
    limpo = re.sub(r"[^\d,.-]", "", bruto or "")
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo or "0")
    except InvalidOperation:
        return Decimal(0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="raspar-portal",
        description="Raspa pedidos de um portal legado e leva para o Bitrix24.",
    )
    p.add_argument("--url", default=os.environ.get("PORTAL_URL", ""))
    p.add_argument("--tabela", default="table#pedidos", help="seletor CSS da tabela")
    p.add_argument("--sessao", type=Path, default=Path("state/sessao.json"))
    p.add_argument("--visivel", action="store_true", help="abre o navegador na tela")
    p.add_argument("--executar", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.url:
        print("informe --url ou PORTAL_URL", file=sys.stderr)
        return 2

    config = Config(
        url_base=args.url,
        usuario=os.environ.get("PORTAL_USER", ""),
        senha=os.environ.get("PORTAL_PASSWORD", ""),
        sessao=args.sessao,
        headless=not args.visivel,
    )

    def logado(page) -> bool:
        return "Pedidos" in page.inner_text("body")

    def login(page) -> None:
        page.goto(f"{config.url_base}/login")
        page.fill("#usuario", config.usuario)
        page.fill("#senha", config.senha)
        page.click("text=Entrar")
        page.wait_for_load_state("networkidle")

    try:
        with Portal(config) as portal:
            portal.page.goto(f"{config.url_base}/pedidos")
            with sessao_valida(portal, login, logado):
                registros = portal.raspar(args.tabela, CAMPOS, ANCORA)
    except (PortalMudou, SessaoExpirada) as exc:
        print(f"\nRASPAGEM ABORTADA\n{exc}", file=sys.stderr)
        return 2

    print(f"\n{len(registros)} pedidos raspados")
    for registro in registros[:5]:
        print(f"  {registro['numero']} — {registro['cliente']} — {registro['valor']}")

    if not args.executar:
        print("\nSIMULACAO (use --executar para gravar no CRM)")
        return 0

    try:
        bx = from_env()
        criados = 0
        for registro, _, erro in bx.batch_iter(
            registros,
            "crm.deal.add",
            lambda r: {
                "fields": {
                    "TITLE": f"Pedido {r['numero']} — {r['cliente']}",
                    "OPPORTUNITY": str(valor_br(r.get("valor", ""))),
                    "UF_CRM_PEDIDO_PORTAL": r["numero"],
                    "COMMENTS": f"Situacao no portal: {r.get('situacao', '')}",
                }
            },
        ):
            criados += 0 if erro else 1
            if erro:
                print(f"  pedido {registro['numero']}: FALHOU — {erro}")
    except BitrixError as exc:
        print(f"erro no portal Bitrix: {exc}", file=sys.stderr)
        return 2

    print(f"\n{criados} negocios criados")
    return 0 if criados == len(registros) else 1


if __name__ == "__main__":
    raise SystemExit(main())
