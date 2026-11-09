"""Sensibilidade do vertimento à carga e estimativa para fins de semana.

1) Sensibilidade: em cada mês, compara dia a dia a carga média do SIN (hrload??.dat,
   a mesma em todos os cenários) com o vertimento médio dos cenários e ajusta uma
   reta. A inclinação é o aumento do vertimento (GWh/dia) por GW a menos de carga
   média no dia. Feito por estado e para o Brasil.

2) Estimativa de fim de semana: como a carga do deck não tem a redução de fim de
   semana nos dias certos, simula uma carga de fim de semana/feriado X% menor que a
   dos dias úteis, mantendo a energia consumida no mês (os dias úteis sobem um
   pouco), e aplica a reta de cada mês.

Uso:
  python estima_vertimento_carga.py "C:\\...\\resultados_uf" --caso "C:\\...\\pasta_do_caso"
  python estima_vertimento_carga.py ... --reducoes 5 10 15 --sem-feriados

Requer numpy e matplotlib; usa graficos_uf.py e graficos_semana.py (mesma pasta).
"""
import argparse
import collections
import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graficos_uf import ler_horario, ORDEM_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402
from graficos_semana import datas_das_linhas, classificar  # noqa: E402

COR_UTIL, COR_FDS, COR_PONTO = '#2a78d6', '#eb6834', '#2a78d6'


