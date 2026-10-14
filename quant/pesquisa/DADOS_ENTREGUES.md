# Dados entregues pelo terminal ao robo: o estado do mundo em tempo real (12/10/2026)

Escrito pela frente "dados em tempo real" do terminal. O robo NAO foi alterado: qualquer uso disto entra "so medindo" e depende do "pode" do Douglas.
Pedidos de dado desta sessao vao em `DADOS_PEDIDOS.md` (ainda nao existia em 12/10/2026 as 17h30).

## Onde e com que frequencia

| Arquivo (em `~/Desktop/terminal-artefato/`) | Refeito | O que e |
|---|---|---|
| `cache/out/tempo_real/estado.json` | a cada 60 s (processo `coletor/tempo_real.py --laco`, launchd `br.autopilot.tempo-real`) | o estado inteiro, ate 20 KB |
| `cache/out/tempo_real/agenda.json` | a cada 60 s | eventos dos proximos 45 dias com consenso, efetivo, surpresa e `faltam_s` |
| `cache/out/tempo_real/surpresas.json` | quando ha surpresa nova | livro por indicador: `[dia, consenso, efetivo, surpresa, fonte]` |
| `cache/out/tempo_real_estado.json` | a cada 60 s | `{gerado, ok, cobertura, fontes}` (saude) |

Tambem pelo motor local (`GET http://127.0.0.1:8930/vivo/tempo_real`, serve o mesmo arquivo; exige o motor reiniciado depois de 12/10/2026) e pelas
ferramentas MCP `estado(bloco)`, `agenda(dias, pais, minimo)` e `surpresas(desde, indicador)` do servidor `autopilot` (`ferramentas/mcp_vivo.py`).

Gravacao atomica (tmp + rename): nunca se le um arquivo pela metade. Idade do estado: `gerado_epoch` (epoch) e `gerado` (ISO -03:00).
Estado com mais de 5 minutos quer dizer processo parado: trate como "sem dado".

## Regras de leitura (as mesmas do pacote `quant/terminal/`)

1. Todo campo e um objeto `{valor, fonte, hora, atraso_s, ...}`. `valor: null` vem com `motivo`. **Nunca troque null por zero.**
2. `atraso_s` e medido (agora menos a hora do dado). `tempo_real: true` so em fonte de tempo real (MetaTrader da XP, Yahoo em fluxo, Coinbase).
   Futuros dos EUA, Brent e ouro vem do Yahoo em lote com 10 a 15 min declarados (`fonte` diz). Fluxo estrangeiro e D+2. Posicao em aberto e do
   fechamento anterior. Volatilidade de fechamento e do ultimo pregao COMPLETO da B3.
3. Nada e estimado. Percentil de 1 ano so existe onde ha 252 fechamentos em `cache/out/hist`.
4. Nenhum campo foi testado como sinal: hipotese escrita antes, descoberta, validacao, prova viva (METODO.md).

## Esquema do `estado.json` (v1)

