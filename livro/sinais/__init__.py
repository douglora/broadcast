"""Motor de sinais: cada regra recebe o Contexto (series, curvas, macro, hoje,
limiares) e o Estado persistido, e devolve Alertas com id deterministico.
A sessao do Claude nunca calcula regra: ela narra o que sai daqui."""

from livro.sinais.base import Alerta, Contexto, Regra  # noqa: F401


def todas() -> list:
    from livro.sinais import curvas, eventos, fx_commod, sistema, tecnicas
    return tecnicas.REGRAS + curvas.REGRAS + fx_commod.REGRAS + eventos.REGRAS + sistema.REGRAS