def carga_diaria(caso, ano):
    """Carga média do SIN em cada dia (GW), somando todos os hrload??.dat."""
    arqs = glob.glob(os.path.join(caso, 'hrload??.dat'))
    if not arqs:
        sys.exit(f'ERRO: não achei arquivos hrload??.dat em {caso}')
    soma = collections.defaultdict(float)
    for f in arqs:
        with open(f, encoding='latin-1') as fh:
            for ln in fh:
                if ln[0] in '$!' or not ln.strip():
                    continue
                y, m, h, v = ln.strip().split(',')[:4]
                if int(y) == ano:
                    soma[datetime.date(ano, int(m), (int(h) - 1) // 24 + 1)] += float(v)
    return {d: s / 24 / 1000 for d, s in soma.items()}


def ajuste(x, y):
    b, a = np.polyfit(x, y, 1)
    r2 = np.corrcoef(x, y)[0, 1] ** 2 if y.std() > 0 else float('nan')
    return a, b, r2


def main():
    p = argparse.ArgumentParser(description='Vertimento x carga e estimativa de fim de semana.')
    p.add_argument('pasta', help='pasta resultados_uf com vergnd_uf_horario.csv')
    p.add_argument('--caso', required=True, help='pasta do caso SDDP com os hrload??.dat')
    p.add_argument('--ano', type=int)
    p.add_argument('--reducoes', nargs='+', type=float, default=[5, 10, 15],
                   help='redução da carga no fim de semana/feriado, em %% (padrão: 5 10 15)')
    p.add_argument('--sem-feriados', action='store_true')
    p.add_argument('--saida')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.pasta, 'graficos_carga')
    os.makedirs(saida, exist_ok=True)

    d = ler_horario(os.path.join(a.pasta, 'vergnd_uf_horario.csv'))
    datas, anos, meses = datas_das_linhas(d)
    ano = a.ano or max(y for y in set(anos) if len(set(meses[anos == y])) == 12)
    sel = anos == ano
    n_cen = len(np.unique(d['cenario'][sel]))
    ufs = [u for u in ORDEM_UF if u in d['ufs']]

    # vertimento diário (GWh/dia, média dos cenários) por estado e Brasil
    dias = sorted(set(datas[sel]))
    idx = {x: i for i, x in enumerate(dias)}
    V = np.zeros((len(dias), len(ufs) + 1))
    linhas_dia = np.array([idx[x] for x in datas[sel]])
    vals = d['valores'][sel]
    for j, u in enumerate(ufs):
        V[:, j] = np.bincount(linhas_dia, weights=vals[:, d['ufs'].index(u)], minlength=len(dias))
    V[:, -1] = V[:, :-1].sum(axis=1)
    V /= n_cen * 1000
    nomes = ufs + ['BR']

    Lmap = carga_diaria(a.caso, ano)
    faltam = [x for x in dias if x not in Lmap]
    if faltam:
        sys.exit(f'ERRO: hrload sem carga para {len(faltam)} dias de {ano} (ex.: {faltam[0]})')
    L = np.array([Lmap[x] for x in dias])
    mes = np.array([x.month for x in dias])
    fds, _ = classificar(np.array(dias), not a.sem_feriados)

    # --- 1) sensibilidade por mês ---------------------------------------------
    coef = {}  # (nome, mes) -> (a, b, r2)
    for j, nm in enumerate(nomes):
        for m in range(1, 13):
            s = mes == m
            coef[(nm, m)] = ajuste(L[s], V[s, j])
    with open(os.path.join(saida, 'sensibilidade_carga.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,mes,aumento_GWh_dia_por_GW_a_menos,pct_da_energia_nao_consumida,R2,carga_media_GW,'
                'carga_min_GW,carga_max_GW,vertimento_medio_GWh_dia\n')
        for nm in nomes:
            j = nomes.index(nm)
            for m in range(1, 13):
                s = mes == m
                _, b, r2 = coef[(nm, m)]
                f.write(f'{nm},{m},{-b:.3f},{-b / 24 * 100:.1f},{r2:.3f},{L[s].mean():.2f},{L[s].min():.2f},'
                        f'{L[s].max():.2f},{V[s, j].mean():.3f}\n')

    # gráfico: dispersão Brasil por mês
    j = nomes.index('BR')
    fig, axs = plt.subplots(3, 4, figsize=(16, 10.5), sharey=False)
    for m, ax in zip(range(1, 13), axs.ravel()):
        s = mes == m
        a0, b, r2 = coef[('BR', m)]
        ax.scatter(L[s & ~fds], V[s & ~fds, j], s=22, color=COR_UTIL, edgecolor=FUNDO, linewidth=0.8,
                   label='dia útil', zorder=3)
        ax.scatter(L[s & fds], V[s & fds, j], s=22, color=COR_FDS, edgecolor=FUNDO, linewidth=0.8,
                   label='fim de semana/feriado (calendário 2030)', zorder=3)
        xx = np.linspace(L[s].min(), L[s].max(), 10)
        ax.plot(xx, a0 + b * xx, color=TEXTO, linewidth=1.2, zorder=2)
        ax.set_title(f'{MESES[m - 1]}/{ano}', loc='left', fontsize=10, fontweight='bold')
        ax.text(0.98, 0.97, f'+{-b:.1f} GWh/dia por GW a menos\n({-b / 24 * 100:.0f}% da energia)  R² {r2:.2f}'
                .replace('.', ','), transform=ax.transAxes, ha='right', va='top', fontsize=8, color=TEXTO2)
        ax.grid(color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
    for ax in axs[:, 0]:
        ax.set_ylabel('Vertimento (GWh/dia)')
    for ax in axs[-1]:
        ax.set_xlabel('Carga média do SIN no dia (GW)')
    axs[0, 0].legend(loc='lower left', fontsize=7.5, frameon=False)
    fig.suptitle(f'Brasil — vertimento diário × carga diária, {ano} (cada ponto = 1 dia, média de {n_cen} cenários)',
                 x=0.01, ha='left', fontsize=13, fontweight='bold')
    fig.text(0.01, 0.005, 'Reta = ajuste linear do mês. A carga do deck é a mesma em todos os cenários; '
             'o vertimento é a média dos cenários.', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.015, 1, 0.97))
    fig.savefig(os.path.join(saida, 'carga_x_vertimento_BR.png'), dpi=130)
    plt.close(fig)

    # gráfico: sensibilidade por estado e mês
    tot = {nm: V[:, nomes.index(nm)].sum() for nm in nomes}
    lista = [u for u in ufs if tot[u] >= 50] + ['BR']   # estados com ≥ 50 GWh/ano
    M = np.array([[-coef[(nm, m)][1] for m in range(1, 13)] for nm in lista])
    R2 = np.array([[coef[(nm, m)][2] for m in range(1, 13)] for nm in lista])
    from matplotlib.colors import LinearSegmentedColormap
    cmap_s = LinearSegmentedColormap.from_list('seq', [FUNDO, '#eb6834', '#3a1a08'])
    cmap_r = LinearSegmentedColormap.from_list('seq_r2', [FUNDO, '#2a78d6', '#0d2a52'])
    fig, axs = plt.subplots(1, 2, figsize=(15, 0.42 * len(lista) + 2.2), gridspec_kw=dict(width_ratios=[1, 1]))
    for ax, dados, tit, fmt, cmap in ((axs[0], M, 'Aumento do vertimento por GW a menos de carga no SIN (GWh/dia)',
                                       '{:.2f}', cmap_s),
                                      (axs[1], R2, 'R² do ajuste (quanto a carga explica o vertimento diário)',
                                       '{:.2f}', cmap_r)):
        lim = np.nanmax(dados[:-1]) if ax is axs[0] else 1
        im = ax.imshow(np.clip(dados, 0, None) if ax is axs[0] else dados, aspect='auto', cmap=cmap,
                       vmin=0, vmax=lim, interpolation='nearest')
        for i in range(dados.shape[0]):
            for k in range(12):
                val = dados[i, k]
                cor = FUNDO if (val / lim if lim else 0) > 0.6 else TEXTO
                if ax is axs[0] and i == dados.shape[0] - 1:
                    cor = FUNDO
                ax.text(k, i, fmt.format(val).replace('.', ','), ha='center', va='center', fontsize=7, color=cor)
        ax.set_yticks(range(len(lista)), lista)
        ax.set_xticks(range(12), [m for m in MESES])
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(tit, loc='left', fontsize=10)
    axs[0].axhline(len(lista) - 1.5, color=TEXTO2, linewidth=0.8)
    fig.suptitle(f'Sensibilidade do vertimento à carga do SIN por estado, {ano}', x=0.01, ha='left',
                 fontsize=13, fontweight='bold')
    fig.text(0.01, 0.005, 'Linha BR = soma dos estados (cor fora da escala dos estados). '
             'Só estados com ≥ 50 GWh de vertimento no ano.', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(os.path.join(saida, 'sensibilidade_estados.png'), dpi=130)
    plt.close(fig)

    # --- 2) estimativa de fim de semana ---------------------------------------
    est = []  # (nome, mes, r, nu, nf, Lu, Lf, Vu, Vf)
    for nm in nomes:
        for m in range(1, 13):
            s = mes == m
            nu, nf = int((s & ~fds).sum()), int((s & fds).sum())
            Lbar = L[s].mean()
            a0, b, _ = coef[(nm, m)]
            for r in a.reducoes:
                q = 1 - r / 100
                Lu = (nu + nf) * Lbar / (nu + nf * q)   # mantém a energia do mês
                Lf = q * Lu
                Vu, Vf = max(a0 + b * Lu, 0), max(a0 + b * Lf, 0)
                est.append((nm, m, r, nu, nf, Lu, Lf, Vu, Vf))
    with open(os.path.join(saida, 'estimativa_fim_semana.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,mes,reducao_carga_fds_pct,dias_uteis,dias_fds_feriado,carga_util_GW,carga_fds_GW,'
                'vertimento_util_GWh_dia,vertimento_fds_GWh_dia,diferenca_pct\n')
        for nm, m, r, nu, nf, Lu, Lf, Vu, Vf in est:
            dif = 100 * (Vf - Vu) / Vu if Vu > 1e-9 else float('nan')
            f.write(f'{nm},{m},{r:g},{nu},{nf},{Lu:.2f},{Lf:.2f},{Vu:.3f},{Vf:.3f},'
                    + (f'{dif:.1f}' if dif == dif else '') + '\n')

    r_meio = sorted(a.reducoes)[len(a.reducoes) // 2]
    fig, axs = plt.subplots(1, 2, figsize=(16, 6.2), gridspec_kw=dict(width_ratios=[1.35, 1]))
    ax = axs[0]
    x = np.arange(12)
    br = {(m, r): (Vu, Vf) for nm, m, r, _, _, _, _, Vu, Vf in est if nm == 'BR'}
    ax.bar(x - 0.2, [br[(m, r_meio)][0] for m in range(1, 13)], width=0.38, color=COR_UTIL, label='dia útil')
    ax.bar(x + 0.2, [br[(m, r_meio)][1] for m in range(1, 13)], width=0.38, color=COR_FDS,
           label=f'fim de semana/feriado (carga {r_meio:g}% menor)')
    if len(a.reducoes) > 1:
        lo, hi = min(a.reducoes), max(a.reducoes)
        ax.vlines(x + 0.2, [br[(m, lo)][1] for m in range(1, 13)], [br[(m, hi)][1] for m in range(1, 13)],
                  color=TEXTO, linewidth=1.2, label=f'fim de semana com carga {lo:g}% a {hi:g}% menor')
    for k, m in enumerate(range(1, 13)):
        vu, vf = br[(m, r_meio)]
        ax.text(k + 0.2, max(vf, br[(m, max(a.reducoes))][1]), f'+{100 * (vf - vu) / vu:.0f}%', ha='center',
                va='bottom', fontsize=8, color=TEXTO2)
    ax.set_xticks(x, MESES)
    ax.set_ylabel('Vertimento (GWh/dia)')
    ax.grid(axis='y', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc='upper left', fontsize=8, frameon=False)
    ax.set_title(f'Brasil: vertimento estimado por dia, {ano}', loc='left', fontsize=10)

    ax = axs[1]
    anual = {}
    for nm, m, r, nu, nf, Lu, Lf, Vu, Vf in est:
        if r == r_meio:
            t = anual.setdefault(nm, [0, 0, 0, 0])
            t[0] += Vu * nu
            t[1] += nu
            t[2] += Vf * nf
            t[3] += nf
    top = sorted([u for u in ufs if tot[u] >= 50], key=lambda u: tot[u])
    y = np.arange(len(top))
    vu = [anual[u][0] / anual[u][1] for u in top]
    vf = [anual[u][2] / anual[u][3] for u in top]
    ax.barh(y + 0.2, vu, height=0.38, color=COR_UTIL, label='dia útil')
    ax.barh(y - 0.2, vf, height=0.38, color=COR_FDS, label=f'fim de semana/feriado ({r_meio:g}% menos carga)')
    for k in range(len(top)):
        ax.text(vf[k], k - 0.2, f' +{100 * (vf[k] - vu[k]) / vu[k]:.0f}%', va='center', fontsize=7.5, color=TEXTO2)
    ax.set_yticks(y, top)
    ax.grid(axis='x', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(loc='lower right', fontsize=8, frameon=False)
    ax.set_xlabel('Vertimento médio (GWh/dia)')
    ax.set_title(f'Estados (≥ 50 GWh/ano): média do ano', loc='left', fontsize=10)
    fig.suptitle(f'Estimativa do vertimento em dia útil × fim de semana/feriado com carga de fim de semana menor, {ano}',
                 x=0.01, ha='left', fontsize=13, fontweight='bold')
    fig.text(0.01, 0.005, 'Estimativa pela reta vertimento × carga de cada mês. A energia consumida no mês é mantida '
             '(dias úteis ficam um pouco acima da média). Não é uma nova simulação do SDDP.',
             fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(os.path.join(saida, 'estimativa_fim_semana.png'), dpi=130)
    plt.close(fig)

    print(f'Ano {ano}, {len(dias)} dias, {int(fds.sum())} fins de semana/feriados, {n_cen} cenários')
    for m in range(1, 13):
        _, b, r2 = coef[('BR', m)]
        print(f'  {MESES[m - 1]}: +{-b:.1f} GWh/dia por GW a menos (R² {r2:.2f})')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
