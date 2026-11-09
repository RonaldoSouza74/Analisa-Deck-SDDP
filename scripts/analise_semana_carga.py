"""Dias úteis x fins de semana a partir apenas dos dados do SDDP.

Fins de semana: em cada semana de cada mês (dias 1-7, 8-14, 15-21, 22-28 e a
sobra 29-31), os 2 dias com menor carga horária média do SIN (soma dos
hrload??.dat do caso) são considerados sábado e domingo; os outros 5 são dias
úteis. Na sobra de 2 ou 3 dias, entra só o dia de menor carga (1 dia de fim de
semana); sobra de 1 dia conta como dia útil.

Nada é estimado: são usados só os valores horários de entrada (carga) e de
saída (vertimento, geração renovável e injeção nas barras) do SDDP. As médias
são feitas por semana: média dos dias úteis da semana e média dos dias de fim
de semana da semana, para cada cenário.

Gera, na pasta de saída:
  semanas.csv                        dias úteis e de fim de semana de cada semana
  semanal_<UF ou BR>.png             por semana: vertimento, geração e injeção
                                     (box plot dos cenários) e carga do SIN (linhas)
  semanal_valores.csv                os valores semanais por estado, cenário e tipo de dia
  resumo_util_fds.png / .csv         média do ano: dia útil x fim de semana por estado
  horario/<UF>/<UF>_<mm>.png         por mês: perfil horário de cada semana, vertimento
                                     (box plot) e carga (linhas), dia útil x fim de semana
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


def media_semana(X, sem, tipo, energia):
    """Por cenário: média diária dos dias do tipo na semana. X: [cen, mês, dia, hora, ...]."""
    dias = sem[tipo]
    if not dias:
        return None
    bloco = X[:, sem['mes'], dias]                       # [cen, dias, hora, ...]
    diario = bloco.sum(axis=2) / 1000 if energia else bloco.mean(axis=2)   # GWh/dia ou MW
    return diario.mean(axis=1)                            # [cen, ...]


def perfil_semana(X, sem, tipo):
    """Por cenário: perfil horário médio (MW) dos dias do tipo na semana."""
    dias = sem[tipo]
    if not dias:
        return None
    return X[:, sem['mes'], dias].mean(axis=1)            # [cen, hora, ...]


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


def _eixo_semanas(ax, semanas):
    ax.set_xticks(range(len(semanas)), [s['rotulo'] if s['num'] == 1 else f'S{s["num"]}' for s in semanas],
                  fontsize=7, rotation=90)
    for i, s in enumerate(semanas):
        if s['num'] == 1 and i:
            ax.axvline(i - 0.5, color=GRADE, linewidth=1)
    ax.set_xlim(-0.7, len(semanas) - 0.3)
    ax.grid(axis='y', color=GRADE, linewidth=0.6)
    ax.set_axisbelow(True)


def grafico_semanal(nome, j, saidas, C, semanas, saida):
    vars_ = [v for v in ('vergnd', 'gergnd', 'businj') if v in saidas]
    fig, axs = plt.subplots(len(vars_) + 1, 1, figsize=(19, 3.3 * (len(vars_) + 1) + 0.8), sharex=True)
    x = np.arange(len(semanas))
    resumo = []
    for ax, v in zip(axs, vars_):
        X, _ = saidas[v]
        energia = v != 'businj'
        Xe = X[..., j] if j is not None else X.sum(axis=-1)
        if v == 'businj' and j is None:
            continue
        util = [media_semana(Xe, s, 'util', energia) for s in semanas]
        fds = [media_semana(Xe, s, 'fds', energia) for s in semanas]
        _caixas(ax, util, x - 0.2, COR_UTIL, 0.34)
        _caixas(ax, fds, x + 0.2, COR_FDS, 0.34)
        if v == 'businj':
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
        tit, un = VAR_INFO[v]
        ax.set_title(f'{tit} ({un}) — caixa = 10 cenários (mínimo a máximo)', loc='left', fontsize=10)
        ax.set_ylabel(un)
        _eixo_semanas(ax, semanas)
        resumo.append((v, util, fds))
    if j is None and 'businj' in vars_:   # Brasil: injeção soma zero, painel removido
        axs[len(vars_) - 1].remove()
    ax = axs[-1]
    cu = [C[s['mes'], s['util']].mean() / 1000 for s in semanas]
    cf = [C[s['mes'], s['fds']].mean() / 1000 if s['fds'] else np.nan for s in semanas]
    ax.plot(x, cu, color=COR_UTIL, linewidth=1.8, marker='o', markersize=3.5, label='dias úteis (5 dias)')
    ax.plot(x, cf, color=COR_FDS, linewidth=1.8, marker='o', markersize=3.5, label='fim de semana (2 dias de menor carga)')
    ax.set_title('Carga do SIN (GW médio, entrada do SDDP — igual em todos os cenários)', loc='left', fontsize=10)
    ax.set_ylabel('GW')
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(facecolor=COR_UTIL + '66', edgecolor=COR_UTIL, label='dias úteis (5 dias da semana)'),
                        Patch(facecolor=COR_FDS + '66', edgecolor=COR_FDS,
                              label='fim de semana (2 dias de menor carga da semana)')],
               loc='upper right', ncol=2, fontsize=9, frameon=False, bbox_to_anchor=(0.995, 0.995))
    _eixo_semanas(ax, semanas)
    titulo = 'Brasil' if j is None else f'{nome} ({REGIAO_DA_UF[nome]})'
    fig.suptitle(f'{titulo} — dias úteis (azul) × fim de semana (laranja), semana a semana, 2030',
                 x=0.01, ha='left', fontsize=13, fontweight='bold')
    fig.text(0.01, 0.004, 'Fim de semana = os 2 dias de menor carga do SIN em cada semana do mês (dias 1-7, 8-14, ...; '
             'na sobra 29-31, o dia de menor carga). Valores médios por dia em cada grupo.', fontsize=8, color=TEXTO2)
    fig.tight_layout(rect=(0, 0.012, 1, 0.97))
    fig.savefig(os.path.join(saida, f'semanal_{nome}.png'), dpi=120)
    plt.close(fig)
    return resumo


def grafico_horario(nome, j, X, C, semanas, saida):
    pasta = os.path.join(saida, 'horario', nome)
    os.makedirs(pasta, exist_ok=True)
    Xe = X[..., j] if j is not None else X.sum(axis=-1)
    horas = np.arange(1, 25)
    for m in range(1, 13):
        sems = [s for s in semanas if s['mes'] == m]
        fig = plt.figure(figsize=(16, 4.4 * len(sems) + 1.0))
        gs = fig.add_gridspec(len(sems) * 3, 1, height_ratios=[2.2, 1, 0.55] * len(sems), hspace=0.12)
        ymax = np.nanmax(Xe[:, m]) * 1.02 if np.nanmax(Xe[:, m]) > 0 else 1
        cmin, cmax = C[m, 1:DIAS_MES[m - 1] + 1].min() / 1000, C[m, 1:DIAS_MES[m - 1] + 1].max() / 1000
        for k, s in enumerate(sems):
            ax = fig.add_subplot(gs[3 * k])
            axc = fig.add_subplot(gs[3 * k + 1], sharex=ax)
            pu, pf = perfil_semana(Xe, s, 'util'), perfil_semana(Xe, s, 'fds')
            if pu is not None:
                _caixas(ax, [pu[:, h] for h in range(24)], horas - 0.18, COR_UTIL, 0.32)
            if pf is not None:
                _caixas(ax, [pf[:, h] for h in range(24)], horas + 0.18, COR_FDS, 0.32)
            ax.set_ylim(0, ymax)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.set_ylabel('Vertim. (MW)')
            dias_u = ','.join(str(x) for x in s['util'])
            dias_f = ','.join(str(x) for x in s['fds']) or '—'
            ax.set_title(f'{MESES[m - 1]} semana {s["num"]} — dias úteis: {dias_u} · fim de semana: {dias_f}',
                         loc='left', fontsize=10, fontweight='bold')
            plt.setp(ax.get_xticklabels(), visible=False)
            axc.plot(horas, C[m, s['util']].mean(axis=0) / 1000, color=COR_UTIL, linewidth=1.8, marker='o',
                     markersize=3, label='carga dias úteis')
            if s['fds']:
                axc.plot(horas, C[m, s['fds']].mean(axis=0) / 1000, color=COR_FDS, linewidth=1.8, marker='o',
                         markersize=3, label='carga fim de semana')
            axc.set_ylim(cmin * 0.97, cmax * 1.03)
            axc.set_ylabel('Carga SIN (GW)')
            axc.grid(color=GRADE, linewidth=0.6)
            axc.set_axisbelow(True)
            axc.set_xticks(horas)
            axc.set_xlim(0.4, 24.6)
            if k == 0:
                axc.legend(loc='lower right', fontsize=8, frameon=False, ncol=2)
        for axc_ in fig.axes[1::2]:
            axc_.set_xlabel('Hora do dia (1 = 00h-01h)', fontsize=8)
        titulo = 'Brasil' if j is None else nome
        fig.suptitle(f'{titulo} — vertimento por hora (caixa = 10 cenários, azul = dias úteis, laranja = fim de semana) '
                     f'e carga do SIN, {MESES[m - 1]}/2030', x=0.01, ha='left', fontsize=12, fontweight='bold')
        fig.subplots_adjust(left=0.06, right=0.99, top=1 - 0.95 / fig.get_figheight(),
                            bottom=0.1 / fig.get_figheight())
        fig.savefig(os.path.join(pasta, f'{nome}_{m:02d}.png'), dpi=110)
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
    p.add_argument('--horario-min-gwh', type=float, default=1000,
                   help='gera perfis horários mensais só para estados com vertimento anual ≥ este valor (GWh)')
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

    # semanal por estado e Brasil
    valores = []
    for nm in ufs + ['BR']:
        j = ufs.index(nm) if nm != 'BR' else None
        res = grafico_semanal(nm, j, saidas, C, semanas, saida)
        for v, util, fds in res:
            for s, u_, f_ in zip(semanas, util, fds):
                for tipo, arr in (('util', u_), ('fds', f_)):
                    if arr is not None:
                        for c, val in enumerate(arr):
                            valores.append((nm, v, s['mes'], s['num'], tipo, c + 1, val))
    with open(os.path.join(saida, 'semanal_valores.csv'), 'w', encoding='utf-8-sig') as f:
        f.write('uf,variavel,mes,semana,tipo_dia,cenario,valor\n')
        for nm, v, m, k, tipo, c, val in valores:
            f.write(f'{nm},{v},{m},{k},{tipo},{c},{val:.4f}\n')
    print('Gráficos semanais: ok')

    linhas = grafico_resumo(saidas, ufs, semanas, C, saida)
    print('Resumo: ok')
    correlacoes(saidas, ufs, C, saida)
    print('Correlações: ok')

    X, _ = saidas['vergnd']
    anual = {u: np.nansum(X[..., j]) / X.shape[0] / 1000 for j, u in enumerate(ufs)}
    lista = ['BR'] + [u for u in ufs if anual[u] >= a.horario_min_gwh]
    for nm in lista:
        grafico_horario(nm, ufs.index(nm) if nm != 'BR' else None, X, C, semanas, saida)
        print(f'Perfis horários mensais: {nm} ok')
    br = [l_ for l_ in linhas if l_[0] == 'BR'][0]
    print(f'Brasil: {br[1]:.1f} GWh/dia em dia útil x {br[2]:.1f} GWh/dia em fim de semana ({br[3]:+.1f}%)')
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