```
{
  "v": 1, "gerado": "2026-10-12T17:06:59-03:00", "gerado_epoch": 1791835619, "ciclo_s": 60, "ok": true, "tamanho_kb": 18.9,
  "como_ler": "cada campo traz valor, fonte, hora (Brasilia) e atraso_s; valor null vem com motivo; nada e estimado",
  "agenda": {
    "hora": ISO da agenda do terminal, "atraso_s": int, "fonte": str,
    "hoje":   [evento...],                      # ate 24, compactos (campos nulos omitidos)
    "semana": [evento...],                      # proximos 7 dias, importancia 2+, ate 40
    "proximos": [{"id","evento","pais","indicador","quando","hora","faltam_s","importancia","consenso","consenso_fonte","anterior","unidade","origem"}],  # 3
    "ultimo_que_saiu": {"id","evento","pais","indicador","quando","consenso","efetivo","surpresa","surpresa_dp","surpresa_hist_n","surpresa_dp_motivo","unidade","fonte"} | null,
    "consenso": {"da_agenda": n, "do_feed_semanal": n, "eventos_so_do_feed": n, "nota": str},
    "surpresa_dp_como": str
  },
  "regime": {
    "itens": {"VIX": {"valor","fonte","hora","atraso_s","nome","var_dia_pct","fech_ant","max_dia","min_dia","tempo_real","pctl_1a","faixa_1a":[min,max],"pctl_1a_fonte"},
              "DXY":..., "ESFUT":..., "NQFUT":..., "BRENT":..., "OURO":..., "BTCUSD":..., "UST10Y": {... "var_dia_bps" ...},
              "USDBRL":..., "DOLFUT":..., "WDOFUT":..., "IBOV":..., "WINFUT":...},
    "di": {"vertices": [{"s":"DI1F27","rotulo":"Jan/27","taxa","var_dia_bps","hora","fonte","tempo_real"}...], "inclinacao": {"entre":[s1,s2],"bps"}, "fonte","hora"},
    "hora": ISO do retrato do motor, "atraso_s": int, "fonte": str, "nota": str
  },
  "fluxo": {
    "estrangeiro_b3": {"valor": saldo do mes em R$, "saldo_dia_rs", "saldo_mes_rs": {tipo: R$}, "pregao", "atraso_pregoes": 2, "fonte","hora","atraso_s","unidade"},
    "posicao_por_participante": {"valor": null, "motivo": "...a B3 tirou do ar em 07/04/2025...", "fonte"},
    "posicao_em_aberto_total": {"valor": {"WIN"|"WDO"|"DOL"|"IND": {"contratos_em_aberto","variacao_dia","principal","ajuste_principal"}}, "pregao","fonte","hora","atraso_s","nota"},
    "aluguel": {"valor": {"total_rs","papeis_com_saldo","var_total_d1_pct","por_papel": {"BOVA11"|"PETR4"|"VALE3": {"taxa_pct_aa","saldo_rs","var_5d_pct","pct_float","dias_para_cobrir"}}}, "pregao","fonte","hora","atraso_s"},
    "hora","fonte"
  },
  "noticias": {"janela_min": 30, "n_na_janela", "n_3h", "itens": [{"hora","ts","veiculo","titulo","link","marcas":[...],"canal","peso"}], "marcas_na_janela": {marca: n},
               "mais_recentes": [...] (so quando a janela esta vazia), "motivo", "hora","atraso_s","fonte","marcas_como"},
  "vol_implicita": {"itens": {"BOVA11"|"PETR4"|"VALE3": {"fechamento": {"valor" % a.a.,"pregao","venc_ref","du","spot_fechamento","de","fonte","hora","atraso_s","aviso"?},
                                                        "intradia": {"valor" % a.a.,"series":[...],"spot","spot_hora","dif_pp_contra_fechamento","fonte","hora","atraso_s"} | {"valor": null,"motivo","series_pedidas"},
                                                        "qual": "intradia"|"fechamento"|null}}, "hora","fonte","nota"},
  "saude": {"ok": bool, "blocos": {bloco: {"hora","idade_s","ok","limite_s","motivo"?}}, "motor": {"ok","pregao_b3","hora","mt5": {"ok","estado","idade_ultimo_tique_s","atraso_robo_motor_ms_p50","oscilacao_ms_p50","em_rajadas"},"fontes_fora":[...]},
            "feed_semanal": {"ok","fonte","n","data","obs","erro"?}, "avisos": [...]?, "nota"}
}
```

Evento (agenda): `{"id","evento","pais":"BR"|"US","indicador","dia","hora","quando","importancia":1..3,"periodo","unidade","anterior","consenso","consenso_fonte",
"efetivo","revisado","saiu","faltam_s","surpresa","surpresa_dp","surpresa_hist_n","surpresa_dp_motivo","fonte","origem":"agenda do terminal"|"feed semanal"}`.
`surpresa = efetivo - consenso` na unidade do evento; `surpresa_dp = surpresa / desvio-padrao das surpresas passadas do mesmo indicador` (so com 8+ pontos,
so dias anteriores: sem olhar o futuro). Indicadores dos EUA que o setup usa: `cpi_mm`, `cpi_nucleo_mm`, `payroll`, `desemprego_us`, `pedidos_seguro`,
`pce_nucleo_mm`, `pib_us`, `ppi_mm`, `varejo_us`, `ism_industria`, `ism_servicos`, `fed_funds`.

