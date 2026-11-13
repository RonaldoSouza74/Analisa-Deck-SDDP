"""Relação entre vertimento, injeção, CMO e linhas/transformadores no limite, por estado.

Um gráfico por estado, com a hora do dia (1 a 24) no eixo x e três colunas, uma para cada
situação da hora no estado:
  horas com vertimento por GARGALO | horas só com vertimento por EXCESSO | horas SEM vertimento

Linhas do gráfico:
  1) vertimento por gargalo e por excesso (MW médio);
  2) injeção líquida do estado (MW, positivo = exporta): mediana e faixa 5%-95%;
  3) CMO ($/MWh): do estado (mediana das barras), do SIN (mediana de todas as barras) e dos
     estados vizinhos para onde ele pode exportar (os de maior capacidade de divisa);
  4) para cada linha/transformador que mais limita o estado (de gargalo_linhas.py): fluxo real
     do SDDP em MW (mediana e faixa 5%-95%, positivo = saindo do estado ou do lado preso) e o
     limite físico do deck: Rating/Rn (tracejado) e EmergencyRating/Re (pontilhado), nos dois
     sentidos.

Rode antes, para o mesmo caso: agrega_saidas_uf.py (etapa 1), limites_uf.py (etapa 2),
gargalo_cmo.py e gargalo_linhas.py.

Uso:
  python relacao_gargalo.py "<pasta do caso>" [--ano 2030] [--circuitos 4]
Saída: <caso>\\resultados_uf\\relacao_gargalo
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agrega_saidas_uf import mes_ano                                                  # noqa: E402
from gargalo_cmo import abrir, bloco, ler_tab                                         # noqa: E402
from gargalo_linhas import circuitos_do_ano, ler_horario_sddp, serie_ano              # noqa: E402
from graficos_uf import ORDEM_UF, REGIAO_DA_UF, TEXTO, TEXTO2, GRADE, FUNDO, plt, np  # noqa: E402

COR_GARG, COR_EXC, COR_INJ, COR_UF, COR_SIN = '#e34948', '#8a8984', '#6250d6', '#2a78d6', TEXTO
COR_VIZ = ['#eb6834', '#1baf7a', '#eda100']
SITS = [('garg', 'Horas com vertimento por GARGALO'), ('exc', 'Horas só com vertimento por EXCESSO (falta de demanda)'),
        ('sem', 'Horas SEM vertimento')]


def faixa(ax, horas, v, hd, m, cor, rot=None, largura=2.0, banda=True, estilo='-'):
    """Mediana por hora (linha) e faixa 5%-95% (sombra) dos valores v nas horas da máscara m."""
    med, p5, p95 = (np.full(24, np.nan) for _ in range(3))
    for h in range(24):
        x = v[m & (hd == h)]
        x = x[np.isfinite(x)]
        if len(x):
            med[h], p5[h], p95[h] = np.median(x), np.percentile(x, 5), np.percentile(x, 95)
    if banda:
        ax.fill_between(horas, p5, p95, color=cor, alpha=0.15, linewidth=0)
    ax.plot(horas, med, color=cor, linewidth=largura, linestyle=estilo, label=rot)
    return med


def main():
    p = argparse.ArgumentParser(description='Vertimento x injeção x CMO x linhas no limite, por estado.')
    p.add_argument('caso')
    p.add_argument('--ano', type=int, default=2030)
    p.add_argument('--circuitos', type=int, default=4, help='quantas linhas/trafos mostrar por estado (padrão 4)')
    p.add_argument('--tabelas', default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument('--saida')
    a = p.parse_args()
    res = os.path.join(a.caso, 'resultados_uf')
    saida = a.saida or os.path.join(res, 'relacao_gargalo')
    os.makedirs(saida, exist_ok=True)

    def precisa(*partes):
        c = os.path.join(res, *partes)
        if not os.path.exists(c):
            sys.exit(f'ERRO: não achei {c}. Rode antes as etapas anteriores (gargalo_cmo / gargalo_linhas).')
        return c
    garg = ler_horario_sddp(precisa('gargalo_cmo', 'vertimento_gargalo_uf_horario.csv'))
    exc = ler_horario_sddp(precisa('gargalo_cmo', 'vertimento_excesso_uf_horario.csv'))
    cmo = ler_horario_sddp(precisa('gargalo_cmo', 'cmo_uf_horario.csv'))
    arq_inj = next((os.path.join(res, n) for n in ('businj_uf_horario.csv', 'bus_inj_uf_horario.csv')
                    if os.path.exists(os.path.join(res, n))), None)
    inj = ler_horario_sddp(arq_inj) if arq_inj else ({}, [])
    with open(precisa('gargalo_linhas', 'circuitos_no_limite.csv'), encoding='utf-8-sig', newline='') as f:
        lim_csv = list(csv.DictReader(f))
    pares = []
    arq_p = os.path.join(res, 'limites_pares_uf.csv')
    if os.path.exists(arq_p):
        with open(arq_p, encoding='utf-8-sig', newline='') as f:
            pares = list(csv.DictReader(f))
    else:
        print('  AVISO: limites_pares_uf.csv não encontrado (etapa 2); sem CMO dos estados vizinhos')

    print('Abrindo as saídas do SDDP...')
    fl = {'linha': abrir(a.caso, 'acline_flow'), 'trafo': abrir(a.caso, 'transformer_flow', obrigatorio=False)}
    ref = fl['linha']
    estagios = [e for e in range(ref['n_estagios']) if mes_ano(ref, e)[1] == a.ano]
    if not estagios:
        sys.exit(f'ERRO: a rodada não tem estágios de {a.ano}')
    n_cen = ref['n_cen']
    circ = circuitos_do_ano(a.caso, a.ano)
    barras = [b for b in ler_tab(os.path.join(a.tabelas, 'barras_uf.csv')) if b['rede'] == 'CA']
    uf_cod = {int(b['codigo']): b['uf'] for b in barras}
    col = {t: {n: i for i, n in enumerate(h['nomes'])} for t, h in fl.items() if h is not None}

    # --- circuitos de cada estado ---------------------------------------------------
    escolha = {}
    for uf in ORDEM_UF:
        cand = [r for r in lim_csv if r['monitorado'] == '1' and uf in (r['uf_de'], r['uf_para'])]
        cand.sort(key=lambda r: (float(r['vertimento_gargalo_coincidente_GWh'] or 0) * (r['uf_lado_preso'] == uf),
                                 float(r['pct_horas_no_limite'] or 0)), reverse=True)
        lst = []
        for r in cand[:a.circuitos]:
            t = 'linha' if r['tipo'] == 'linha' else 'trafo'
            ci = circ.get((t, r['nome']))
            if ci is None or t not in col or r['nome'] not in col[t]:
                continue
            ude, upa = uf_cod.get(ci['de'], '??'), uf_cod.get(ci['para'], '??')
            # sentido positivo: saindo do estado (divisa) ou saindo do lado preso (dentro do estado)
            if ude != upa:
                sinal = 1 if ude == uf else -1
            else:
                sinal = 1
            lst.append(dict(tipo=t, nome=r['nome'], col=col[t][r['nome']], sinal=sinal, ude=ude, upa=upa,
                            limite=ci['limite'], emerg=ci.get('emergencia', float('nan')),
                            pct=float(r['pct_horas_no_limite'] or 0), preso=r['uf_lado_preso']))
        escolha[uf] = lst

    # --- leitura dos fluxos só dos circuitos escolhidos --------------------------------
    sel = {t: sorted({d['col'] for lst in escolha.values() for d in lst if d['tipo'] == t}) for t in col}
    fluxos = {t: {} for t in sel}
    t0 = time.time()
    for e in estagios:
        for c in range(n_cen):
            for t, cols in sel.items():
                if cols:
                    fluxos[t][(e, c)] = bloco(fl[t], e, c)[:, cols]
        print(f'  estágio {e + 1} ok - {time.time() - t0:.0f} s')
    pos = {t: {k: i for i, k in enumerate(sel[t])} for t in sel}

    def serie_circ(d):
        dic = fluxos[d['tipo']]
        j = pos[d['tipo']][d['col']]
        return np.concatenate([dic[(e, c)][:, j] for e in estagios for c in range(n_cen)]) * d['sinal']

    horas = np.arange(1, 25)
    linhas_csv = []
    ocorrencias = {}       # UF -> {situação: % das ocorrências de cada hora}
    for uf in ORDEM_UF:
        if uf not in garg[1]:
            continue
        g, hd, _ = serie_ano(garg[0], estagios, n_cen, garg[1].index(uf))
        x = serie_ano(exc[0], estagios, n_cen, exc[1].index(uf))[0]
        if g is None or x is None or (np.nansum(g) + np.nansum(x)) <= 0:
            continue
        g, x = np.nan_to_num(g), np.nan_to_num(x)
        sit = {'garg': g > 1}
        sit['exc'] = ~sit['garg'] & (x > 1)
        sit['sem'] = ~sit['garg'] & ~sit['exc']
        inj_v = serie_ano(inj[0], estagios, n_cen, inj[1].index(uf))[0] if uf in inj[1] else None
        cmo_uf = serie_ano(cmo[0], estagios, n_cen, cmo[1].index(uf))[0] if uf in cmo[1] else None
        cmo_sin = serie_ano(cmo[0], estagios, n_cen, cmo[1].index('SIN'))[0] if 'SIN' in cmo[1] else None
        viz = []
        for r in pares:
            if uf in (r['uf_a'], r['uf_b']):
                outro = r['uf_b'] if r['uf_a'] == uf else r['uf_a']
                cap = float(r['capacidade_CA_MW'] or 0) + float(r['capacidade_CC_a_para_b_MW'] or 0)
                viz.append((cap, outro))
        viz = [u for _, u in sorted(viz, reverse=True) if u in cmo[1]][:3]
        cmo_viz = {u: serie_ano(cmo[0], estagios, n_cen, cmo[1].index(u))[0] for u in viz}
        circs = escolha.get(uf, [])
        F = {d['nome']: serie_circ(d) for d in circs}

        n_lin = 4 + len(circs)
        cont_h = {s_: np.array([(sit[s_] & (hd == h)).sum() for h in range(24)]) for s_, _ in SITS}
        tot_h = sum(cont_h.values())
        ocorrencias[uf] = {s_: 100 * cont_h[s_] / np.maximum(tot_h, 1) for s_ in cont_h}
        fig, axs = plt.subplots(n_lin, 3, figsize=(19, 2.9 * n_lin + 1.4), sharex=True, sharey='row', squeeze=False)
        for j, (s_, rot_s) in enumerate(SITS):
            m = sit[s_]
            ph = 100 * m.mean()
            # 0) número de ocorrências (dias x cenários) de cada hora nesta situação
            ax = axs[0, j]
            cor_oc = {'garg': COR_GARG, 'exc': COR_EXC, 'sem': COR_UF}[s_]
            ax.bar(horas, cont_h[s_], color=cor_oc, width=0.75)
            for h in range(24):
                if cont_h[s_][h]:
                    ax.text(h + 1, cont_h[s_][h], f'{100 * cont_h[s_][h] / max(tot_h[h], 1):.0f}%', ha='center',
                            va='bottom', fontsize=6, color=TEXTO2)
            ax.set_title(f'{rot_s}\n({ph:.1f}% das horas do ano)'.replace('.', ','), loc='left', fontsize=10,
                         fontweight='bold')
            # 1) vertimento
            ax = axs[1, j]
            mg = np.array([g[m & (hd == h)].mean() if (m & (hd == h)).any() else np.nan for h in range(24)])
            mx = np.array([x[m & (hd == h)].mean() if (m & (hd == h)).any() else np.nan for h in range(24)])
            ax.bar(horas, np.nan_to_num(mg), color=COR_GARG, width=0.75, label='vertimento por gargalo')
            ax.bar(horas, np.nan_to_num(mx), bottom=np.nan_to_num(mg), color=COR_EXC, width=0.75,
                   label='vertimento por excesso')
            # 2) injeção
            ax = axs[2, j]
            if inj_v is not None:
                faixa(ax, horas, inj_v, hd, m, COR_INJ, 'injeção líquida do estado')
            ax.axhline(0, color=TEXTO2, linewidth=0.8)
            # 3) CMO
            ax = axs[3, j]
            if cmo_sin is not None:
                faixa(ax, horas, cmo_sin, hd, m, COR_SIN, 'SIN (mediana das barras)', largura=1.6, banda=False,
                      estilo='--')
            for k, u in enumerate(viz):
                faixa(ax, horas, cmo_viz[u], hd, m, COR_VIZ[k], f'vizinho: {u}', largura=1.3, banda=False)
            if cmo_uf is not None:
                faixa(ax, horas, cmo_uf, hd, m, COR_UF, f'{uf} (mediana das barras)', largura=2.2)
            # 4) circuitos
            for i, d in enumerate(circs):
                ax = axs[4 + i, j]
                v = F[d['nome']]
                faixa(ax, horas, v, hd, m, COR_UF, 'fluxo real (mediana; faixa 5-95%)')
                for y, est in ((d['limite'], '--'), (-d['limite'], '--')):
                    ax.axhline(y, color=TEXTO, linewidth=1.2, linestyle=est)
                if np.isfinite(d['emerg']) and 0 < d['emerg'] < 99999 and d['emerg'] != d['limite']:
                    for y in (d['emerg'], -d['emerg']):
                        ax.axhline(y, color=TEXTO2, linewidth=1, linestyle=':')
                ax.axhline(0, color=TEXTO2, linewidth=0.6)
                lim_m = np.abs(v[m]) >= 0.99 * d['limite'] if m.any() else np.array([False])
                ax.text(0.01, 0.97, f'{100 * lim_m.mean():.1f}% destas horas no limite'.replace('.', ','),
                        transform=ax.transAxes, va='top', fontsize=8, color=TEXTO2)
                if j == 0:
                    sentido = (f'+ = saindo de {uf}' if d['ude'] != d['upa'] else f'+ = de {d["ude"]} (barra "de") '
                               f'para a barra "para"')
                    ax.set_ylabel('MW')
                    ax.set_title(f'{d["nome"][:40]} ({d["ude"]}-{d["upa"]}) · limite {d["limite"]:,.0f} MW · '
                                 f'{sentido}'.replace(',', '.'), loc='left', fontsize=8.5)
        # rótulos e legendas
        axs[0, 0].set_ylabel('ocorrências')
        axs[1, 0].set_title('Vertimento médio nessas horas (MW) — vermelho: gargalo · cinza: excesso nas mesmas horas',
                            loc='left', fontsize=8.5)
        axs[1, 0].set_ylabel('MW')
        axs[2, 0].set_ylabel('MW')
        axs[3, 0].set_ylabel('$/MWh')
        axs[2, 0].set_title('Injeção líquida do estado (MW, positivo = exporta) — mediana e faixa 5-95%',
                            loc='left', fontsize=8.5)
        axs[3, 0].set_title('CMO ($/MWh) — estado, SIN e vizinhos (medianas); faixa = 5-95% do estado',
                            loc='left', fontsize=8.5)
        axs[1, 2].legend(loc='upper right', fontsize=7.5, frameon=False)
        axs[3, 2].legend(loc='upper right', fontsize=7.5, frameon=False)
        if circs:
            from matplotlib.lines import Line2D
            axs[4, 2].legend(handles=[Line2D([], [], color=COR_UF, linewidth=2, label='fluxo real (mediana; faixa 5-95%)'),
                                      Line2D([], [], color=TEXTO, linewidth=1.2, linestyle='--',
                                             label='limite físico normal (Rating/Rn)'),
                                      Line2D([], [], color=TEXTO2, linewidth=1, linestyle=':',
                                             label='limite de emergência')],
                             loc='upper right', fontsize=7.5, frameon=False)
        for ax in axs.ravel():
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
            ax.set_xticks(horas, [str(h) if h % 2 else '' for h in horas])
            ax.set_xlim(0.4, 24.6)
        for ax in axs[-1]:
            ax.set_xlabel('Hora do dia (1 = 00h-01h)')
        fig.suptitle(f'{uf} ({REGIAO_DA_UF.get(uf, "")}) — vertimento, injeção, CMO e linhas no limite por situação '
                     f'da hora, {a.ano}', x=0.01, y=1 - 0.25 / fig.get_figheight(), ha='left', fontsize=13,
                     fontweight='bold')
        fig.text(0.01, 0.004, f'Todas as horas do ano e os {n_cen} cenários, separadas pela situação do estado em cada '
                 'hora. Fluxos e limites físicos das linhas/trafos que mais limitam o estado (gargalo_linhas).',
                 fontsize=7.5, color=TEXTO2)
        fig.subplots_adjust(left=0.05, right=0.99, top=1 - 0.95 / fig.get_figheight(),
                            bottom=0.65 / fig.get_figheight(), hspace=0.45, wspace=0.06)
        fig.savefig(os.path.join(saida, f'relacao_{uf}.png'), dpi=110)
        plt.close(fig)

        # tabela: medianas por situação e hora
        for s_, _ in SITS:
            m = sit[s_]
            for h in range(24):
                mh = m & (hd == h)
                if not mh.any():
                    continue
                lin = dict(uf=uf, situacao=s_, hora=h + 1, n_horas=int(mh.sum()),
                           vert_gargalo_MW=round(float(g[mh].mean()), 1), vert_excesso_MW=round(float(x[mh].mean()), 1),
                           injecao_MW=round(float(np.median(inj_v[mh])), 1) if inj_v is not None else '',
                           cmo_estado=round(float(np.nanmedian(cmo_uf[mh])), 2) if cmo_uf is not None else '',
                           cmo_sin=round(float(np.nanmedian(cmo_sin[mh])), 2) if cmo_sin is not None else '')
                for k, u in enumerate(viz):
                    lin[f'vizinho{k + 1}_uf'] = u
                    lin[f'vizinho{k + 1}_cmo'] = round(float(np.nanmedian(cmo_viz[u][mh])), 2)
                for k, d in enumerate(circs):
                    v = F[d['nome']][mh]
                    lin[f'circ{k + 1}_nome'] = d['nome']
                    lin[f'circ{k + 1}_limite_MW'] = round(d['limite'], 1)
                    lin[f'circ{k + 1}_fluxo_mediano_MW'] = round(float(np.median(v)), 1)
                    lin[f'circ{k + 1}_pct_horas_no_limite'] = round(100 * float((np.abs(v) >= 0.99 * d['limite']).mean()), 1)
                linhas_csv.append(lin)
        print(f'  {uf} ok')

    # visão geral: % das ocorrências de cada hora em cada situação, todos os estados
    if ocorrencias:
        ufs_o = [u for u in ORDEM_UF if u in ocorrencias]
        ncol = 4
        nlin = int(np.ceil(len(ufs_o) / ncol))
        fig, axs = plt.subplots(nlin, ncol, figsize=(16, 2.6 * nlin + 1.2), sharex=True, sharey=True, squeeze=False)
        for k, uf in enumerate(ufs_o):
            ax = axs.ravel()[k]
            base = np.zeros(24)
            for s_, cor in (('garg', COR_GARG), ('exc', COR_EXC), ('sem', '#c9dcf3')):
                v = ocorrencias[uf][s_]
                ax.bar(horas, v, bottom=base, color=cor, width=0.85, edgecolor=FUNDO, linewidth=0.5)
                base += v
            pg = ocorrencias[uf]['garg'].mean()
            ax.set_title(f'{uf} · gargalo em {pg:.1f}% das horas'.replace('.', ','), loc='left', fontsize=9.5,
                         fontweight='bold')
            ax.set_ylim(0, 100)
            ax.set_xticks(horas, [str(h) if h % 4 == 1 else '' for h in horas], fontsize=7)
            ax.grid(axis='y', color=GRADE, linewidth=0.6)
            ax.set_axisbelow(True)
        for ax in axs.ravel()[len(ufs_o):]:
            ax.axis('off')
        for ax in axs[:, 0]:
            ax.set_ylabel('% das ocorrências')
        from matplotlib.patches import Patch
        fig.legend(handles=[Patch(color=COR_GARG, label='com vertimento por gargalo'),
                            Patch(color=COR_EXC, label='só com vertimento por excesso (falta de demanda)'),
                            Patch(color='#c9dcf3', label='sem vertimento')],
                   loc='upper right', ncol=3, fontsize=9, frameon=False, bbox_to_anchor=(0.995, 0.995))
        fig.suptitle(f'Em que situação cada hora do dia ocorreu, por estado, {a.ano}', x=0.01, ha='left', fontsize=13,
                     fontweight='bold')
        dias = sum(ref['horas'][e + 1] - ref['horas'][e] for e in estagios) // 24
        fig.text(0.01, 0.004, f'Para cada hora do dia, as ocorrências são os {dias} dias × {n_cen} cenários; a barra mostra '
                 'quanto % delas caiu em cada situação. Números absolutos em relacao_por_hora.csv (coluna n_horas).',
                 fontsize=8, color=TEXTO2)
        fig.tight_layout(rect=(0, 0.015, 1, 1 - 0.6 / fig.get_figheight()))
        fig.savefig(os.path.join(saida, 'ocorrencias_estados.png'), dpi=120)
        plt.close(fig)

    if linhas_csv:
        campos = []
        for l_ in linhas_csv:
            for k in l_:
                if k not in campos:
                    campos.append(k)
        with open(os.path.join(saida, 'relacao_por_hora.csv'), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(linhas_csv)
    print('Fim. Arquivos em', saida)


if __name__ == '__main__':
    main()
