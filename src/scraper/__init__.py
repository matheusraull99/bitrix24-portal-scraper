"""Raspagem resiliente de portal legado, com destino no Bitrix24."""

from .navegador import Config, Portal, PortalMudou, SessaoExpirada, sessao_valida
from .seletores import (
    Alvo,
    Ancora,
    Estabilidade,
    Mapa,
    alvo,
    casar_colunas,
    extrair_linhas,
    normalizar_cabecalho,
)

__version__ = "1.0.0"

__all__ = [
    "Alvo",
    "Ancora",
    "Config",
    "Estabilidade",
    "Mapa",
    "Portal",
    "PortalMudou",
    "SessaoExpirada",
    "alvo",
    "casar_colunas",
    "extrair_linhas",
    "normalizar_cabecalho",
    "sessao_valida",
]
