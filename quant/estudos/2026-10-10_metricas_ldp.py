"""Metricas formais (Sharpe liquido, queda maxima, Sharpe deflacionado) das duas regras com mecanismo e evidencia.
Regra aprovada: reversao do dado americano no mini-dolar (gatilho 3). Regra em prova viva: fim do pregao no mini-indice.
ATENCAO: para estas duas regras 2025 e 2026 ja foram abertos antes; aqui so se mede o que ja foi visto, com a regua nova."""
import json, numpy as np, pandas as pd
from quant.pesquisa import lab, ldp
from quant.saida.pesquisa5.calendario import regras as cal
from quant.pesquisa.regras import win_fim_do_dia as wf

n_sim = sum(1 for x in open(lab.REGISTRO, encoding="utf-8") if '"tipo": "evento"' not in x and '"triagem"' not in x)
print(f"simulacoes completas no registro: {n_sim} (as frentes relataram mais ~35 mil medicoes de triagem)")
casos = {
    "DADO (WDO, gatilho 3, 120 min, stop 40)": ("WDO", lambda m: cal.reverte_dado_ny(m, r=2, thr=3.0), dict(stop=40.0, tempo=120), ("descoberta", "validacao", "prova")),
    "FIM DO PREGAO (WIN, 25 min, stop 500)": ("WIN", wf.regra, dict(stop=500.0, tempo=25, ini="09:00", ult="18:30", zerar="18:30"), ("descoberta", "validacao")),
}
for nome, (ativo, regra, kw, partes) in casos.items():
    print("\n==", nome)
    todos = []
    for parte in partes:
        m = lab.carregar(ativo, parte)
        r = lab.avaliar(m, regra(m), nome, "metricas", ativo=ativo, registrar=False, **kw)
        t = lab.medir(r["negocios"], espec=lab.espec_de(ativo))
        rd = ldp.retorno_por_pregao(t, lab.dia(m)); rd.index = pd.to_datetime(rd.index); todos.append(rd)
        print(f"  {parte:<10} negocios {len(t):>3} | Sharpe anual {ldp.sharpe_anual(rd):+.2f} | media por pregao R$ {rd.mean() * 1e5:+.1f} | desvio por pregao R$ {rd.std() * 1e5:.0f} | "
              f"queda maxima R$ {ldp.queda_maxima(rd) * 1e5:.0f} | pior pregao R$ {rd.min() * 1e5:.0f}")
    j = pd.concat(todos); fora = pd.concat(todos[1:])
    for rot, x in (("tudo", j), ("fora da descoberta", fora)):
        print(f"  {rot:<18} pregoes {len(x)} | Sharpe anual {ldp.sharpe_anual(x):+.2f} | PSR(>0) {ldp.psr(x):.3f} | Sharpe deflacionado com 100 tentativas {ldp.dsr(x, 100):.3f}, "
              f"com 2.500: {ldp.dsr(x, 2500):.3f}, com 35.000: {ldp.dsr(x, 35000):.3f} | queda maxima R$ {ldp.queda_maxima(x) * 1e5:.0f}")
    v = 1.0 / (len(j) - 1)
    print(f"  o maior Sharpe anual que o ACASO produz em {len(j)} pregoes: com 100 tentativas {ldp.sharpe_esperado_do_acaso(100, v) * 252 ** .5:.2f}, com 2.500 {ldp.sharpe_esperado_do_acaso(2500, v) * 252 ** .5:.2f}, com 35.000 {ldp.sharpe_esperado_do_acaso(35000, v) * 252 ** .5:.2f}")
    # por regime de volatilidade (faixa do dia anterior no tercil alto x resto), so para a aprovada
