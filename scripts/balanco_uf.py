"""Balanço por estado nas horas de vertimento: o que estava gerando quando houve corte.

Para cada estado, hora e cenário do ano:
  renovável gerada  (gergnd_uf_horario.csv, da etapa 1)
  hidro gerada      (gerhid, por usina -> estado pela barra)
  térmica gerada    (gerter, por usina -> estado pela barra)
  carga             (demxba, por barra -> estado; igual em todos os cenários)
  injeção líquida   (businj_uf_horario.csv, da etapa 1)
  outros            = injeção - (renovável + hidro + térmica - carga): baterias, déficit e
                      arredondamentos (deve ser pequeno)
  vertimento        por gargalo e por excesso no sistema (gargalo_cmo, etapa 6)

e classifica cada hora do estado: com vertimento por gargalo / só com vertimento por
excesso (falta de demanda) / sem vertimento.

Hidrelétricas e térmicas ligadas à rede pelas unidades geradoras (hydrounit??.dat,
thermunit??.dat) entram pela barra das unidades.

Uso:
  python balanco_uf.py "<pasta do caso>" [--ano 2030]
Precisa: gerhid, gerter e demxba (.hdr/.bin) na pasta do caso; chidro??.dat, ctermi??.dat,
hydrounit??.dat e thermunit??.dat do deck; e, em <caso>\\resultados_uf, os resultados das
etapas 1 (gergnd/businj_uf_horario.csv) e 6 (gargalo_cmo).
Saída: <caso>\\resultados_uf\\balanco_uf
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import mes_ano                                              # noqa: E402
from gargalo_cmo import abrir, bloco, ler_tab                                     # noqa: E402
from gargalo_linhas import ler_horario_sddp, serie_ano, _caixas                   # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, MESES, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR = {'ren': '#1baf7a', 'hid': '#2a78d6', 'ter': '#eda100', 'out': '#8a8984',
       'garg': '#e34948', 'exc': '#c3c2b7', 'carga': TEXTO, 'inj': '#6250d6'}
ROT = {'ren': 'renovável gerada', 'hid': 'hidrelétrica', 'ter': 'termelétrica', 'out': 'outros (baterias, déficit)',
       'garg': 'vertimento por gargalo', 'exc': 'vertimento por excesso', 'carga': 'carga do estado',
       'inj': 'injeção líquida'}
SIT = [('garg', 'horas com vertimento por GARGALO'), ('exc', 'horas só com vertimento por EXCESSO (falta de demanda)'),
       ('sem', 'horas SEM vertimento')]


def barras_por_unidades(caso, cadastro, unidades):
    """Usinas ligadas pelas unidades geradoras: nome da usina -> lista de códigos de barra."""
    nomes = {}
    for arq in glob.glob(os.path.join(caso, f'{cadastro}??.dat')):
        sis = arq[-6:-4]
        with open(arq, encoding='latin-1') as f:
            for ln in f:
                if ln[:4].strip().isdigit():
                    nomes[(sis, int(ln[:4]))] = ln[5:17].strip()
    out = collections.defaultdict(list)
    for arq in glob.glob(os.path.join(caso, f'{unidades}??.dat')):
        sis = re.search(rf'{unidades}(..)\.dat$', arq).group(1)
        with open(arq, encoding='latin-1', newline='') as f:
            for r in csv.reader(f):
                if not r or r[0].startswith(('$', '!')):
                    continue
                try:
                    n = nomes.get((sis, int(r[2])))
                    if n:
                        out[n].append(int(r[3]))
                except (ValueError, IndexError):
                    continue
    return out


def main():
    p = argparse.ArgumentParser(description='Balanço por estado nas horas de vertimento.')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    a = p.parse_args()
    res = os.path.join(a.caso, 'resultados_uf')
    saida = a.saida or os.path.join(res, 'balanco_uf')
    os.makedirs(saida, exist_ok=True)

    print('Abrindo as saídas do SDDP...')
    hid, ter, dem = abrir(a.caso, 'gerhid'), abrir(a.caso, 'gerter'), abrir(a.caso, 'demxba')
    for h in (ter, dem):
        if h['horas'] != hid['horas']:
            sys.exit(f'ERRO: {h["nome"]} tem horas diferentes do gerhid (rodadas diferentes?)')
    estagios = [e for e in range(hid['n_estagios']) if mes_ano(hid, e)[1] == a.ano]
    if not estagios:
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}')
    n_cen = hid['n_cen']

    # --- resultados das etapas anteriores ---------------------------------------
    def csv_h(*nomes):
        for n in nomes:
            c = os.path.join(res, n)
            if os.path.exists(c):
                return ler_horario_sddp(c)
        sys.exit(f'ERRO: não achei {nomes[0]} em {res}. Rode antes as etapas anteriores.')
    ren_d = csv_h('gergnd_uf_horario.csv')
    inj_d = csv_h('businj_uf_horario.csv', 'bus_inj_uf_horario.csv')
    garg_d = csv_h(os.path.join('gargalo_cmo', 'vertimento_gargalo_uf_horario.csv'))
    exc_d = csv_h(os.path.join('gargalo_cmo', 'vertimento_excesso_uf_horario.csv'))

    # --- usina/barra -> estado ------------------------------------------------------
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    uf_cod = {int(b['codigo']): b['uf'] for b in barras}
    uf_nome = {b['nome']: b['uf'] for b in barras}
    conex = collections.defaultdict(list)
    for r in ler_tab(os.path.join(a.tabelas, 'conexoes_usinas_uf.csv')):
        conex[(r['tipo_usina'], r['nome_usina'])].append(int(r['barra']))
    unid = {'H': barras_por_unidades(a.caso, 'chidro', 'hydrounit'),
            'T': barras_por_unidades(a.caso, 'ctermi', 'thermunit')}
    ufs = ORDEM_UF

    def indicadora(h, tipo):
        M = np.zeros((h['n_agentes'], len(ufs)))
        sem = []
        for i, n in enumerate(h['nomes']):
            cods = [c for c in (conex.get((tipo, n)) or unid[tipo].get(n, [])) if c in uf_cod]
            if cods:
                u = collections.Counter(uf_cod[c] for c in cods).most_common(1)[0][0]
                M[i, ufs.index(u)] = 1
            else:
                sem.append(n)
        if sem:
            print(f'  AVISO: {len(sem)} usinas de {h["nome"]} sem barra (ficam fora do balanço): '
                  f'{", ".join(sem[:10])}{" ..." if len(sem) > 10 else ""}')
        return M
    M_hid, M_ter = indicadora(hid, 'H'), indicadora(ter, 'T')
    M_dem = np.zeros((dem['n_agentes'], len(ufs)))
    for i, n in enumerate(dem['nomes']):
        if uf_nome.get(n) in ufs:
            M_dem[i, ufs.index(uf_nome[n])] = 1

    # --- leitura das saídas por estado ------------------------------------------------
    agg = {k: {} for k in ('hid', 'ter', 'carga')}
    t0 = time.time()
    for e in estagios:
        D = bloco(dem, e, 0) * 1000.0 @ M_dem                          # carga (MW), igual nos cenários
        for c in range(n_cen):
            agg['hid'][(e, c)] = bloco(hid, e, c) * 1000.0 @ M_hid
            agg['ter'][(e, c)] = bloco(ter, e, c) * 1000.0 @ M_ter
            agg['carga'][(e, c)] = D
        print(f'  {MESES[mes_ano(hid, e)[0] - 1]}/{a.ano} ok - {time.time() - t0:.0f} s')

    def serie(chave, uf):
        if chave in agg:
            return serie_ano(agg[chave], estagios, n_cen, ufs.index(uf))[0]
        dic, cols = {'ren': ren_d, 'inj': inj_d, 'garg': garg_d, 'exc': exc_d}[chave]
        return serie_ano(dic, estagios, n_cen, cols.index(uf))[0] if uf in cols else None

    # --- por estado ---------------------------------------------------------------------
    resumo = []
    for uf in ufs:
        S = {k: serie(k, uf) for k in ('ren', 'hid', 'ter', 'carga', 'inj', 'garg', 'exc')}
        if any(v is None for v in S.values()):
            continue
        n = min(len(v) for v in S.values())
        S = {k: np.nan_to_num(v[:n]) for k, v in S.items()}
        _, hd, est = serie_ano(agg['hid'], estagios, n_cen, ufs.index(uf))
        hd, est = hd[:n], est[:n]
        S['out'] = S['inj'] - (S['ren'] + S['hid'] + S['ter'] - S['carga'])
        sit = {'garg': S['garg'] > 1}
        sit['exc'] = ~sit['garg'] & (S['exc'] > 1)
        sit['sem'] = ~sit['garg'] & ~sit['exc']
        for s_, _ in SIT:
            m = sit[s_]
            nh = m.sum()
            linha = dict(uf=uf, situacao=s_, pct_horas=round(100 * nh / n, 2))
            for k in ('ren', 'hid', 'ter', 'out', 'carga', 'inj', 'garg', 'exc'):
                linha[f'{k}_MW_medio'] = round(float(S[k][m].mean()), 1) if nh else ''
                linha[f'{k}_GWh_ano'] = round(float(S[k][m].sum()) / n_cen / 1000, 2)
            resumo.append(linha)
        if S['garg'].sum() + S['exc'].sum() <= 0:
            continue

        horas = np.arange(1, 25)
        fig = plt.figure(figsize=(16, 13.5))
        gs = fig.add_gridspec(3, 3, height_ratios=[1.15, 1, 1], hspace=0.5, wspace=0.18)
        # 1) balanço médio por hora (todas as horas)
        ax = fig.add_subplot(gs[0, :])

        def empilhado(ax, m, larg=0.8, legenda=False):
            base = np.zeros(24)
            # horas sem nenhum caso ficam em branco (NaN), em vez de aparecer como zero
            media = lambda v: np.array([v[m & (hd == h)].mean() if (m & (hd == h)).any() else np.nan for h in range(24)])
            for k in ('hid', 'ter', 'ren', 'garg', 'exc'):
                y = media(S[k])
                ax.bar(horas, np.nan_to_num(y), bottom=base, width=larg, color=COR[k], edgecolor=FUNDO, linewidth=0.6,
                       label=ROT[k] if legenda else None, hatch='//' if k in ('garg', 'exc') else None)
                base += np.nan_to_num(y)
            ax.plot(horas, media(S['carga']), color=COR['carga'], linewidth=2, marker='o', markersize=3,
                    label=ROT['carga'] if legenda else None)
            ax.plot(horas, media(S['inj']), color=COR['inj'], linewidth=1.6, linestyle='--',
                    label=ROT['inj'] + ' (geração − carga)' if legenda else None)
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
            ax.set_xticks(horas, [str(h) if h % 2 else '' for h in horas])
            ax.set_xlim(0.4, 24.6)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        empilhado(ax, np.ones(n, bool), legenda=True)
        ax.set_title('Média de todas as horas do ano (MW): geração por fonte + vertimento (hachurado) empilhados; '
                     'linha preta = carga; tracejado roxo = injeção líquida', loc='left', fontsize=10)
        ax.set_ylabel('MW')
        ax.legend(loc='upper left', fontsize=8, frameon=False, ncol=4, bbox_to_anchor=(0, -0.1))
        # 2) mesmo balanço separado pela situação da hora
        for j, (s_, rot) in enumerate(SIT):
            ax = fig.add_subplot(gs[1, j])
            empilhado(ax, sit[s_], larg=0.75)
            ax.set_title(f'{rot}\n({100 * sit[s_].mean():.1f}% das horas)'.replace('.', ','), loc='left', fontsize=9)
            if j == 0:
                ax.set_ylabel('MW médio')
        # 3) hidro e térmica conforme a situação da hora (box plot)
        for j, (k, rot) in enumerate((('ter', 'Termelétrica gerada'), ('hid', 'Hidrelétrica gerada'),
                                      ('out', 'Outros: baterias, déficit e diferenças'))):
            ax = fig.add_subplot(gs[2, j])
            for s_, cor, off in (('garg', COR['garg'], -0.27), ('exc', '#8a8984', 0.0), ('sem', '#2a78d6', 0.27)):
                grupos = [S[k][sit[s_] & (hd == h)] for h in range(24)]
                ok = [i for i, g_ in enumerate(grupos) if len(g_)]
                if ok:
                    _caixas(ax, [grupos[i] for i in ok], horas[ok] + off, cor, 0.24)
            ax.set_xticks(horas, [str(h) if h % 2 else '' for h in horas])
            ax.set_xlim(0.4, 24.6)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.set_title(f'{rot} (MW), conforme a situação da hora', loc='left', fontsize=9)
            ax.set_xlabel('Hora do dia')
            if j == 0:
                ax.set_ylabel('MW')
        from matplotlib.patches import Patch
        fig.legend(handles=[Patch(facecolor=COR['garg'] + '55', edgecolor=COR['garg'], label='horas com vertimento por gargalo'),
                            Patch(facecolor='#8a898455', edgecolor='#8a8984', label='horas só com vertimento por excesso'),
                            Patch(facecolor='#2a78d655', edgecolor='#2a78d6', label='horas sem vertimento')],
                   loc='lower right', ncol=3, fontsize=8.5, frameon=False, bbox_to_anchor=(0.99, 0.325))
        res_ = S['out']
        fig.suptitle(f'{uf} ({REGIAO_DA_UF.get(uf, "")}) — balanço do estado nas horas de vertimento, {a.ano}',
                     x=0.01, ha='left', fontsize=13, fontweight='bold')
        fig.text(0.01, 0.006, f'Médias e caixas com todas as horas do ano e os {n_cen} cenários. "Outros" = injeção − '
                 f'(renovável + hidro + térmica − carga): baterias, déficit e diferenças (média {res_.mean():.0f} MW, '
                 f'95% entre {np.percentile(res_, 2.5):.0f} e {np.percentile(res_, 97.5):.0f} MW).',
                 fontsize=7.5, color=TEXTO2)
        fig.subplots_adjust(left=0.05, right=0.99, top=0.94, bottom=0.06)
        fig.savefig(os.path.join(saida, f'balanco_{uf}.png'), dpi=115)
        plt.close(fig)

    with open(os.path.join(saida, 'balanco_situacao_uf.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        if resumo:
            w = csv.DictWriter(f, fieldnames=list(resumo[0].keys()))
            w.writeheader()
            w.writerows(resumo)

    # resumo: hidro e térmica nas horas com vertimento por gargalo e por excesso
    por_uf = collections.defaultdict(dict)
    for r in resumo:
        por_uf[r['uf']][r['situacao']] = r
    lista = [u for u in ufs if u in por_uf and por_uf[u]['garg']['garg_GWh_ano'] + por_uf[u]['exc']['exc_GWh_ano'] >= 50]
    if lista:
        lista = sorted(lista, key=lambda u: por_uf[u]['garg']['garg_GWh_ano'] + por_uf[u]['exc']['exc_GWh_ano'])
        fig, axs = plt.subplots(1, 2, figsize=(16, 0.42 * len(lista) + 2.4))
        y = np.arange(len(lista))
        for ax, (s_, rot) in zip(axs, SIT[:2]):
            ver = np.array([por_uf[u][s_][f'{s_}_GWh_ano'] for u in lista])
            te = np.array([por_uf[u][s_]['ter_GWh_ano'] for u in lista])
            hi = np.array([por_uf[u][s_]['hid_GWh_ano'] for u in lista])
            ax.barh(y + 0.27, ver, height=0.26, color=COR[s_ if s_ == 'garg' else 'exc'], edgecolor='#8a8984',
                    label=ROT['garg' if s_ == 'garg' else 'exc'])
            ax.barh(y, te, height=0.26, color=COR['ter'], label='termelétrica gerada nessas horas')
            ax.barh(y - 0.27, hi, height=0.26, color=COR['hid'], label='hidrelétrica gerada nessas horas')
            ax.set_yticks(y, lista)
            ax.set_xlabel('GWh no ano (média dos cenários)')
            ax.set_title(rot, loc='left', fontsize=10)
            ax.grid(axis='x', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.legend(loc='lower right', fontsize=8, frameon=False)
        fig.suptitle(f'Vertimento × geração hidrelétrica e termelétrica do próprio estado nas mesmas horas, {a.ano}',
                     x=0.01, ha='left', fontsize=13, fontweight='bold')
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        fig.savefig(os.path.join(saida, 'balanco_resumo.png'), dpi=130)
        plt.close(fig)
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
