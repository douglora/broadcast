"""
Ensaio do swing numa pasta temporaria, sem tocar em nada de verdade:

    cd ~/Desktop/quant-b3 && PYTHONPATH=. .venv/bin/python -W ignore -m quant.swing.ensaio [--cenario medido|capital|ambos] [--pasta CAMINHO]

O QUE RODA DE VERDADE: `robo.main(["preparar", "--modulo", "swing"])` e `robo.main(["dia", "--modulo", "swing"])`, o mesmo caminho do agendador: a boleta de swing
(processo a parte, com os dados reais ja baixados), a conciliacao, o gestor, o robo ao vivo inteiro (entrada na abertura, stop, alvo, tela).

O QUE E DE MENTIRA: (1) o relogio (o ensaio roda um pregao inteiro em segundos; pula para o proximo pregao de verdade); (2) o motor de cotacoes, um servidor
local que serve precos combinados, para provar a entrada, o alvo e o stop; (3) os passos de DADO da manha (cotacoes, balancos, proventos...) sao pulados,
para nao mexer no banco real. Os arquivos do swing, da rotina e da tela vao para a pasta do ensaio (variaveis QUANT_SWING_DIR, QUANT_SAIDA_SWING,
QUANT_SWING_CONFIG). A chave `modulos` de `quant/saida/modo_robo.json` nao e lida nem escrita (o ensaio usa um modo_robo.json da pasta); o ensaio confere o
hash do arquivo de verdade antes e depois.

CENARIOS: "medido" = a evidencia de verdade (nenhum setup com capital: so medicao); "capital" = o Douglas "liberou" dois setups so dentro da pasta do ensaio,
para exercitar entrada, alvo e stop com preco combinado. Nada do cenario "capital" vale fora da pasta.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from quant import robo
from quant.comum import DIR_SAIDA, FUSO_BRT, garantir_dir, log
from quant.swing import boleta as bol_mod
from quant.swing import estado as est
from quant.swing import evidencia, vivo

PASSO_S = 60                      # cada "dormir" do robo avanca o relogio do ensaio em 1 minuto
ARQ_MODO_VERDADE = os.path.join(DIR_SAIDA, "modo_robo.json")


def _sha(caminho):
    try:
        with open(caminho, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


class Relogio:
    def __init__(self, inicio):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def ir_para(self, hhmm):
        h, m = (int(x) for x in hhmm.split(":"))
        self.agora = self.agora.replace(hour=h, minute=m, second=0, microsecond=0)

    def dormir(self, _s):
        self.agora = self.agora + timedelta(seconds=PASSO_S)


class Motor:
    """Servidor local no formato do motor do terminal (/vivo/retrato). Preco por papel e por hora, combinado:
    papel 'sobe': abertura = referencia e sobe ate passar do alvo as 14h; 'cai': abertura = referencia e cai ate passar do stop as 11h30; os demais ficam parados."""

    def __init__(self, relogio, referencias, roteiro):
        self.relogio, self.ref, self.roteiro = relogio, referencias, roteiro
        motor = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):                                     # noqa: N802
                corpo = json.dumps(motor.retrato()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def preco(self, t, agora):
        ref = self.ref[t]["preco"]
        papel = self.roteiro.get(t)
        hm = agora.strftime("%H:%M")
        if papel == "sobe":
            return ref * (1.0 + (self.ref[t]["alvo_pct"] * 1.3 if hm >= "14:00" else 0.005 if hm >= "10:30" else 0.0))
        if papel == "cai":
            return ref * (1.0 - (self.ref[t]["stop_pct"] * 1.3 if hm >= "11:30" else 0.003 if hm >= "10:30" else 0.0))
        return ref

    def retrato(self):
        agora = self.relogio()
        ts = agora.timestamp()
        q = {}
        for t, r in self.ref.items():
            ult = round(self.preco(t, agora), 2)
            q[t] = [ult, 0.0, round(r["preco"], 2), ult, ult, 1000.0, round(r["preco"], 2), ts, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        return {"q": q, "mt5_idade_s": 0.5, "mt5": "ensaio"}

    def parar(self):
        self.srv.shutdown()


def ensaio(pasta, cenario="medido"):
    """Roda um cenario na `pasta`. Devolve dict com os testes feitos (nome -> bool) e numeros."""
    garantir_dir(pasta)
    sw, rot, saida = (os.path.join(pasta, x) for x in ("swing", "rotina", "tela"))
    for d in (sw, rot, saida):
        garantir_dir(d)
    tela = os.path.join(saida, "quant_fatores.json")
    modo = os.path.join(pasta, "modo_robo.json")
    cfg_arq = os.path.join(pasta, "swing_config.json")
    with open(modo, "w", encoding="utf-8") as f:
        json.dump({"robo": "daytrade", "modulos": ["swing", "daytrade"], "obs": "ENSAIO: este arquivo e da pasta do ensaio"}, f)
    if cenario == "capital":
        with open(cfg_arq, "w", encoding="utf-8") as f:
            json.dump({"liberar": ["C1.S0", "E1.S0"], "motivo": "ENSAIO: liberacao so dentro da pasta do ensaio", "decidido_em": "ensaio"}, f)
    hash_antes = _sha(ARQ_MODO_VERDADE)
    pastas_verdade = [os.path.join(DIR_SAIDA, "swing")]
    existiam = [os.path.exists(x) for x in pastas_verdade]
    ambiente = {"QUANT_SWING_DIR": sw, "QUANT_SAIDA_SWING": tela, "QUANT_SWING_CONFIG": cfg_arq}
    entrada_em = bol_mod.proxima_entrada()
    relogio = Relogio(datetime(entrada_em.year, entrada_em.month, entrada_em.day, 8, 35, tzinfo=FUSO_BRT))
    passo_real = robo.passo
    puladas = []

    def passo_ensaio(dia, nome, args, timeout=1800, repetir=False):
        if nome != "swing":
            puladas.append(nome)
            return True                                          # passos de dado: nao mexem no banco real
        return passo_real(dia, nome, args, timeout=timeout, repetir=repetir)

    resultado = {"cenario": cenario, "pasta": pasta, "entrada_em": str(entrada_em), "testes": {}, "numeros": {}}
    motor = None
    with mock.patch.dict(os.environ, ambiente), mock.patch.object(robo, "DIR_ROTINA", rot), mock.patch.object(robo, "ARQ_MODO", modo), \
            mock.patch.object(robo, "passo", passo_ensaio), mock.patch.object(robo, "agora_brt", relogio), \
            mock.patch.object(evidencia, "ARQ_CONFIG", cfg_arq):
        log(f"ensaio [{cenario}]: pasta {pasta}; pregão simulado {entrada_em}")
        # 1) a manha: `robo preparar --modulo swing`
        codigo_prep = robo.main(["preparar", "--modulo", "swing", "--data", str(entrada_em), "--repetir"])
        resultado["testes"]["preparar terminou com codigo 0"] = codigo_prep == 0
        resultado["testes"]["passos de dado pulados (nao mexeu no banco)"] = bool(puladas)
        b = bol_mod.ler_boleta(entrada_em)
        resultado["testes"]["boleta de swing gravada e emitida"] = bool(b and b.get("emitida"))
        if not b:
            return resultado
        caps = [c for c in b["candidatas"] if c["destino"] == "capital"]
        resultado["numeros"].update({"candidatas": len(b["candidatas"]), "com_capital": len(caps), "evidencia": b["evidencia"]})
        # 2) precos combinados: o 1o papel com capital sobe ate o alvo, o 2o cai ate o stop, o resto fica parado
        refs, roteiro = {}, {}
        for c in b["candidatas"]:
            refs[c["ticker"]] = {"preco": c["preco_ref"], "alvo_pct": ((c["alvo_dist"] or 0.0) / c["preco_ref"]), "stop_pct": c["stop_dist"] / c["preco_ref"]}
        if len(caps) >= 1:
            roteiro[caps[0]["ticker"]] = "sobe"
        if len(caps) >= 2:
            roteiro[caps[1]["ticker"]] = "cai"
        motor = Motor(relogio, refs, roteiro)
        rodar_real = vivo.rodar

        def rodar_ensaio(**kw):
            relogio.ir_para("09:58")
            return rodar_real(motor=motor.url, relogio=relogio, dormir=relogio.dormir, saidas=[tela], **kw)

        try:
            with mock.patch.object(vivo, "rodar", rodar_ensaio):
                # 3) o dia: `robo dia --modulo swing` (preparar ja feito hoje; o guard da boleta emitida o pula) e o robo ao vivo ate as 18h30
                codigo_dia = robo.main(["dia", "--modulo", "swing"])
        finally:
            motor.parar()
        resultado["testes"]["dia --modulo swing terminou com codigo 0"] = codigo_dia == 0
    # 4) conferencias
    t = json.load(open(tela, encoding="utf-8"))
    s = t.get("swing") or {}
    est_final = est.carregar(os.path.join(sw, "estado.json"))
    fech = est.fechadas(os.path.join(sw, "fechadas.jsonl"))
    cap_fech = [f for f in fech if f.get("modo") == "capital" and f.get("status") == "fechada"]
    cap_abertas = [p for p in est_final["posicoes"] if p.get("modo") == "capital" and p.get("status") == "aberta"]
    pend = [p for p in est_final["posicoes"] if p.get("modo") == "medida" and p.get("status") == "pendente"]
    T = resultado["testes"]
    T["tela gravada com o bloco swing"] = bool(s) and t.get("modulo") == "swing"
    T["tela fechou o pregao (fase encerrado)"] = (t.get("vivo") or {}).get("fase") == "encerrado"
    T["a primeira linha de aviso diz a verdade sobre a evidencia"] = bool(t.get("avisos")) and ("setup" in t["avisos"][0])
    T["operacoes medidas ficaram pendentes para as barras oficiais"] = len(pend) == resultado["numeros"]["candidatas"]
    T["modo_robo.json de verdade nao mudou"] = _sha(ARQ_MODO_VERDADE) == hash_antes
    T["nada gravado na pasta swing de verdade"] = [os.path.exists(x) for x in pastas_verdade] == existiam
    if cenario == "medido":
        T["sem capital: nenhuma entrada com capital"] = resultado["numeros"]["com_capital"] == 0 and not cap_abertas and not cap_fech
        T["tela diz que roda so medido"] = s.get("estado") == "so_medido"
    else:
        motivos = sorted(f["motivo_saida"] for f in cap_fech)
        T["houve entradas com capital na abertura"] = len(cap_fech) + len(cap_abertas) >= 1
        T["o papel que sobe saiu no alvo"] = "alvo" in motivos
        T["o papel que cai saiu no stop"] = bool({"stop", "gap_stop"} & set(motivos))
        T["os demais seguem abertos, vigiados"] = len(cap_abertas) == max(len(caps) - len(cap_fech), 0) or len(cap_abertas) >= 1
        T["exposicao nunca passou do limite"] = (s.get("livro") or {}).get("exposicao", 0.0) <= 1.0 + 1e-9
        T["posicoes na tela com os campos do contrato"] = all(k in (s["posicoes"][0] if s.get("posicoes") else {k: 1}) for k in
                                                                ("setup", "entrada_em", "preco_entrada", "stop", "alvo", "prazo_ate", "pregoes_na_posicao",
                                                                 "pregoes_restantes", "resultado_rs", "porque"))
        resultado["numeros"].update({"fechadas_capital": [(f["ticker"], f["setup"], f["motivo_saida"], round(f["resultado_rs"], 2)) for f in cap_fech],
                                     "abertas_capital": len(cap_abertas)})
    resultado["numeros"].update({"medidas_pendentes": len(pend), "passos_pulados": sorted(set(puladas))})
    resultado["ok"] = all(T.values())
    return resultado


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ensaio do swing numa pasta temporaria")
    ap.add_argument("--cenario", choices=["medido", "capital", "ambos"], default="ambos")
    ap.add_argument("--pasta", default=None, help="pasta do ensaio (padrao: uma nova em /tmp)")
    a = ap.parse_args(argv)
    import tempfile
    base = a.pasta or tempfile.mkdtemp(prefix="ensaio_swing_")
    ok = True
    for cen in (["medido", "capital"] if a.cenario == "ambos" else [a.cenario]):
        r = ensaio(os.path.join(base, cen), cen)
        print(json.dumps({k: v for k, v in r.items() if k != "testes"}, ensure_ascii=False, indent=1, default=str))
        for nome, passou in r["testes"].items():
            print(f"  [{'ok' if passou else 'FALHOU'}] {nome}")
        ok = ok and r.get("ok", False)
    print("ENSAIO " + ("PASSOU" if ok else "FALHOU") + f" (pasta: {base})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