Consenso dos EUA hoje: semana corrente pelo feed publico do ForexFactory (sem efetivo), historico pelo calendario do MetaTrader DEPOIS que o Douglas rodar o
script (ver `coletor/tempo_real.LEIAME.md`, "Consenso historico"); ate la `surpresa_dp` dos EUA fica null com o motivo "historico curto".

## Exemplo de leitura em Python (so leitura; nada aqui escreve no terminal)

```python
import json, os, time
from pathlib import Path

ARQ = Path(os.environ.get("AUTOPILOT_TERMINAL", "~/Desktop/terminal-artefato")).expanduser() / "cache" / "out" / "tempo_real" / "estado.json"

def estado_do_mundo(max_idade_s=300):
    """O estado inteiro, ou None se nao existe, esta ilegivel (meio de uma regravacao) ou e velho demais."""
    try:
        e = json.loads(ARQ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(e.get("gerado_epoch") or 0) > max_idade_s:
        return None                       # processo parado: sem dado, nunca dado velho como se fosse novo
    return e

def campo(e, *caminho):
    """Valor de um campo {valor, fonte, hora, atraso_s}; None com o motivo quando nao ha dado."""
    x = e
    for k in caminho:
        x = (x or {}).get(k)
    if not isinstance(x, dict):
        return None, "campo ausente"
    return x.get("valor"), (x.get("motivo") or x.get("fonte"))

e = estado_do_mundo()
if e:
    vix, de = campo(e, "regime", "itens", "VIX")              # 15.23, 'Yahoo Finance, fluxo ao vivo'
    pctl = e["regime"]["itens"]["VIX"].get("pctl_1a")           # 15.1 (percentil de 1 ano) ou None
    prox = e["agenda"]["proximos"]                              # os 3 proximos eventos relevantes, com faltam_s (contado de gerado_epoch)
    faltam = prox[0]["faltam_s"] - (time.time() - e["gerado_epoch"]) if prox else None
    ult = e["agenda"]["ultimo_que_saiu"]                        # {'evento','efetivo','consenso','surpresa','surpresa_dp',...} ou None
    rajada = e["saude"]["motor"].get("mt5", {}).get("em_rajadas")   # True: feed do MetaTrader em rajadas (ver mt5-feed-em-rajadas)
    estrangeiro, fonte = campo(e, "fluxo", "estrangeiro_b3")   # saldo do mes em R$, com 2 pregoes de atraso (e['fluxo']['estrangeiro_b3']['pregao'])
```

Para o historico de surpresas (teste do setup do dado): `surpresas.json` -> `itens[indicador]` = lista `[dia, consenso, efetivo, surpresa, fonte]`,
em ordem de dia. Desvio-padrao populacional de `surpresa` da o denominador que o estado usa.

## O que falta (dito sem enfeite)

- Historico de consenso dos EUA: so depois de rodar o script do calendario do MetaTrader (comando no LEIAME do coletor). Sem ele, a surpresa em
  desvios-padrao dos EUA nao existe; a surpresa na unidade existe quando o feed semanal deu o consenso da semana.
- Posicao em aberto por tipo de participante (dolar e indice): a B3 tirou do ar em 04/2025; so em produto pago. Fica o total por contrato.
- Volatilidade implicita intradiaria: so com pregao aberto e o MetaTrader entregando as series pedidas; em 12/10 (feriado) ficou null com motivo.
- VIX, DXY, Brent, ouro e futuros dos EUA: 10 a 15 min de atraso (Yahoo); o `fonte` de cada um diz. Nao ha fonte gratuita melhor conferida ate agora.
