"""Dias úteis x fins de semana a partir apenas dos dados do SDDP.

Fins de semana: em cada semana de cada mês (dias 1-7, 8-14, 15-21, 22-28 e a
sobra 29-31), os 2 dias com menor carga horária média do SIN (soma dos
hrload??.dat do caso) são considerados sábado e domingo; os outros 5 são dias
úteis. Na sobra de 2 ou 3 dias, entra só o dia de menor carga (1 dia de fim de
semana); sobra de 1 dia conta como dia útil.

Nada é estimado: são usados só os valores horários de entrada (carga) e de
saída (vertimento, geração renovável e injeção nas barras) do SDDP, para cada
um dos cenários.

Gera, na pasta de saída:
  semanas.csv / dias.csv             semanas, tipo de cada dia e carga média do dia
  diario/<var>/diario_<var>_<UF>.png por estado e variável (vertimento, geração,
                                     injeção): 12 painéis (meses), cada dia = caixa
                                     dos cenários; carga diária no eixo da direita
  diario_valores.csv                 os valores diários por estado, cenário e tipo de dia
  horario/horario_<UF>.png           por estado: 12 painéis (meses), perfil horário médio
                                     do mês (dias úteis x fim de semana), vertimento em
                                     caixas e carga no eixo da direita
  resumo_util_fds.png / .csv         média do ano: dia útil x fim de semana por estado
  correlacoes.png / .csv             correlações horárias entre carga, geração, vertimento
                                     e injeção, por estado
  carga_liquida_x_vertimento.png     vertimento x carga líquida do SIN, hora a hora

Uso:
  python analise_semana_carga.py "C:\\...\\resultados_uf" --caso "C:\\...\\pasta_do_caso"

Requer numpy e matplotlib; usa graficos_uf.py (mesma pasta).
"""
import argparse
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graficos_uf import ler_horario, ORDEM_UF, REGIAO_DA_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa

COR_UTIL, COR_FDS = '#2a78d6', '#eb6834'
DIAS_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
VAR_INFO = {'vergnd': ('Vertimento renovável', 'GWh/dia'),
            'gergnd': ('Geração renovável', 'GWh/dia'),
            'businj': ('Injeção líquida (positivo = exporta)', 'MW médio')}


