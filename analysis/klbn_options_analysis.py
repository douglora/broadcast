"""
KLBN11 — Análise de opções (Black-Scholes, IV, gregas, assimetrias e comparação de estratégias)
Valuation date: 30/06/2026  |  Vencimento alvo: 17/07/2026 (3a sexta) = 12 dias úteis
Foco: avaliar a venda da PUT KLBNS161 (strike 16,16 / prêmio 0,07) e alternativas.

Dados de mercado (coletados via pesquisa — egress de dados bloqueado nesta sessão):
- Spot KLBN11 ............ R$ 16,80 (informado pelo usuário; mercado ~16,8-17,0)
- SELIC (risk-free) ...... 14,25% a.a. (Copom jun/2026)
- Range 52 semanas ....... R$ 16,01 - 21,25
- Lateralização .......... suporte ~16,97 (perdido) / próx. 16,20-16,50 ; resist. ~19,42
- DY ..................... ~8,4-9,0% a.a.  | sem ex-dividendo até 17/jul
"""
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

# ----------------------------- Parâmetros base -----------------------------
S      = 16.80          # spot
r_nom  = 0.1425         # SELIC nominal a.a. (base 252)
r      = np.log(1 + r_nom)   # taxa contínua equivalente
du     = 12             # dias úteis até o vencimento (30/jun -> 17/jul, excl. feriado 09/jul SP)
T      = du / 252.0     # tempo em anos (base 252, convenção B3)
q      = 0.0            # sem dividendo até o vencimento

print("="*78)
print(f"S={S:.2f}  r_nom={r_nom:.4f}  r_cont={r:.5f}  T={T:.5f} ano ({du} d.u.)  q={q}")
print("="*78)

# ----------------------------- Black-Scholes -------------------------------
def d1d2(S, K, T, r, sig, q=0.0):
    d1 = (np.log(S/K) + (r - q + 0.5*sig**2)*T) / (sig*np.sqrt(T))
    d2 = d1 - sig*np.sqrt(T)
    return d1, d2

def bs_price(S, K, T, r, sig, kind, q=0.0):
    d1, d2 = d1d2(S, K, T, r, sig, q)
    if kind == 'put':
        return K*np.exp(-r*T)*norm.cdf(-d2) - S*np.exp(-q*T)*norm.cdf(-d1)
    return S*np.exp(-q*T)*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)

def greeks(S, K, T, r, sig, kind, q=0.0):
    d1, d2 = d1d2(S, K, T, r, sig, q)
    pdf = norm.pdf(d1)
    if kind == 'put':
        delta = -np.exp(-q*T)*norm.cdf(-d1)
        theta = (-S*pdf*sig*np.exp(-q*T)/(2*np.sqrt(T))
                 + r*K*np.exp(-r*T)*norm.cdf(-d2) - q*S*np.exp(-q*T)*norm.cdf(-d1))
    else:
        delta = np.exp(-q*T)*norm.cdf(d1)
        theta = (-S*pdf*sig*np.exp(-q*T)/(2*np.sqrt(T))
                 - r*K*np.exp(-r*T)*norm.cdf(d2) + q*S*np.exp(-q*T)*norm.cdf(d1))
    gamma = np.exp(-q*T)*pdf/(S*sig*np.sqrt(T))
    vega  = S*np.exp(-q*T)*pdf*np.sqrt(T)
    return dict(delta=delta, gamma=gamma, theta_year=theta, theta_day=theta/252,
                vega_1pct=vega/100, prob_ITM=norm.cdf(-d2) if kind=='put' else norm.cdf(d2))

def implied_vol(price, S, K, T, r, kind, q=0.0):
    try:
        return brentq(lambda s: bs_price(S,K,T,r,s,kind,q)-price, 1e-4, 5.0, maxiter=200)
    except ValueError:
        return np.nan

# ----------------------------- A PUT proposta ------------------------------
K_put   = 16.16
premio  = 0.07
print("\n### 1) PUT KLBNS161  (strike 16,16 | prêmio 0,07) ###")
iv = implied_vol(premio, S, K_put, T, r, 'put')
print(f"Vol IMPLÍCITA do prêmio 0,07 .......... {iv*100:.1f}% a.a.")
for sig in [0.16,0.18,0.20,0.215,0.24,0.26,0.28]:
    fv = bs_price(S, K_put, T, r, sig, 'put')
    tag = "  <-- IV do prêmio" if abs(sig-0.215)<1e-9 else ""
    print(f"  Fair value @ vol {sig*100:4.1f}% = R$ {fv:0.3f}{tag}")
