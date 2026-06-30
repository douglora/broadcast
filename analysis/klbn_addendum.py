"""
ADENDO — incorpora correções da verificação adversarial (3 revisores + síntese).
Foco: (1) carrego/forward e assimetria PUT vs CALL; (2) prob. risk-neutral vs real;
(3) bear call spread (vende o lado estruturalmente rico) ; (4) benchmark caixa SELIC.

Correções de rotulagem aplicadas na leitura dos resultados:
- PUTs sobre ações/units na B3 são EUROPEIAS -> a put vendida NÃO tem exercício antecipado.
  (risco de assignment antecipado só nas CALLs vendidas, perto de ex-dividendo; KLBN sem ex-div até o venc.)
- IR: NÃO há isenção de R$20 mil/mês para opções (só ações à vista). Ganho em opção = 15%, DARF auto-apurado.
- Prêmios das estruturas multi-perna são TEÓRICOS (IV plana 21,6%), não cotações executáveis -> checar book.
- Prob. ITM 17,5% é risk-neutral N(-d2); no mundo real (drift 0) ~21,2%.
- Theta: opção perde ~R$0,007/dia-corrido de valor temporal (ganho do vendedor); ~R$0,0096/dia-útil em base 252.
"""
import numpy as np
from scipy.stats import norm

S, r_nom = 16.80, 0.1425
r = np.log(1 + r_nom); T = 12/252; SIG = 0.216

def bs(K, kind):
    d1 = (np.log(S/K) + (r + 0.5*SIG**2)*T)/(SIG*np.sqrt(T)); d2 = d1 - SIG*np.sqrt(T)
    return (K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)) if kind=='put' \
        else (S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2))

def pITM(K, kind, drift):
    d2 = (np.log(S/K) + (drift - 0.5*SIG**2)*T)/(SIG*np.sqrt(T))
    return norm.cdf(-d2) if kind=='put' else norm.cdf(d2)

F = S*np.exp(r*T)
print(f"Forward 17/jul = {F:.3f}  (spot 16,80; +{F/S-1:.2%}) -> carrego empurra PUT p/ baixo, CALL p/ cima")
d = 0.64
print(f"Assimetria de carrego (IV plana 21,6%, equidistantes do spot):")
print(f"  PUT 16,16 = R${bs(16.16,'put'):.3f}   CALL {S+d:.2f} = R${bs(S+d,'call'):.3f} "
      f"(+{bs(S+d,'call')/bs(16.16,'put')-1:.0%} vs a put)")
print(f"Prob. assignment PUT 16,16: risk-neutral {pITM(16.16,'put',r):.1%} | real(drift0) {pITM(16.16,'put',0):.1%}")
print("\nBEAR CALL SPREAD (neutro-baixista, vende o lado rico, risco definido):")
for ks, kl in [(17.00,17.50),(17.50,18.00)]:
    cr = bs(ks,'call')-bs(kl,'call'); w = kl-ks
    print(f"  Vende {ks:.2f}/Compra {kl:.2f}: crédito R${cr:.3f} perda_máx R${w-cr:.3f} "
          f"R:R {cr/(w-cr):.2f} P(lucro)~{1-pITM(ks,'call',0):.0%}")
print(f"\nBenchmark caixa: SELIC em 12 d.u. = {(1+r_nom)**(12/252)-1:.2%}  (>  0,43% da venda da PUT 16,16)")
