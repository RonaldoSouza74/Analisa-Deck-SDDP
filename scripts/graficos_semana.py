"""Vertimento em dias úteis x fins de semana e feriados, por mês e estado.

Usa o calendário real do ano (datas dos estágios mensais do SDDP) e considera
como "fim de semana / feriado" os sábados, domingos e feriados nacionais.

Atenção: no deck analisado, a carga horária do SDDP não segue os dias da semana
do calendário (o perfil é fixo por data). Por isso, a diferença entre os dois
grupos reflete sobretudo a variação de vento, sol e hidrologia, e não uma carga
menor no fim de semana.

Gera, na pasta de saída:
  semana_<UF>.png    por estado: 12 painéis (um por mês) com o vertimento médio
                     por hora do dia, dia útil x fim de semana/feriado
  semana_BR.png      o mesmo para o total do Brasil
  semana_resumo.png  diferença % (fim de semana/feriado - dia útil) por estado e mês
  semana_resumo.csv  vertimento médio diário por estado, mês e tipo de dia

Uso:
  python graficos_semana.py "C:\\...\\resultados_uf"
  python graficos_semana.py "C:\\...\\resultados_uf" --var gergnd
  python graficos_semana.py "C:\\...\\resultados_uf" --sem-feriados

Requer numpy e matplotlib; usa graficos_uf.py (mesma pasta).
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graficos_uf import (ler_horario, ORDEM_UF, REGIAO_DA_UF, MESES, VARS, TEXTO, TEXTO2, GRADE,  # noqa: E402
                         FUNDO, plt, np)

COR_UTIL, COR_FDS = '#2a78d6', '#eb6834'


def pascoa(ano):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return datetime.date(ano, mes, dia)


def feriados_nacionais(ano):
    p = pascoa(ano)
    dt = datetime.timedelta
    fixos = [(1, 1, 'Confraternização Universal'), (4, 21, 'Tiradentes'), (5, 1, 'Dia do Trabalho'),
             (9, 7, 'Independência'), (10, 12, 'N. Sra. Aparecida'), (11, 2, 'Finados'),
             (11, 15, 'Proclamação da República'), (11, 20, 'Consciência Negra'), (12, 25, 'Natal')]
    f = {datetime.date(ano, m, d): n for m, d, n in fixos}
    f[p - dt(days=48)] = 'Carnaval (segunda)'
    f[p - dt(days=47)] = 'Carnaval (terça)'
    f[p - dt(days=2)] = 'Sexta-feira Santa'
    f[p + dt(days=60)] = 'Corpus Christi'
    return f


def datas_das_linhas(d):
    """Data (dia) de cada linha do CSV horário, pelo estágio mensal e pela hora."""
    m0 = d['mes_ini'] - 1 + d['estagio'] - 1
    meses = m0 % 12 + 1
    anos = d['ano_ini'] + m0 // 12
    dias = (d['hora'] - 1) // 24 + 1
    cache = {}
    out = []
    for a, m, dd in zip(anos, meses, dias):
        k = (a, m, dd)
        if k not in cache:
            cache[k] = datetime.date(a, m, dd)
        out.append(cache[k])
    return np.array(out), anos, meses


def classificar(datas, com_feriados):
    anos = sorted({x.year for x in datas})
    fer = {}
    if com_feriados:
        for a in anos:
            fer.update(feriados_nacionais(a))
    unicos = {x: (x.weekday() >= 5 or x in fer) for x in set(datas)}
    return np.array([unicos[x] for x in datas]), fer


def perfil(x, hd, mascara):
    """Média e quartis por hora do dia."""
    med, q1, q3 = np.zeros(24), np.zeros(24), np.zeros(24)
    for h in range(24):
        v = x[mascara & (hd == h)]
        if len(v):
            med[h] = v.mean()
            q1[h], q3[h] = np.percentile(v, [25, 75])
    return med, q1, q3


def figura(nome_uf, titulo, x, d, fds, meses, anos, saida, arquivo, n_cen):
    hd = (d['hora'] - 1) % 24
    pares = sorted({(a, m) for a, m in zip(anos, meses)})
    fig, axs = plt.subplots(3, 4, figsize=(16, 10.5), sharex=True, sharey=True)
    axs = axs.ravel()
    linhas = []
    horas = np.arange(1, 25)
    for k, (a, m) in enumerate(pares[:12]):
        ax = axs[k]
        sel = (anos == a) & (meses == m)
        for msk, cor, rot in ((sel & ~fds, COR_UTIL, 'Dia útil'), (sel & fds, COR_FDS, 'Fim de semana / feriado')):
            if not msk.any():
                continue
            med, q1, q3 = perfil(x, hd, msk)
            ax.fill_between(horas, q1, q3, color=cor, alpha=0.15, linewidth=0)
            ax.plot(horas, med, color=cor, linewidth=2, label=rot)
        n_u = len(np.unique((d['hora'][sel & ~fds] - 1) // 24))   # dias no mês
        n_f = len(np.unique((d['hora'][sel & fds] - 1) // 24))
        # energia média diária (GWh/dia) = soma / (dias x cenários) / 1000
        e_u = x[sel & ~fds].sum() / max(n_u * n_cen, 1) / 1000
        e_f = x[sel & fds].sum() / max(n_f * n_cen, 1) / 1000
        dif = 100 * (e_f - e_u) / e_u if e_u > 1e-9 else float('nan')
        linhas.append((nome_uf, a, m, n_u, n_f, e_u, e_f, dif))
        txt = (f'útil {e_u:.2f} · fds/fer {e_f:.2f} GWh/dia' if max(e_u, e_f) < 10 else
               f'útil {e_u:.0f} · fds/fer {e_f:.0f} GWh/dia')
        ax.set_title(f'{MESES[m - 1]}/{a}', loc='left', fontsize=10, fontweight='bold')
        ax.text(0.01, 0.97, f'{txt}\n{n_u} dias úteis, {n_f} fds/feriados'
                + (f'  ·  {dif:+.0f}%'.replace('.', ',') if dif == dif else ''),
                transform=ax.transAxes, va='top', fontsize=7.5, color=TEXTO2)
        ax.grid(color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_xticks(range(1, 25, 2))
        ax.set_xlim(1, 24)
    for ax in axs[len(pares):]:
        ax.axis('off')
    for ax in axs[8:12]:
        ax.set_xlabel('Hora do dia')
    for ax in axs[::4]:
        ax.set_ylabel('MW')
    axs[0].legend(loc='upper right', fontsize=8, frameon=False)
    fig.suptitle(titulo, x=0.01, ha='left', fontsize=13, fontweight='bold')
    fig.text(0.01, 0.005, 'Linha = média de todos os dias do grupo e de todos os cenários; faixa = 25% a 75%. '
             'Fim de semana/feriado = sábados, domingos e feriados nacionais do calendário. Hora 1 = 00h-01h.',
             fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.015, 1, 0.97))
    fig.savefig(os.path.join(saida, arquivo), dpi=130)
    plt.close(fig)
    return linhas


def resumo(linhas, saida, var):
    ufs = [u for u in ORDEM_UF + ['BR'] if any(l_[0] == u for l_ in linhas)]
    pares = sorted({(l_[1], l_[2]) for l_ in linhas})
    M = np.full((len(ufs), len(pares)), np.nan)
    for l_ in linhas:
        if l_[5] >= 0.05:  # só onde o vertimento em dia útil é ≥ 0,05 GWh/dia
            M[ufs.index(l_[0]), pares.index((l_[1], l_[2]))] = l_[7]
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list('div', ['#164a8a', '#2a78d6', '#e9e8e4', '#eb6834', '#a3401a'])
    cmap.set_bad(FUNDO)
    lim = np.nanpercentile(np.abs(M), 95) if np.isfinite(M).any() else 1
    fig, ax = plt.subplots(figsize=(11, 0.36 * len(ufs) + 2))
    im = ax.imshow(M, aspect='auto', cmap=cmap, vmin=-lim, vmax=lim, interpolation='nearest')
    for i in range(len(ufs)):
        for j in range(len(pares)):
            if np.isfinite(M[i, j]):
                ax.text(j, i, f'{M[i, j]:+.0f}', ha='center', va='center', fontsize=7,
                        color=FUNDO if abs(M[i, j]) > 0.6 * lim else TEXTO)
    ax.set_yticks(range(len(ufs)), ufs)
    ax.set_xticks(range(len(pares)), [f'{MESES[m - 1]}/{str(a)[2:]}' for a, m in pares])
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label('%', color=TEXTO2)
    cb.outline.set_visible(False)
    ax.set_title(f'{VARS[var]["titulo"]}: fim de semana/feriado em relação ao dia útil (%, por GWh/dia). '
                 'Laranja = mais no fim de semana', loc='left', fontsize=10)
    fig.text(0.01, 0.005, 'Células vazias: vertimento em dia útil abaixo de 0,05 GWh/dia.', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(os.path.join(saida, 'semana_resumo.png'), dpi=130)
    plt.close(fig)
    with open(os.path.join(saida, 'semana_resumo.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,ano,mes,dias_uteis,dias_fds_feriado,GWh_dia_util,GWh_dia_fds_feriado,diferenca_pct\n')
        for l_ in linhas:
            f.write(f'{l_[0]},{l_[1]},{l_[2]},{l_[3]},{l_[4]},{l_[5]:.4f},{l_[6]:.4f},'
                    + (f'{l_[7]:.1f}' if l_[7] == l_[7] else '') + '\n')


def main():
    p = argparse.ArgumentParser(description='Vertimento em dias úteis x fins de semana/feriados.')
    p.add_argument('pasta', help='pasta resultados_uf com o <var>_uf_horario.csv')
    p.add_argument('--var', default='vergnd', choices=['vergnd', 'gergnd'])
    p.add_argument('--saida', help='pasta dos gráficos (padrão: <pasta>\\graficos_semana)')
    p.add_argument('--ano', type=int, help='ano a considerar (padrão: o último ano completo do arquivo)')
    p.add_argument('--sem-feriados', action='store_true', help='não trata feriados como fim de semana')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.pasta, 'graficos_semana')
    os.makedirs(saida, exist_ok=True)

    arq = os.path.join(a.pasta, f'{a.var}_uf_horario.csv')
    if not os.path.exists(arq):
        sys.exit(f'ERRO: não achei {arq}')
    print('Lendo', arq, '...')
    d = ler_horario(arq)
    datas, anos, meses = datas_das_linhas(d)
    ano = a.ano or max(y for y in set(anos) if len(set(meses[anos == y])) == 12)
    sel = anos == ano
    d = {k: (x[sel] if isinstance(x, np.ndarray) else x) for k, x in d.items()}
    datas, anos, meses = datas[sel], anos[sel], meses[sel]
    fds, fer = classificar(datas, not a.sem_feriados)
    n_cen = len(np.unique(d['cenario']))
    print(f'Ano {ano}: {len(set(datas))} dias, {len({x for x in set(datas) if x.weekday() >= 5})} sábados/domingos')
    for dt_, n in sorted(fer.items()):
        if dt_.year == ano:
            print(f'  feriado {dt_.strftime("%d/%m")} ({["seg", "ter", "qua", "qui", "sex", "sáb", "dom"][dt_.weekday()]}) {n}')

    titulo_var = VARS[a.var]['titulo']
    linhas = []
    ufs = [u for u in ORDEM_UF if u in d['ufs']]
    for u in ufs:
        x = d['valores'][:, d['ufs'].index(u)]
        linhas += figura(u, f'{u} ({REGIAO_DA_UF[u]}) — {titulo_var.lower()} em dia útil × fim de semana/feriado, '
                            f'{ano}, {n_cen} cenários', x, d, fds, meses, anos, saida, f'semana_{u}.png', n_cen)
    x = d['valores'].sum(axis=1)
    linhas += figura('BR', f'Brasil — {titulo_var.lower()} em dia útil × fim de semana/feriado, {ano}, '
                           f'{n_cen} cenários', x, d, fds, meses, anos, saida, 'semana_BR.png', n_cen)
    resumo(linhas, saida, a.var)
    print(f'Fim. {len(ufs) + 1} figuras semana_<UF>.png + semana_resumo.png/.csv em {saida}')


if __name__ == '__main__':
    main()