g = greeks(S, K_put, T, r, iv, 'put')
print(f"Delta={g['delta']:.3f}  Gamma={g['gamma']:.3f}  "
      f"Theta/dia=+{-g['theta_day']:.4f} (a favor do vendedor)  Vega(1%)={g['vega_1pct']:.4f}")
print(f"Prob. terminar ITM (assignment) ....... {g['prob_ITM']*100:.1f}%")
print(f"Prob. expirar sem valor (lucro máx) ... {(1-g['prob_ITM'])*100:.1f}%")
print(f"Breakeven (strike - prêmio) ........... R$ {K_put-premio:.2f}  "
      f"({(K_put-premio)/S-1:+.2%} vs spot)")

# Distância em desvios-padrão até o strike
move_1sd = S*iv*np.sqrt(T)
print(f"Mov. 1 desvio-padrão até 17/jul ....... R$ {move_1sd:.2f} ({move_1sd/S:.2%})")
print(f"Strike está a ........................ {(S-K_put)/move_1sd:.2f} desvios abaixo do spot")

# ----------------------------- EV sob lognormal ----------------------------
def ev_short_put(K, prem, S, T, r, sig, n=400000, seed=7):
    rng = np.random.default_rng(seed)
    ST = S*np.exp((r-0.5*sig**2)*T + sig*np.sqrt(T)*rng.standard_normal(n))
    payoff = prem - np.maximum(K-ST, 0.0)          # P&L por ação no vencimento
    return payoff.mean(), payoff.std(), np.mean(payoff>0), ST

print("\n### 2) Valor esperado da venda da PUT 16,16 (lognormal risk-neutral e real) ###")
for label, drift_sig in [("risk-neutral (r)", iv)]:
    ev, sd, pwin, _ = ev_short_put(K_put, premio, S, T, r, iv)
    print(f"  [{label}] EV/ação=R$ {ev:+.4f}  desvio=R$ {sd:.3f}  P(lucro)={pwin:.1%}")
# cenário 'mundo real' com vol realizada menor (lateralização) e drift ~0
for hv in [0.18, 0.20]:
    rng = np.random.default_rng(11)
    ST = S*np.exp((0.0-0.5*hv**2)*T + hv*np.sqrt(T)*rng.standard_normal(400000))
    pl = premio - np.maximum(K_put-ST,0.0)
    print(f"  [real, drift 0, HV {hv*100:.0f}%] EV/ação=R$ {pl.mean():+.4f}  P(lucro)={np.mean(pl>0):.1%}")

# ----------------------------- Rendimento e custos -------------------------
print("\n### 3) Rendimento da venda coberta de caixa (CSP) e drag de custos ###")
capital_margem = K_put             # caixa reservado p/ assignment (R$ por ação)
ret_periodo = premio/capital_margem
print(f"Retorno do período (12 d.u.) .......... {ret_periodo:.2%}")
print(f"Anualizado (composto, 252/12 ciclos) .. {(1+ret_periodo)**(252/du)-1:.1%}  "
      f"(otimista: assume repetir sem nunca ser exercido)")
# custos: emolumentos B3 (~0,037% opções) + corretagem + IR 15% sobre ganho
ir = 0.15
liq_apos_ir = premio*(1-ir)
print(f"Prêmio líquido após IR 15% ............ R$ {liq_apos_ir:.4f} (sobre 0,07)")
print(f"Obs.: corretagem fixa por boleta costuma consumir boa parte de 0,07/ação.")

# ----------------------------- Estratégias comparadas ----------------------
# Preço de mercado estimado das demais opções via IV ~ 0,215 (skew leve ignorado)
SIG = iv
def px(K, kind): return bs_price(S, K, T, r, SIG, kind)

