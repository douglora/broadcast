"""S01: falha de dados. Silencio em dia util e defeito, nao sucesso: quando
>= 3 series do livro ficam sem a barra do dia, ou uma perna oficial (DI,
Tesouro, UST) falha, o proprio runner emite o alerta com a causa."""

from __future__ import annotations

from livro.sinais.base import Alerta, Contexto, Estado, Regra


class S01FalhaDados(Regra):
    id = "S01"
    familia = "sistema"

    def avaliar(self, ctx, estado):
        L = ctx.limiares.get("S01_FALHA_DADOS") or {}
        minimo = int(L.get("series_faltando_min", 3))
        velhas = [i for i, info in ctx.series_info.items() if info.get("esperado_hoje") and not info.get("fresco", True)]
        faltando = [i for i, info in ctx.series_info.items() if info.get("ausente")]
        pernas = {k: v for k, v in ctx.falhas.items() if k in ("di", "tesouro", "ust", "yahoo", "bcb")}
        problemas = []
        if len(velhas) + len(faltando) >= minimo:
            problemas.append(f"{len(velhas) + len(faltando)} séries sem cotação do dia: " + ", ".join((velhas + faltando)[:8]))
        for perna, motivo in pernas.items():
            if perna == "di" and ctx.slot != "manha":
                continue  # ajuste B3 costuma sair depois do fechamento; a manha cobra
            problemas.append(f"{perna}: {motivo}")
        if not problemas:
            return []
        hoje = ctx.hoje.isoformat()
        chave = f"S01:{ctx.slot}"
        if estado.ultima_data(chave) == hoje:
            return []
        estado.marcar(chave, hoje)
        return [Alerta(self.id, "SISTEMA", "atencao", "sistema",
                       f"coleta do slot {ctx.slot} saiu incompleta: " + " · ".join(problemas), tag=ctx.slot, data=hoje,
                       corpo=["O que fiz: entreguei as seções disponíveis; as pernas que falharam estão em LACUNAS."],
                       por_que="silêncio é lido como 'está tudo bem'; declarar a falha é o que permite confiar no restante",
                       fonte="manifest do runner", dados={"velhas": velhas, "faltando": faltando, "pernas": pernas})]


REGRAS = [S01FalhaDados()]
