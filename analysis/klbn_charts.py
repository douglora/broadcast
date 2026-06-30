"""Gráficos: payoff/assimetria das estratégias em KLBN11 (vencimento 17/07/2026)."""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm

S, r, T = 16.80, np.log(1.1425), 12/252
SIG = 0.216
def bs(K, kind):
    d1=(np.log(S/K)+(r+0.5*SIG**2)*T)/(SIG*np.sqrt(T)); d2=d1-SIG*np.sqrt(T)
    if kind=='put': return K*np.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1)
    return S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2)

ST = np.linspace(13.5, 20.0, 700)

# Estratégias (payoff no vencimento, por ação)
prem_put   = 0.07
naked_put  = prem_put - np.maximum(16.16-ST,0)                      # (a)
# Iron Condor 15,66/16,00 - 17,50/18,00
cr_ic = (bs(16.00,'put')-bs(15.66,'put'))+(bs(17.50,'call')-bs(18.00,'call'))
ic = cr_ic - np.maximum(16.00-ST,0)+np.maximum(15.66-ST,0) \
           - np.maximum(ST-17.50,0)+np.maximum(ST-18.00,0)
# Bull put spread 16,50/15,66
cr_bps = bs(16.50,'put')-bs(15.66,'put')
bps = cr_bps - np.maximum(16.50-ST,0)+np.maximum(15.66-ST,0)
# Covered call: unit + venda call 17,50
cc = bs(17.50,'call')
covcall = (ST-S) + cc - np.maximum(ST-17.50,0)

fig, ax = plt.subplots(2,2, figsize=(15,10)); fig.suptitle(
  "KLBN11 — Spot R$16,80 • Venc. 17/07/2026 (12 d.u.) • IV≈21,6% • SELIC 14,25%",
  fontsize=14, fontweight='bold')

def style(a, title):
    a.axhline(0,color='k',lw=.8); a.axvline(S,color='gray',ls=':',lw=1)
    a.axvspan(16.20,16.97,color='orange',alpha=.10)   # zona de suporte
    a.text(16.55,a.get_ylim()[1] if False else 0,'',fontsize=8)
    a.set_xlabel("Preço KLBN11 no vencimento (R$)"); a.set_ylabel("Resultado por unit (R$)")
    a.set_title(title,fontsize=11,fontweight='bold'); a.grid(alpha=.3); a.legend(fontsize=9)

# (1) A PUT proposta — assimetria
a=ax[0,0]
a.plot(ST,naked_put,color='crimson',lw=2,label='Venda PUT 16,16 @0,07')
a.fill_between(ST,naked_put,0,where=naked_put<0,color='crimson',alpha=.15)
a.fill_between(ST,naked_put,0,where=naked_put>=0,color='green',alpha=.15)
a.axvline(16.09,color='crimson',ls='--',lw=1,label='Breakeven 16,09')
a.annotate('ganho máx +0,07',(18.5,0.07),(17.2,0.9),fontsize=9,
           arrowprops=dict(arrowstyle='->'))
a.annotate('perda cresce sem limite\n(risco ~R$16/ação)',(14.0,naked_put[ (np.abs(ST-14.0)).argmin()]),
           (15.6,-1.8),fontsize=9,color='crimson',arrowprops=dict(arrowstyle='->',color='crimson'))
style(a,"(a) A PROPOSTA: assimetria ruim — risco enorme p/ prêmio mínimo")
a.set_ylim(-2.6,1.1)

# (2) IV vs fair value (barras)
a=ax[0,1]
vols=[16,18,20,21.6,24,26,28]; fvs=[]
for v in vols:
    s=v/100; d1=(np.log(S/16.16)+(r+0.5*s**2)*T)/(s*np.sqrt(T)); d2=d1-s*np.sqrt(T)
    fvs.append(16.16*np.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1))
cols=['#888' if v!=21.6 else 'crimson' for v in vols]
a.bar([str(v) for v in vols],fvs,color=cols)
a.axhline(0.07,color='crimson',ls='--',lw=1.5,label='prêmio de mercado = 0,07')
a.set_title("(b) Preço justo da PUT 16,16 por nível de volatilidade",fontsize=11,fontweight='bold')
a.set_xlabel("Volatilidade anual (%)"); a.set_ylabel("Fair value (R$)")
a.text(3.2,0.075,'IV implícita ≈ 21,6%\n(prêmio JUSTO, sem gordura)',color='crimson',fontsize=9)
a.grid(alpha=.3,axis='y'); a.legend(fontsize=9)

# (3) Comparação de estruturas
a=ax[1,0]
a.plot(ST,naked_put,color='crimson',lw=1.6,label='(a) PUT nua 16,16')
a.plot(ST,ic,color='navy',lw=2,label='(f) Iron Condor 15,66/16,00-17,50/18,00')
a.plot(ST,bps,color='teal',lw=2,ls='--',label='(d) Bull Put Spread 16,50/15,66')
a.fill_between(ST,ic,0,where=ic>=0,color='navy',alpha=.10)
style(a,"(c) Risco DEFINIDO vence: condor/spread limitam a perda")
a.set_ylim(-1.0,0.5)

# (4) Covered call vs ação
a=ax[1,1]
a.plot(ST,ST-S,color='gray',lw=1.5,ls=':',label='Só comprar a unit')
a.plot(ST,covcall,color='darkgreen',lw=2,label='Covered Call (unit + venda CALL 17,50)')
a.annotate('teto em 17,50\n+ prêmio + DY ~8-9%',(17.5,covcall[(np.abs(ST-18.2)).argmin()]),
           (15.0,0.9),fontsize=9,color='darkgreen',arrowprops=dict(arrowstyle='->',color='darkgreen'))
style(a,"(d) Se já possui KLBN11: Covered Call rende mais no lado lateral")
a.set_ylim(-2.0,1.4)

plt.tight_layout(rect=[0,0,1,0.96])
plt.savefig("analysis/klbn_payoffs.png",dpi=130,bbox_inches='tight')
print("OK -> analysis/klbn_payoffs.png")
print(f"Iron Condor crédito={cr_ic:.3f}  Bull Put Spread crédito={cr_bps:.3f}  Covered Call prêmio={cc:.3f}")
