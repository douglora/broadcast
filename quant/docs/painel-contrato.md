# Contrato do `painel.json` (Fase 3)

`quant/rodar_diario.py` grava **um** arquivo, `quant/saida/painel.json`, e o terminal só lê esse
arquivo. Nenhum endpoint do `app.py` importa pandas, e nenhum cálculo acontece dentro de uma
requisição HTTP. Este documento é o contrato entre os dois lados.

Regras que valem para o arquivo inteiro:

- **Só tipos JSON nativos.** Nada de `NaN`, `Infinity`, `numpy.float64` ou `pandas.Timestamp` —
  `jsonify` não serializa nenhum deles, e `NaN` produz JSON inválido que quebra o `await r.json()`
  do front. Valor ausente é `null`.
- **Datas como texto ISO** (`"2026-09-08"`), carimbos com fuso (`"2026-09-08T21:05:00-03:00"`).
- **Percentuais como fração** (`0.0123` = 1,23%). Quem formata é o front.
- **Dinheiro em reais, float.**
- O arquivo é dado pessoal: fica em `quant/saida/` (ignorado pelo git) e **nunca** entra no
  snapshot estático publicado no GitHub Pages.

```json
{
  "gerado_em": "2026-09-08T21:05:00-03:00",
  "modo": "paper",
  "origem": "sintetico",
  "capital": 100000.0,

  "gate_fase1": {
    "passou": false,
    "detalhe": "nao rodado: falta o COTAHIST real"
  },

  "frescor": {
    "cotahist": {"data": "2026-09-05", "dias_atras": 3, "ok": false},
    "bdi":      {"data": "2026-09-05", "dias_atras": 3, "ok": false},
    "sinais":   {"data": "2026-08-29", "dias_atras": 8, "ok": true},
    "cdi":      {"data": "2026-09-05", "dias_atras": 3, "ok": true}
  },

  "modo_seguro": {
    "ativo": true,
    "motivos": ["COTAHIST do pregao de hoje ausente", "gate da fase 1 nao aprovado"]
  },

  "carteira": {
    "patrimonio": 101234.56,
    "caixa": 26000.0,
    "valor_posicoes": 75234.56,
    "n_posicoes": 22,
    "contratos_hedge": 1,
    "exposicao": 0.743,
    "caixa_minimo": 25000.0,
    "violacoes": [],
    "posicoes": [
      {"ticker": "ABCD3", "setor": "energia", "qtd": 300, "preco_medio": 20.10,
       "preco": 21.00, "valor": 6300.0, "peso": 0.062, "peso_alvo": 0.055,
       "meses": 3, "rank": 4, "pnl": 270.0, "pnl_pct": 0.0448}
    ]
  },

  "boleta": {
    "data": "2026-09-08",
    "id": "20260908",
    "emitida": false,
    "motivo_bloqueio": ["COTAHIST do pregao de hoje ausente"],
    "custo_total": 145.0,
    "ordens": [
      {"ticker": "ABCD3", "lado": "C", "qtd": 300, "preco_limite": 20.55,
       "validade": "dia", "motivo": "entrada", "custo": 12.30,
       "fatia": "1/2", "adtv": 5200000.0, "fracionario": false}
    ]
  },

  "paper": {
    "origem": "ensaio",
    "sessoes": 110,
    "primeira": "2026-04-01",
    "ultima": "2026-09-08",
    "boletas_emitidas": 110,
    "taxa_execucao": 1.0,
    "slippage_bps": -58.4,
    "slippage_vwap_bps": -55.1,
    "erros": 0,
    "meses_sem_erro": null,
    "rolls": 3,
    "passou": false,
    "reprovados": ["meses_sem_erro"],
    "avisos": ["ENSAIO sobre dado sintetico: isto nao e a fase 4"],
    "criterios": [
      {"criterio": "execucao", "valor": 1.0, "gatilho": 0.6,
       "formato": "pct", "status": "ok"}
    ]
  },

  "fiscal": {
    "mes": "2026-09",
    "vendas_acoes_mes": 12000.0,
    "isencao_restante": 8000.0,
    "isento": true,
    "lucro_comum": 1500.0,
    "lucro_day_trade": 0.0,
    "prejuizo_acumulado_comum": 0.0,
    "prejuizo_acumulado_day_trade": 0.0,
    "irrf_retido": 0.60,
    "darf": 0.0,
    "darf_vence": "2026-10-30",
    "darf_acumulado": 0.0,
    "aviso": "calculo de apoio; conferir com contador antes de recolher"
  },

  "desempenho": {
    "desde": "2026-01-02",
    "retorno": 0.0123,
    "cdi": 0.0111,
    "excesso": 0.0012,
    "ibov": 0.0201,
    "vol": 0.14,
    "mdd": 0.031,
    "giro_mensal": 0.18,
    "custo_aa": 0.024,
    "serie": [{"data": "2026-01-02", "carteira": 1.0, "cdi": 1.0, "ibov": 1.0}]
  },

  "kill": [
    {"criterio": "drawdown", "rotulo": "Drawdown do pico",
     "valor": 0.031, "gatilho": 0.20, "status": "ok", "formato": "pct",
     "descricao": "20% reduz o gross pela metade; 30% encerra"}
  ]
}
```

## Campos que o front pode contar

- `modo_seguro.ativo` **manda na tela**: quando é `true`, a aba Boleta mostra os motivos em
  vermelho e não mostra ordem nenhuma, porque não existe ordem.
- `origem` é `"real"` ou `"sintetico"`. Em `"sintetico"`, o cabeçalho do painel diz, com todas as
  letras, que nenhum número ali é resultado de estratégia.
- `gate_fase1.passou` false ⇒ faixa de aviso no topo, sempre.
- `kill[].status` ∈ `"ok"` | `"atencao"` | `"disparado"`. Verde, amarelo, vermelho.
- `kill[].formato` ∈ `"pct"` | `"x"` | `"num"` diz **como formatar** aquele critério. Não é
  decoração: sem ele o front formata tudo como porcentagem e um universo de 33 nomes aparece
  como "3.300%" — foi o que aconteceu na primeira versão do painel.
- `paper.passou` só é `true` quando **todos** os critérios passam **e** `paper.origem` é
  `"real"`. Um ensaio sobre o mercado sintético nunca "passa" na Fase 4, por construção: o
  ensaio prova que o laço fecha, e nada além disso.
- `paper.criterios[].formato` segue a mesma regra de `kill[].formato`, com um valor a mais:
  `pct` | `x` | `num` | `bool` (`bool` vira "sim"/"não" — "parâmetros intocados: 1" não
  quer dizer nada para quem lê a tela).
- `paper.meses_sem_erro` vem `null` enquanto nenhum mês foi **assinado** como conferido.
  Diário de erros vazio não é prova de mês limpo — pode ser mês em que ninguém anotou.
- Toda lista pode vir vazia. Todo campo numérico pode vir `null`. O front nunca deve assumir
  presença: o arquivo pode ter sido gerado antes de existir carteira, fill ou histórico.

## Ausência do arquivo

Se `quant/saida/painel.json` não existe, o endpoint devolve **503** com
`{"error": "painel nao gerado", "comando": "python3 -m quant.rodar_diario --paper"}`, e o card do
terminal mostra esse comando. Isso não é erro: é o estado normal de quem ainda não rodou nada.