# ----------------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------------
def ler_carga(caso, ano):
    """Carga horária do SIN (MW) do ano: matriz [mês 1-12, dia 1-31, hora 0-23]."""
    arqs = glob.glob(os.path.join(caso, 'hrload??.dat'))
    if not arqs:
        sys.exit(f'ERRO: não achei arquivos hrload??.dat em {caso}')
    C = np.full((13, 32, 24), np.nan)
    soma = collections.defaultdict(float)
    for f in arqs:
        with open(f, encoding='latin-1') as fh:
            for ln in fh:
                if ln[0] in '$!' or not ln.strip():
                    continue
                y, m, h, v = ln.strip().split(',')[:4]
                if int(y) == ano:
                    soma[(int(m), int(h))] += float(v)
    for (m, h), v in soma.items():
        C[m, (h - 1) // 24 + 1, (h - 1) % 24] = v
    for m in range(1, 13):
        if np.isnan(C[m, 1:DIAS_MES[m - 1] + 1]).any():
            sys.exit(f'ERRO: carga incompleta no mês {m} de {ano} nos hrload??.dat')
    return C


def ler_saida(pasta, var, ano):
    """Saída horária por UF: matriz [cenário, mês, dia, hora, UF] e lista de UFs."""
    nomes = [var] + (['bus_inj'] if var == 'businj' else [])
    arq = next((os.path.join(pasta, f'{n}_uf_horario.csv') for n in nomes
                if os.path.exists(os.path.join(pasta, f'{n}_uf_horario.csv'))), None)
    if not arq:
        return None, None
    print('Lendo', arq, '...')
    d = ler_horario(arq)
    m0 = d['mes_ini'] - 1 + d['estagio'] - 1
    meses, anos = m0 % 12 + 1, d['ano_ini'] + m0 // 12
    sel = anos == ano
    ncen = d['cenario'][sel].max()
    ufs = [u for u in ORDEM_UF if u in d['ufs']]
    col = [d['ufs'].index(u) for u in ufs]
    X = np.full((ncen, 13, 32, 24, len(ufs)), np.nan)
    h = d['hora'][sel] - 1
    X[d['cenario'][sel] - 1, meses[sel], h // 24 + 1, h % 24] = d['valores'][sel][:, col]
    return X, ufs


# ----------------------------------------------------------------------------
# Semanas
# ----------------------------------------------------------------------------
def montar_semanas(C):
    semanas = []
    for m in range(1, 13):
        diaria = C[m].mean(axis=1)
        for k, ini in enumerate(range(1, DIAS_MES[m - 1] + 1, 7)):
            dias = list(range(ini, min(ini + 7, DIAS_MES[m - 1] + 1)))
            n_fds = 2 if len(dias) == 7 else (1 if len(dias) >= 2 else 0)
            fds = sorted(sorted(dias, key=lambda x: diaria[x])[:n_fds])
            util = [x for x in dias if x not in fds]
            semanas.append(dict(mes=m, num=k + 1, rotulo=f'{MESES[m - 1]} S{k + 1}', util=util, fds=fds))
    return semanas


# ----------------------------------------------------------------------------
# Gráficos
# ----------------------------------------------------------------------------
def _caixas(ax, dados, pos, cor, largura):
    ok = [i for i, x in enumerate(dados) if x is not None]
    if not ok:
        return
    ax.boxplot([dados[i] for i in ok], positions=[pos[i] for i in ok], widths=largura, whis=(0, 100),
               showfliers=False, patch_artist=True, manage_ticks=False,
               boxprops=dict(facecolor=cor + '66', edgecolor=cor, linewidth=0.9),
               whiskerprops=dict(color=cor, linewidth=0.9), capprops=dict(color=cor, linewidth=0.9),
               medianprops=dict(color=TEXTO, linewidth=1.2))


def tipo_dos_dias(semanas):
    """Dicionário (mês, dia) -> 'util' ou 'fds'."""
    t = {}
    for s in semanas:
        for d in s['util']:
            t[(s['mes'], d)] = 'util'
        for d in s['fds']:
            t[(s['mes'], d)] = 'fds'
    return t


def _carga_eixo_direito(ax, faixa_baixo=0.42):
    """Cria o eixo secundário da carga e reserva a parte de cima do gráfico para ela.

    As caixas (eixo da esquerda) ficam na parte de baixo e a carga (eixo da direita) na de
    cima, para as duas não se sobreporem.
    """
    axc = ax.twinx()
    axc.spines['right'].set_visible(True)
    axc.spines['right'].set_color(GRADE)
    axc.tick_params(axis='y', labelsize=7, colors=TEXTO2)
    return axc


def _ajusta_faixas(ax, axc, vmax, cmin, cmax, frac_caixas=0.58, frac_carga=0.40):
    """Caixas ocupam os ~58% de baixo; carga ocupa os ~40% de cima."""
    vmax = vmax if vmax > 0 else 1
    ax.set_ylim(0, vmax / frac_caixas)
    ax.set_yticks([t for t in ax.get_yticks() if 0 <= t <= vmax * 1.001])
    amp = max(cmax - cmin, 1e-6)
    baixo = cmin - amp * (1 - frac_carga) / frac_carga
    axc.set_ylim(baixo, cmax + amp * 0.06)
    axc.set_yticks([t for t in axc.get_yticks() if cmin - amp * 0.05 <= t <= cmax + amp * 0.06])


def grafico_diario(nome, j, v, X, C, tipos, saida):
    """Uma figura por estado e variável: 12 painéis (meses); cada dia = caixa dos 10 cenários."""
    energia = v != 'businj'
    tit, un = VAR_INFO[v]
    Xe = X[..., j] if j is not None else X.sum(axis=-1)
    if energia:
        diario = np.nansum(Xe, axis=3) / 1000          # [cen, mês, dia] GWh/dia
    else:
        diario = np.nanmean(Xe, axis=3)                # MW médio
    fig, axs = plt.subplots(4, 3, figsize=(20, 17))
    linhas = []
    vmin_glob = np.nanmin(diario[:, 1:13]) if not energia else 0
    vmax_glob = np.nanmax(diario[:, 1:13])
    for m, ax in zip(range(1, 13), axs.ravel()):
        nd = DIAS_MES[m - 1]
        dias = np.arange(1, nd + 1)
        for tp, cor in (('util', COR_UTIL), ('fds', COR_FDS)):
            ds = [d for d in dias if tipos[(m, d)] == tp]
            _caixas(ax, [diario[:, m, d] for d in ds], ds, cor, 0.7)
        if not energia:
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
        ax.set_xlim(0.3, nd + 0.7)
        ax.set_xticks(dias, [str(d) if d % 2 else '' for d in dias], fontsize=7)
        ax.grid(axis='y', color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_title(f'{MESES[m - 1]}/2030', loc='left', fontsize=10, fontweight='bold')
        if (m - 1) % 3 == 0:
            ax.set_ylabel(un)
        carga = C[m, 1:nd + 1].mean(axis=1) / 1000
        axc = _carga_eixo_direito(ax)
        axc.plot(dias, carga, color=TEXTO2, linewidth=1, linestyle='--', zorder=1)
        cores = [COR_UTIL if tipos[(m, d)] == 'util' else COR_FDS for d in dias]
        axc.scatter(dias, carga, c=cores, s=16, edgecolor=TEXTO, linewidth=0.5, marker='D', zorder=2)
        diaria = C[1:13, 1:].mean(axis=2)              # NaN nos dias que não existem
        cmin, cmax = np.nanmin(diaria) / 1000, np.nanmax(diaria) / 1000
        if energia:
            _ajusta_faixas(ax, axc, vmax_glob, cmin, cmax)
        else:
            amp = vmax_glob - vmin_glob
            ax.set_ylim(vmin_glob - amp * 0.02, vmin_glob + amp / 0.58)
            amp_c = cmax - cmin
            axc.set_ylim(cmin - amp_c * 1.5, cmax + amp_c * 0.06)
            axc.set_yticks([t for t in axc.get_yticks() if cmin - amp_c * 0.05 <= t <= cmax + amp_c * 0.06])
        if m % 3 == 0:
            axc.set_ylabel('Carga SIN (GW)', color=TEXTO2, fontsize=8)
        for d in dias:
            for c in range(diario.shape[0]):
                linhas.append((nome, v, m, d, tipos[(m, d)], c + 1, diario[c, m, d]))
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    fig.legend(handles=[Patch(facecolor=COR_UTIL + '66', edgecolor=COR_UTIL, label=f'{tit.split(" (")[0]} — dia útil'),
                        Patch(facecolor=COR_FDS + '66', edgecolor=COR_FDS,
                              label=f'{tit.split(" (")[0]} — fim de semana (2 dias de menor carga da semana)'),
                        Line2D([], [], color=TEXTO2, linestyle='--', marker='D', markerfacecolor=FUNDO,
                               markeredgecolor=TEXTO, label='carga média do dia no SIN (eixo da direita)')],
               loc='upper right', ncol=3, fontsize=9, frameon=False, bbox_to_anchor=(0.995, 0.985))
    titulo = 'Brasil' if j is None else f'{nome} ({REGIAO_DA_UF[nome]})'
    fig.suptitle(f'{titulo} — {tit.lower()} por dia ({un}), 2030', x=0.01, y=0.985, ha='left',
                 fontsize=14, fontweight='bold')
    fig.text(0.01, 0.004, 'Caixa = 10 cenários (mínimo a máximo, linha = mediana). Eixo da esquerda: ' + un +
             '; eixo da direita: carga do SIN (GW), entrada do SDDP, igual em todos os cenários.',
             fontsize=8.5, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.01, 1, 0.955), h_pad=1.6, w_pad=2.5)
    pasta = os.path.join(saida, 'diario', v)
    os.makedirs(pasta, exist_ok=True)
    fig.savefig(os.path.join(pasta, f'diario_{v}_{nome}.png'), dpi=110)
    plt.close(fig)
    return linhas


def grafico_horario(nome, j, X, C, tipos, saida):
    """Uma figura por estado: 12 painéis (meses); perfil horário médio do mês por tipo de dia."""
    Xe = X[..., j] if j is not None else X.sum(axis=-1)       # [cen, mês, dia, hora]
    fig, axs = plt.subplots(4, 3, figsize=(20, 17))
    horas = np.arange(1, 25)
    perfis = {}
    for m in range(1, 13):
        for tp in ('util', 'fds'):
            ds = [d for d in range(1, DIAS_MES[m - 1] + 1) if tipos[(m, d)] == tp]
            perfis[(m, tp)] = (Xe[:, m, ds].mean(axis=1), C[m, ds].mean(axis=0) / 1000, len(ds))
    vmax = max(np.nanmax(p[0]) for p in perfis.values())
    cmin = min(np.nanmin(p[1]) for p in perfis.values())
    cmax = max(np.nanmax(p[1]) for p in perfis.values())
    for m, ax in zip(range(1, 13), axs.ravel()):
        axc = _carga_eixo_direito(ax)
        for tp, cor, off in (('util', COR_UTIL, -0.19), ('fds', COR_FDS, 0.19)):
            pv, pc, n = perfis[(m, tp)]
            _caixas(ax, [pv[:, h] for h in range(24)], horas + off, cor, 0.34)
            axc.plot(horas, pc, color=cor, linewidth=1.6, linestyle='--', marker='o', markersize=3,
                     markerfacecolor=FUNDO, markeredgecolor=cor)
        _ajusta_faixas(ax, axc, vmax, cmin, cmax)
        ax.set_xlim(0.4, 24.6)
        ax.set_xticks(horas, [str(h) if h % 2 else '' for h in horas], fontsize=7)
        ax.grid(axis='y', color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        nu, nf = perfis[(m, 'util')][2], perfis[(m, 'fds')][2]
        ax.set_title(f'{MESES[m - 1]}/2030  ·  {nu} dias úteis, {nf} de fim de semana', loc='left', fontsize=10,
                     fontweight='bold')
        if (m - 1) % 3 == 0:
            ax.set_ylabel('Vertimento (MW)')
        if m % 3 == 0:
            axc.set_ylabel('Carga SIN (GW)', color=TEXTO2, fontsize=8)
        if m > 9:
            ax.set_xlabel('Hora do dia (1 = 00h-01h)', fontsize=8)
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    fig.legend(handles=[Patch(facecolor=COR_UTIL + '66', edgecolor=COR_UTIL, label='vertimento — dia útil'),
                        Patch(facecolor=COR_FDS + '66', edgecolor=COR_FDS, label='vertimento — fim de semana'),
                        Line2D([], [], color=COR_UTIL, linestyle='--', marker='o', markerfacecolor=FUNDO,
                               label='carga SIN — dia útil (eixo da direita)'),
                        Line2D([], [], color=COR_FDS, linestyle='--', marker='o', markerfacecolor=FUNDO,
                               label='carga SIN — fim de semana (eixo da direita)')],
               loc='upper right', ncol=4, fontsize=9, frameon=False, bbox_to_anchor=(0.995, 0.985))
    titulo = 'Brasil' if j is None else f'{nome} ({REGIAO_DA_UF[nome]})'
    fig.suptitle(f'{titulo} — perfil horário médio de cada mês, 2030', x=0.01, y=0.985, ha='left',
                 fontsize=14, fontweight='bold')
    fig.text(0.01, 0.004, 'Média de todos os dias úteis (ou de fim de semana) do mês, para cada cenário; caixa = 10 '
             'cenários (mínimo a máximo, linha = mediana). Fim de semana = 2 dias de menor carga de cada semana.',
             fontsize=8.5, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.01, 1, 0.955), h_pad=1.6, w_pad=2.5)
    pasta = os.path.join(saida, 'horario')
    os.makedirs(pasta, exist_ok=True)
    fig.savefig(os.path.join(pasta, f'horario_{nome}.png'), dpi=110)
    plt.close(fig)


def grafico_resumo(saidas, ufs, semanas, C, saida):
    X, _ = saidas['vergnd']
    nomes = ufs + ['BR']
    linhas = []
    dados = {}
    for j, nm in enumerate(nomes):
        Xe = X[..., j] if nm != 'BR' else X.sum(axis=-1)
        tot = {}
        for tipo in ('util', 'fds'):
            soma, n = 0, 0
            for s in semanas:
                if s[tipo]:
                    soma = soma + Xe[:, s['mes'], s[tipo]].sum(axis=(1, 2)) / 1000
                    n += len(s[tipo])
            tot[tipo] = soma / n          # GWh/dia por cenário
        dados[nm] = tot
        u, f = tot['util'], tot['fds']
        linhas.append((nm, u.mean(), f.mean(), 100 * (f.mean() - u.mean()) / u.mean() if u.mean() >= 0.01 else float('nan'),
                       u.min(), u.max(), f.min(), f.max()))
    nu = sum(len(s['util']) for s in semanas)
    nf = sum(len(s['fds']) for s in semanas)
    cu = np.mean([C[s['mes'], d].mean() for s in semanas for d in s['util']]) / 1000
    cf = np.mean([C[s['mes'], d].mean() for s in semanas for d in s['fds']]) / 1000
    with open(os.path.join(saida, 'resumo_util_fds.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,vertimento_util_GWh_dia,vertimento_fds_GWh_dia,diferenca_pct,util_min_cenarios,util_max_cenarios,'
                'fds_min_cenarios,fds_max_cenarios\n')
        for l_ in linhas:
            f.write(','.join([l_[0]] + ['' if x != x else f'{x:.3f}' for x in l_[1:]]) + '\n')
    sel = [nm for nm in ufs if dados[nm]['util'].mean() + dados[nm]['fds'].mean() >= 0.5]
    sel = sorted(sel, key=lambda nm: dados[nm]['util'].mean())
    fig = plt.figure(figsize=(16, 0.42 * len(sel) + 2.5))
    gs = fig.add_gridspec(2, 2, width_ratios=[1.6, 1], hspace=0.45)
    axs = [fig.add_subplot(gs[:, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, 1])]
    ax = axs[0]
    y = np.arange(len(sel))
    for off, tipo, cor in ((0.2, 'util', COR_UTIL), (-0.2, 'fds', COR_FDS)):
        ax.boxplot([dados[nm][tipo] for nm in sel], positions=y + off, widths=0.34, vert=False, whis=(0, 100),
                   showfliers=False, patch_artist=True, manage_ticks=False,
                   boxprops=dict(facecolor=cor + '66', edgecolor=cor), whiskerprops=dict(color=cor),
                   capprops=dict(color=cor), medianprops=dict(color=TEXTO, linewidth=1.2))
    for k, nm in enumerate(sel):
        u, f = dados[nm]['util'].mean(), dados[nm]['fds'].mean()
        ax.text(max(dados[nm]['fds'].max(), dados[nm]['util'].max()), k, f'  {100 * (f - u) / u:+.0f}%'.replace('.', ','),
                va='center', fontsize=8, color=TEXTO2)
    ax.set_yticks(y, sel)
    ax.grid(axis='x', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel('Vertimento médio por dia em 2030 (GWh/dia)')
    ax.set_title('Por estado — caixa = 10 cenários; % = fim de semana em relação ao dia útil', loc='left', fontsize=10)
    ax.plot([], [], color=COR_UTIL, linewidth=6, alpha=0.6, label=f'dias úteis ({nu} dias)')
    ax.plot([], [], color=COR_FDS, linewidth=6, alpha=0.6, label=f'fins de semana ({nf} dias)')
    ax.legend(loc='lower right', fontsize=8, frameon=False)
    ax = axs[1]
    for off, tipo, cor in ((0.2, 'util', COR_UTIL), (-0.2, 'fds', COR_FDS)):
        ax.boxplot([dados['BR'][tipo]], positions=[off], widths=0.34, vert=False, whis=(0, 100), showfliers=False,
                   patch_artist=True, manage_ticks=False, boxprops=dict(facecolor=cor + '66', edgecolor=cor),
                   whiskerprops=dict(color=cor), capprops=dict(color=cor), medianprops=dict(color=TEXTO, linewidth=1.2))
    u, f = dados['BR']['util'].mean(), dados['BR']['fds'].mean()
    ax.text(dados['BR']['util'].max(), 0.2, f'  média {u:.0f}'.replace('.', ','), va='center', fontsize=8, color=TEXTO2)
    ax.text(dados['BR']['fds'].max(), -0.2, f'  média {f:.0f} ({100 * (f - u) / u:+.0f}%)'.replace('.', ','),
            va='center', fontsize=8, color=TEXTO2)
    ax.set_yticks([0.2, -0.2], ['dias úteis', 'fim de semana'])
    ax.set_xlim(0, max(dados['BR']['fds'].max(), dados['BR']['util'].max()) * 1.35)
    ax.grid(axis='x', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel('GWh/dia')
    ax.set_title('Brasil — vertimento médio por dia (caixa = 10 cenários)', loc='left', fontsize=10)
    ax = axs[2]
    ax.barh([0.2, -0.2], [cu, cf], height=0.34, color=[COR_UTIL, COR_FDS])
    ax.text(cu, 0.2, f' {cu:.1f} GW'.replace('.', ','), va='center', fontsize=8, color=TEXTO2)
    ax.text(cf, -0.2, f' {cf:.1f} GW ({100 * (cf - cu) / cu:+.1f}%)'.replace('.', ','), va='center', fontsize=8,
            color=TEXTO2)
    ax.set_yticks([0.2, -0.2], ['dias úteis', 'fim de semana'])
    ax.set_xlim(0, cu * 1.35)
    ax.grid(axis='x', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel('GW')
    ax.set_title('Carga média do SIN (entrada do SDDP)', loc='left', fontsize=10)
    fig.suptitle('Vertimento em dias úteis × fins de semana (2 dias de menor carga de cada semana), 2030',
                 x=0.01, ha='left', fontsize=13, fontweight='bold')
    fig.subplots_adjust(left=0.05, right=0.98, top=0.9, bottom=0.08, wspace=0.18)
    fig.savefig(os.path.join(saida, 'resumo_util_fds.png'), dpi=130)
    plt.close(fig)
    return linhas


def correlacoes(saidas, ufs, C, saida):
    """Correlação horária (todas as horas de 2030 e todos os cenários)."""
    V, _ = saidas['vergnd']
    G = saidas.get('gergnd', (None,))[0]
    B = saidas.get('businj', (None,))[0]
    ncen = V.shape[0]
    mask = ~np.isnan(V[0, :, :, :, 0])
    carga = np.broadcast_to(C, (ncen,) + C.shape)[:, mask].ravel() / 1000          # GW
    def serie(X, j):
        return X[..., j][:, mask].ravel() if j is not None else X.sum(axis=-1)[:, mask].ravel()
    pares = [('carga × vertimento', lambda j: (carga, serie(V, j)))]
    if G is not None:
        renov = (G.sum(axis=-1) + V.sum(axis=-1))[:, mask].ravel() / 1000           # GW disponível no Brasil
        liquida = carga - renov
        pares += [('carga × geração', lambda j: (carga, serie(G, j))),
                  ('geração × vertimento', lambda j: (serie(G, j), serie(V, j))),
                  ('carga líquida × vertimento', lambda j: (liquida, serie(V, j)))]
    if B is not None:
        pares += [('carga × injeção', lambda j: (carga, serie(B, j))),
                  ('injeção × vertimento', lambda j: (serie(B, j), serie(V, j)))]
        if G is not None:
            pares.append(('geração × injeção', lambda j: (serie(G, j), serie(B, j))))
    tot = {u: np.nansum(V[..., j]) for j, u in enumerate(ufs)}
    lista = [u for u in ufs if tot[u] / ncen / 1000 >= 50]
    nomes = lista + ['BR']
    R = np.full((len(nomes), len(pares)), np.nan)
    for i, nm in enumerate(nomes):
        j = ufs.index(nm) if nm != 'BR' else None
        for k, (rot, f) in enumerate(pares):
            if nm == 'BR' and 'injeção' in rot:
                continue
            a, b = f(j)
            if a.std() > 0 and b.std() > 0:
                R[i, k] = np.corrcoef(a, b)[0, 1]
    with open(os.path.join(saida, 'correlacoes.csv'), 'w', encoding='utf-8-sig') as fh:
        fh.write('uf,' + ','.join(p[0] for p in pares) + '\n')
        for i, nm in enumerate(nomes):
            fh.write(nm + ',' + ','.join('' if np.isnan(x) else f'{x:.3f}' for x in R[i]) + '\n')
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list('div', ['#b4302f', '#e34948', '#e9e8e4', '#2a78d6', '#164a8a'])
    cmap.set_bad(FUNDO)
    fig, ax = plt.subplots(figsize=(2 + 1.5 * len(pares), 0.42 * len(nomes) + 2.4))
    im = ax.imshow(R, aspect='auto', cmap=cmap, vmin=-1, vmax=1, interpolation='nearest')
    for i in range(len(nomes)):
        for k in range(len(pares)):
            if not np.isnan(R[i, k]):
                ax.text(k, i, f'{R[i, k]:+.2f}'.replace('.', ','), ha='center', va='center', fontsize=8,
                        color=FUNDO if abs(R[i, k]) > 0.55 else TEXTO)
    ax.set_yticks(range(len(nomes)), nomes)
    ax.set_xticks(range(len(pares)), [p[0].replace(' × ', '\n× ') for p in pares], fontsize=8.5)
    ax.xaxis.tick_top()
    for sp in ax.spines.values():
        sp.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    fig.suptitle('Correlação horária em 2030 (todas as horas e cenários)', x=0.01, ha='left', fontsize=13,
                 fontweight='bold')
    fig.text(0.01, 0.005, 'Carga = carga do SIN (hrload). Carga líquida = carga do SIN − renovável disponível no Brasil '
             '(geração + vertimento). Geração, vertimento e injeção = do estado. Estados com ≥ 50 GWh de vertimento.',
             fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    fig.savefig(os.path.join(saida, 'correlacoes.png'), dpi=130)
    plt.close(fig)

    if G is None:
        return
    top = sorted(lista, key=lambda u: -tot[u])[:11]
    fig, axs = plt.subplots(3, 4, figsize=(16, 11.5))
    for ax, nm in zip(axs.ravel(), ['BR'] + top):
        j = ufs.index(nm) if nm != 'BR' else None
        y = serie(V, j) / 1000
        ax.hexbin(liquida, y, gridsize=45, bins='log', mincnt=1, linewidths=0,
                  cmap=LinearSegmentedColormap.from_list('seq', [FUNDO, '#eb6834', '#3a1a08']))
        ax.axvline(0, color=TEXTO2, linewidth=0.8)
        ax.set_title(f'{"Brasil" if nm == "BR" else nm}  ·  r = {np.corrcoef(liquida, y)[0, 1]:+.2f}'.replace('.', ','),
                     loc='left', fontsize=10, fontweight='bold')
        ax.grid(color=GRADE, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.set_xlabel('Carga líquida do SIN (GW)')
        ax.set_ylabel('Vertimento (GW)')
    fig.suptitle('Vertimento × carga líquida do SIN, hora a hora (2030, 10 cenários)', x=0.01, ha='left',
                 fontsize=13, fontweight='bold')
    fig.text(0.01, 0.005, 'Carga líquida = carga do SIN − renovável disponível no Brasil (geração + vertimento). '
             'Cor = quantidade de horas (escala log).', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.015, 1, 0.96))
    fig.savefig(os.path.join(saida, 'carga_liquida_x_vertimento.png'), dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description='Dias úteis x fins de semana com dados do SDDP.')
    p.add_argument('pasta', help='pasta resultados_uf com os *_uf_horario.csv')
    p.add_argument('--caso', required=True, help='pasta do caso SDDP com os hrload??.dat')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--saida')
    a = p.parse_args()
    saida = a.saida or os.path.join(a.pasta, 'analise_semana')
    os.makedirs(saida, exist_ok=True)

    C = ler_carga(a.caso, a.ano)
    semanas = montar_semanas(C)
    with open(os.path.join(saida, 'semanas.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('mes,semana,dias_uteis,dias_fim_de_semana,carga_util_GW,carga_fds_GW\n')
        for s in semanas:
            cu = C[s['mes'], s['util']].mean() / 1000
            cf = C[s['mes'], s['fds']].mean() / 1000 if s['fds'] else float('nan')
            f.write(f'{s["mes"]},{s["num"]},"{" ".join(map(str, s["util"]))}","{" ".join(map(str, s["fds"]))}",'
                    f'{cu:.2f},{cf:.2f}\n')
    print(f'{len(semanas)} semanas; fins de semana: {sum(len(s["fds"]) for s in semanas)} dias')

    saidas = {}
    ufs = None
    for v in ('vergnd', 'gergnd', 'businj'):
        X, u = ler_saida(a.pasta, v, a.ano)
        if X is not None:
            saidas[v] = (X, u)
            ufs = ufs or u
            if u != ufs:
                sys.exit(f'ERRO: {v} tem estados diferentes dos outros arquivos')
    if 'vergnd' not in saidas:
        sys.exit(f'ERRO: não achei vergnd_uf_horario.csv em {a.pasta}')

    tipos = tipo_dos_dias(semanas)
    with open(os.path.join(saida, 'dias.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('mes,dia,semana,tipo_dia,carga_media_GW\n')
        for s_ in semanas:
            for d in sorted(s_['util'] + s_['fds']):
                f.write(f'{s_["mes"]},{d},{s_["num"]},{tipos[(s_["mes"], d)]},{C[s_["mes"], d].mean() / 1000:.2f}\n')

    # diário por estado e Brasil, para cada variável
    valores = []
    for v, (X, _) in saidas.items():
        for nm in ufs + ['BR']:
            if nm == 'BR' and v == 'businj':
                continue                      # a injeção do Brasil soma zero
            valores += grafico_diario(nm, ufs.index(nm) if nm != 'BR' else None, v, X, C, tipos, saida)
        print(f'Gráficos diários de {v}: ok')
    with open(os.path.join(saida, 'diario_valores.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,variavel,mes,dia,tipo_dia,cenario,valor\n')
        for nm, v, m, d, tp, c, val in valores:
            f.write(f'{nm},{v},{m},{d},{tp},{c},{val:.4f}\n')

    linhas = grafico_resumo(saidas, ufs, semanas, C, saida)
    print('Resumo: ok')
    correlacoes(saidas, ufs, C, saida)
    print('Correlações: ok')

    X, _ = saidas['vergnd']
    for nm in ['BR'] + ufs:
        grafico_horario(nm, ufs.index(nm) if nm != 'BR' else None, X, C, tipos, saida)
    print('Perfis horários mensais: ok')
    br = [l_ for l_ in linhas if l_[0] == 'BR'][0]
    print(f'Brasil: {br[1]:.1f} GWh/dia em dia útil x {br[2]:.1f} GWh/dia em fim de semana ({br[3]:+.1f}%)')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