print("\n### 4) Estrutura de prêmios estimados @ IV {:.1f}% ###".format(SIG*100))
strikes_put  = [15.66, 16.00, 16.16, 16.50, 16.80]
strikes_call = [16.80, 17.00, 17.50, 18.00, 18.50]
print(" PUTs:  " + "  ".join(f"{k:.2f}=R${px(k,'put'):.3f}" for k in strikes_put))
print(" CALLs: " + "  ".join(f"{k:.2f}=R${px(k,'call'):.3f}" for k in strikes_call))

def metrics(name, breakeven, maxgain, maxloss, pop, capital):
    rr = (maxgain/abs(maxloss)) if maxloss else float('inf')
    print(f"\n{name}")
    print(f"   Breakeven={breakeven}  Ganho_máx=R${maxgain:.3f}  Perda_máx=R${maxloss:.3f}")
    print(f"   Reward:Risk={rr:.3f}  P(lucro)~{pop:.0%}  Retorno s/ capital={maxgain/capital:.2%} (12du)")

print("\n### 5) Comparação de estratégias (por ação / por unit) ###")
# (a) PUT 16,16 nua/coberta de caixa
metrics("(a) Venda PUT 16,16 @0,07 [a proposta]", f"{K_put-premio:.2f}",
        premio, -(K_put-premio), 1-greeks(S,K_put,T,r,SIG,'put')['prob_ITM'], K_put)
# (b) CSP strike 16,00 (mais OTM ainda) — referência
p16 = px(16.00,'put'); metrics("(b) Venda PUT 16,00 (mais OTM)", f"{16.00-p16:.2f}",
        p16, -(16.00-p16), 1-greeks(S,16.00,T,r,SIG,'put')['prob_ITM'], 16.00)
# (c) CSP strike 16,50 (mais perto do dinheiro, prêmio gordo)
p1650 = px(16.50,'put'); metrics("(c) Venda PUT 16,50 (perto do dinheiro)", f"{16.50-p1650:.2f}",
        p1650, -(16.50-p1650), 1-greeks(S,16.50,T,r,SIG,'put')['prob_ITM'], 16.50)
# (d) Bull put spread 16,50 / 15,66 (vende 16,50, compra 15,66)
short_p, long_p = px(16.50,'put'), px(15.66,'put'); credit = short_p-long_p
width = 16.50-15.66
metrics("(d) Bull Put Spread 16,50/15,66 (risco definido)", f"{16.50-credit:.2f}",
        credit, -(width-credit), 1-greeks(S,16.50,T,r,SIG,'put')['prob_ITM'], width-credit)
# (e) Short Strangle 16,00 put + 17,50 call (monetiza lateralização)
sp, sc = px(16.00,'put'), px(17.50,'call'); cr = sp+sc
metrics("(e) Short Strangle 16,00P/17,50C (vende lateralização)", f"{16.00-cr:.2f} / {17.50+cr:.2f}",
        cr, float('-inf'), 1.0 - greeks(S,16.00,T,r,SIG,'put')['prob_ITM'] - greeks(S,17.50,T,r,SIG,'call')['prob_ITM'], 16.00)
# (f) Iron Condor 15,66/16,00 - 17,50/18,00 (risco definido)
sp, lp = px(16.00,'put'), px(15.66,'put')
sc2, lc = px(17.50,'call'), px(18.00,'call')
cr_ic = (sp-lp)+(sc2-lc); w_ic = max(16.00-15.66, 18.00-17.50)
metrics("(f) Iron Condor 15,66/16,00//17,50/18,00 (risco definido)", f"{16.00-cr_ic:.2f} / {17.50+cr_ic:.2f}",
        cr_ic, -(w_ic-cr_ic), 1.0 - greeks(S,16.00,T,r,SIG,'put')['prob_ITM'] - greeks(S,17.50,T,r,SIG,'call')['prob_ITM'], w_ic-cr_ic)
# (g) Covered call: possui KLBN11 + vende call 17,50
cc = px(17.50,'call')
print(f"\n(g) Covered Call: possui unit + vende CALL 17,50 @R${cc:.3f}")
print(f"   Renda extra no período={cc/S:.2%}  | teto de ganho até 17,50 (+{17.50/S-1:.1%}) + prêmio")
print(f"   Combina com DY ~8,4-9% a.a.; em mercado lateral, melhora o carrego.")

print("\nFIM.")
