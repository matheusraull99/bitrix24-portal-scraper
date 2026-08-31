"""Relógio do robô, sempre no fuso de Brasília.

O robô roda em servidor — no CI, `ubuntu-latest`, que vive em UTC. E `now()`
sem fuso devolve a hora de *quem hospeda*, não a de quem usa: depois das 21h
de Brasília o UTC já virou o dia seguinte, então o carimbo sai com a data de
amanhã. Numa prova de falha isso manda quem for depurar procurar o print no
dia errado.

A correção não é passar para UTC — seria trocar um horário errado por outro,
e o portal, o operador e o CRM todos raciocinam em horário de Brasília. É
declarar o fuso, uma vez, aqui.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

#: Fuso de referência do negócio. Cuida do horário de verão sozinho, porque a
#: regra vem da base IANA e não de um offset fixo escrito na mão.
FUSO = ZoneInfo("America/Sao_Paulo")


def agora() -> datetime:
    """Instante atual em Brasília, já com o fuso embutido."""
    return datetime.now(FUSO)
