"""Camada Playwright: sessão reaproveitada, espera por estado e prova de falha.

Três hábitos que separam RPA de navegador que sobrevive de um que dá plantão:

**Nunca ``sleep``.** Esperar 3 segundos é apostar que a rede está boa hoje.
Esperar o *elemento* aparecer é determinístico: rápido quando dá certo,
explícito quando não dá.

**Sessão persistida.** Fazer login a cada execução multiplica o risco de
bloqueio por tentativa e é a parte mais lenta do fluxo. O ``storage_state``
guarda os cookies; o login só acontece quando a sessão expirou de verdade.

**Prova quando falha.** Print da tela e HTML no momento do erro. Sem isso,
depurar RPA que quebrou às 3h vira adivinhação sobre um portal que já mudou.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .seletores import Alvo, Ancora, extrair_linhas
from .tempo import agora

if TYPE_CHECKING:  # `Self` so existe em typing a partir do 3.11, e o piso aqui e 3.10.
    from typing_extensions import Self

log = logging.getLogger("scraper")


class PortalMudou(RuntimeError):
    """A página não é o que o robô esperava — abortar é mais seguro que seguir."""


class SessaoExpirada(RuntimeError):
    """Precisa fazer login de novo."""


@dataclass
class Config:
    url_base: str
    usuario: str
    senha: str
    sessao: Path = Path("state/sessao.json")
    provas: Path = Path("saida/provas")
    timeout_ms: int = 15_000
    headless: bool = True


class Portal:
    """Fachada sobre o Playwright com as garantias acima."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self) -> Self:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.config.headless)

        estado = (
            str(self.config.sessao) if self.config.sessao.exists() else None
        )
        if estado:
            log.info("reaproveitando sessao de %s", self.config.sessao)
        self._context = self._browser.new_context(
            storage_state=estado,
            viewport={"width": 1440, "height": 900},
            locale="pt-BR",
        )
        self._context.set_default_timeout(self.config.timeout_ms)
        self.page = self._context.new_page()
        return self

    def __exit__(self, tipo, valor, traceback) -> None:
        if tipo is not None and self.page:
            self.guardar_prova("falha")
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------ #

    def localizar(self, alvo: Alvo):
        """Tenta cada seletor do alvo, da forma mais estável para a mais frágil.

        Raises:
            PortalMudou: nenhuma forma funcionou e o alvo é obrigatório. A
                mensagem lista tudo que foi tentado — quem for consertar
                precisa saber o que já não funciona.
        """
        for estabilidade, seletor in alvo.ordenadas():
            elemento = self.page.locator(seletor).first
            if elemento.count():
                if estabilidade.value >= 3:
                    # Ainda funciona, mas e um aviso: o seletor bom quebrou.
                    log.warning(
                        "'%s' achado por seletor fragil (%s); considere um data-testid",
                        alvo.nome, estabilidade.name,
                    )
                return elemento

        if alvo.obrigatorio:
            self.guardar_prova(f"alvo_{alvo.nome}")
            raise PortalMudou(alvo.descrever_falha())
        return None

    def esperar_tabela(self, seletor_tabela: str) -> tuple[list[str], list[list[str]]]:
        """Espera a tabela carregar e devolve cabeçalho e linhas.

        Espera pela **primeira linha de dados**, não pela tag ``<table>``:
        muitos portais renderizam a tabela vazia e preenchem por AJAX, e
        quem espera só pelo elemento raspa zero linha achando que acabou.
        """
        self.page.wait_for_selector(f"{seletor_tabela} tbody tr", state="visible")

        cabecalho = self.page.locator(f"{seletor_tabela} thead th").all_inner_texts()
        if not cabecalho:
            cabecalho = self.page.locator(f"{seletor_tabela} tr:first-child td").all_inner_texts()

        linhas = []
        for linha in self.page.locator(f"{seletor_tabela} tbody tr").all():
            linhas.append([c.strip() for c in linha.locator("td").all_inner_texts()])
        return [c.strip() for c in cabecalho], linhas

    def raspar(
        self,
        seletor_tabela: str,
        campos: dict[str, tuple[str, ...]],
        ancora: Ancora | None = None,
    ) -> list[dict[str, str]]:
        """Raspa a tabela conferindo a âncora antes de confiar no resultado."""
        cabecalho, linhas = self.esperar_tabela(seletor_tabela)

        if ancora:
            problema = ancora.conferir(self.page.inner_text("body"), len(linhas), cabecalho)
            if problema:
                self.guardar_prova("ancora")
                raise PortalMudou(problema)

        registros, ausentes = extrair_linhas(cabecalho, linhas, campos)
        if ausentes:
            self.guardar_prova("colunas")
            raise PortalMudou(
                f"colunas nao encontradas: {ausentes}. Cabecalho lido: {cabecalho}"
            )
        log.info("%d registros raspados", len(registros))
        return registros

    def guardar_prova(self, rotulo: str) -> Path:
        """Salva print e HTML para depuração posterior."""
        self.config.provas.mkdir(parents=True, exist_ok=True)
        carimbo = agora().strftime("%Y%m%d-%H%M%S")
        base = self.config.provas / f"{carimbo}_{rotulo}"
        try:
            self.page.screenshot(path=f"{base}.png", full_page=True)
            base.with_suffix(".html").write_text(self.page.content(), encoding="utf-8")
            log.error("prova salva em %s.png", base)
        except Exception:
            # Captura ampla de proposito: salvar prova nunca pode mascarar o erro real.
            log.exception("nao consegui salvar a prova")
        return base

    def salvar_sessao(self) -> None:
        """Persiste cookies para a próxima execução pular o login."""
        self.config.sessao.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(self.config.sessao))
        log.info("sessao salva em %s", self.config.sessao)


@contextmanager
def sessao_valida(portal: Portal, fazer_login, esta_logado):
    """Garante login, reaproveitando a sessão quando ela ainda vale.

    Args:
        portal: instância já aberta.
        fazer_login: função que executa o login na página.
        esta_logado: função que devolve ``True`` se a sessão está viva.
    """
    if not esta_logado(portal.page):
        log.info("sessao expirada; fazendo login")
        fazer_login(portal.page)
        if not esta_logado(portal.page):
            portal.guardar_prova("login")
            raise SessaoExpirada("login nao completou — credencial ou captcha?")
        portal.salvar_sessao()
    yield portal


def carregar_config(caminho: Path, ambiente: dict[str, Any]) -> Config:
    """Lê a configuração do portal, com credencial vindo só do ambiente."""
    dados = json.loads(caminho.read_text("utf-8"))
    return Config(
        url_base=dados["url_base"],
        usuario=ambiente.get("PORTAL_USER", ""),
        senha=ambiente.get("PORTAL_PASSWORD", ""),
        sessao=Path(dados.get("sessao", "state/sessao.json")),
        provas=Path(dados.get("provas", "saida/provas")),
        timeout_ms=int(dados.get("timeout_ms", 15_000)),
        headless=bool(dados.get("headless", True)),
    )
