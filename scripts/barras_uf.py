"""Identifica a UF (estado) de cada barra elétrica de um caso SDDP.

Fontes, em ordem de prioridade:
  1. nome   - nome da barra no padrão ANAREDE "NOMEXX-UFkkk" (ex.: S.BONF-BA138)
  2. usina  - UF no nome das usinas renováveis ligadas à barra (busconnection.dat
              + cgnd??.dat, ex.: EOLRN031759 -> RN)
  3. rede   - maioria das UFs das barras vizinhas na rede (dcirc.dat), propagada
              em ondas a partir das barras já identificadas
  4. coord  - barra identificada mais próxima pelas coordenadas (gcbus.dat)
  5. area   - UF predominante na área elétrica (dbus.dat/darea.dat)

Uso: python barras_uf.py <pasta_do_caso> <pasta_saida>
Saídas: barras_uf.csv, cargas_uf.csv, conexoes_usinas_uf.csv, resumo_uf.csv
"""
import collections
import csv
import math
import os
import re
import sys

UFS = {'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG',
       'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'}
ENC = 'latin-1'


def ler_csv(caminho):
    """Lê um .dat no formato CSV do SDDP (pula linhas $ e !)."""
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding=ENC, newline='') as f:
        return [r for r in csv.reader(f) if r and not r[0].startswith(('$', '!'))]


def uf_do_nome_barra(nome):
    n = nome[:12].ljust(12)
    if n[6] == '-' and n[7:9] in UFS:
        return n[7:9]
    return None


def tipo_da_barra(nome):
    n = nome[:12].ljust(12)
    if n[6] == '-' and n[7:9] in UFS:
        return 'SE'  # barra de subestação
    return n[6:9].strip('-') or '?'


def uf_do_nome_usina(nome):
    # EOLRN031759, UFVPI049403, PCHMT028996, OMGDMT25732, MMGDDF22945 ...
    m = re.match(r'^(?:[A-Z]{3}|[MO]MGD)([A-Z]{2})\d', nome.strip())
    if m and m.group(1) in UFS:
        return m.group(1)
    return None


def main(caso, saida):
    os.makedirs(saida, exist_ok=True)

    # --- barras -------------------------------------------------------------
    barras = {}
    for r in ler_csv(os.path.join(caso, 'dbus.dat')):
        barras[int(r[0])] = dict(codigo=int(r[0]), nome=r[1].strip(), sistema=r[2],
                                 area=r[3], tensao_kv=r[6])
    for b in barras.values():
        b.update(tipo=tipo_da_barra(b['nome']), uf=None, metodo=None, lat='', lon='', rede='CA')
    # Barras CC (elos) têm numeração própria, que se repete com a das barras CA
    barras_cc = {}
    for r in ler_csv(os.path.join(caso, 'ddcbus.dat')):
        barras_cc[int(r[0])] = dict(codigo=int(r[0]), nome=r[1].strip(), sistema=r[3], area=r[4],
                                    tensao_kv=r[6], tipo='CC', uf=None, metodo=None, lat='',
                                    lon='', rede='CC')

    sistemas = {}
    with open(os.path.join(caso, 'sistem.dat'), encoding=ENC) as f:
        for ln in f:
            p = ln.split()
            if len(p) >= 3 and p[0].isdigit():
                sistemas[p[0]] = (p[-2], ' '.join(p[1:-2]))  # codigo -> (id, nome)
    id_para_cod = {v[0]: k for k, v in sistemas.items()}

    areas = {r[0]: r[1].strip() for r in ler_csv(os.path.join(caso, 'darea.dat'))}

    for r in ler_csv(os.path.join(caso, 'gcbus.dat')):
        if int(r[0]) in barras:
            barras[int(r[0])].update(lat=float(r[1]), lon=float(r[2]))

    # 1. nome da barra
    for b in barras.values():
        uf = uf_do_nome_barra(b['nome'])
        if uf:
            b.update(uf=uf, metodo='nome')

    # --- usinas renováveis (nome com UF) e conexões --------------------------
    usinas_ren = {}  # (sistema_id, codigo) -> nome
    for arq in sorted(os.listdir(caso)):
        m = re.match(r'^cgnd([a-z]{2})\.dat$', arq)
        if not m:
            continue
        with open(os.path.join(caso, arq), encoding=ENC) as f:
            for ln in f:
                if ln.startswith(('$', '!')) or not ln.strip():
                    continue
                usinas_ren[(m.group(1), int(ln[0:4]))] = ln[5:17].strip()

    def nomes_fixos(prefixo):
        """Lê nomes de hidros/térmicas dos arquivos de largura fixa."""
        d = {}
        for arq in sorted(os.listdir(caso)):
            m = re.match(rf'^{prefixo}([a-z]{{2}})\.dat$', arq)
            if not m:
                continue
            with open(os.path.join(caso, arq), encoding=ENC) as f:
                for ln in f:
                    if ln.startswith(('$', '!')) or not ln[:4].strip().isdigit():
                        continue
                    d[(m.group(1), int(ln[0:4]))] = ln[5:17].strip()
        return d

    usinas_hid = nomes_fixos('chidro')
    usinas_ter = nomes_fixos('ctermi')

    conexoes = []
    votos_usina = collections.defaultdict(collections.Counter)
    for r in ler_csv(os.path.join(caso, 'busconnection.dat')):
        sis, bus, tipo, cod = r[0], int(r[1]), r[2], int(r[3])
        nome = {'R': usinas_ren, 'H': usinas_hid, 'T': usinas_ter}.get(tipo, {}).get((sis, cod), '')
        conexoes.append(dict(sistema=sis, barra=bus, tipo_usina=tipo, cod_usina=cod, nome_usina=nome))
        uf = uf_do_nome_usina(nome) if tipo == 'R' else None
        if uf:
            votos_usina[bus][uf] += 1

    # 2. UF das usinas renováveis conectadas
    for bus, c in votos_usina.items():
        b = barras.get(bus)
        if b and not b['uf']:
            b.update(uf=c.most_common(1)[0][0], metodo='usina')

    # --- rede -----------------------------------------------------------------
    # linhas, transformadores, capacitores série e SVC (barra -> barra controlada)
    viz = collections.defaultdict(set)
    ligacoes = [('dcirc.dat', 2, 3), ('dtrans.dat', 2, 3), ('dseriescap.dat', 2, 3),
                ('dsvc.dat', 2, 3)]
    for arq, i, j in ligacoes:
        for r in ler_csv(os.path.join(caso, arq)):
            try:
                a, c = int(r[i]), int(r[j])
            except (ValueError, IndexError):
                continue
            if a in barras and c in barras and a != c:
                viz[a].add(c)
                viz[c].add(a)

    # 3. propagação pela rede
    def propagar():
        while True:
            novos = {}
            for k, b in barras.items():
                if b['uf']:
                    continue
                c = collections.Counter(barras[v]['uf'] for v in viz[k] if barras[v]['uf'])
                if c:
                    novos[k] = c.most_common(1)[0][0]
            if not novos:
                return
            for k, uf in novos.items():
                barras[k].update(uf=uf, metodo='rede')

    propagar()

    # 4. coordenadas (vizinho mais próximo entre as barras com UF pelo nome)
    ref = [(b['lat'], b['lon'], b['uf']) for b in barras.values()
           if b['metodo'] == 'nome' and b['lat'] != '']

    def mais_proxima(lat, lon):
        best = min(ref, key=lambda t: (t[0] - lat) ** 2 + ((t[1] - lon) * math.cos(math.radians(lat))) ** 2)
        return best[2]

    for b in barras.values():
        if not b['uf'] and b['lat'] != '':
            b.update(uf=mais_proxima(b['lat'], b['lon']), metodo='coord')
    propagar()

    # 5. área elétrica predominante (só áreas com >=90% das barras numa UF)
    por_area = collections.defaultdict(collections.Counter)
    for b in barras.values():
        if b['metodo'] == 'nome':
            por_area[b['area']][b['uf']] += 1
    area_uf = {}
    for a, c in por_area.items():
        uf, n = c.most_common(1)[0]
        if n / sum(c.values()) >= 0.9 and a not in ('998', '999'):
            area_uf[a] = uf
    for b in barras.values():
        if not b['uf'] and b['area'] in area_uf:
            b.update(uf=area_uf[b['area']], metodo='area')
    propagar()

    # --- barras CC: UF da barra CA do conversor, depois pelas linhas CC -------
    for r in ler_csv(os.path.join(caso, 'dcnvlcc.dat')):
        ca = barras.get(int(r[2]))
        for col in (3, 4):  # DCBusCode, GroundBusCode
            cc = barras_cc.get(int(r[col])) if r[col].strip() else None
            if ca and ca['uf'] and cc and not cc['uf']:
                cc.update(uf=ca['uf'], metodo='conversor')
    linhas_cc = [(int(r[2]), int(r[3])) for r in ler_csv(os.path.join(caso, 'ddcline.dat'))]
    for _ in range(len(barras_cc)):
        mudou = False
        for a, c in linhas_cc + [(c, a) for a, c in linhas_cc]:
            if a in barras_cc and c in barras_cc and barras_cc[a]['uf'] and not barras_cc[c]['uf']:
                barras_cc[c].update(uf=barras_cc[a]['uf'], metodo='rede')
                mudou = True
        if not mudou:
            break

    # --- validação: esconder a UF do nome e ver se os outros métodos acertam ---
    valid = collections.defaultdict(lambda: [0, 0])
    for k, b in barras.items():
        if b['metodo'] != 'nome':
            continue
        c = collections.Counter(barras[v]['uf'] for v in viz[k]
                                if barras[v]['metodo'] == 'nome')
        if c:
            valid['rede'][0] += c.most_common(1)[0][0] == b['uf']
            valid['rede'][1] += 1
    amostra = [b for b in barras.values() if b['metodo'] == 'nome' and b['lat'] != '']
    for b in amostra[::5]:  # leave-one-out numa amostra de 20%
        outros = [t for t in ref if not (t[0] == b['lat'] and t[1] == b['lon'])]
        if outros:
            best = min(outros, key=lambda t: (t[0] - b['lat']) ** 2 + ((t[1] - b['lon']) * math.cos(math.radians(b['lat']))) ** 2)
            valid['coord'][0] += best[2] == b['uf']
            valid['coord'][1] += 1
    for b in barras.values():
        if b['metodo'] == 'nome' and b['area'] in area_uf:
            valid['area'][0] += area_uf[b['area']] == b['uf']
            valid['area'][1] += 1
    for k, b in barras.items():
        if k in votos_usina and b['metodo'] == 'nome':
            valid['usina'][0] += votos_usina[k].most_common(1)[0][0] == b['uf']
            valid['usina'][1] += 1

    # --- saídas ---------------------------------------------------------------
    def escrever(nome, campos, linhas):
        with open(os.path.join(saida, nome), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=campos, delimiter=';', extrasaction='ignore')
            w.writeheader()
            w.writerows(linhas)

    for b in list(barras.values()) + list(barras_cc.values()):
        s = sistemas.get(b['sistema'], ('', ''))
        b.update(subsistema=s[1], nome_area=areas.get(b['area'], ''), uf=b['uf'] or '',
                 metodo=b['metodo'] or 'nao_identificada',
                 grau=len(viz[b['codigo']]) if b['rede'] == 'CA' else '')
    escrever('barras_uf.csv',
             ['rede', 'codigo', 'nome', 'tipo', 'tensao_kv', 'sistema', 'subsistema', 'area',
              'nome_area', 'uf', 'metodo', 'lat', 'lon', 'grau'],
             sorted(barras.values(), key=lambda b: b['codigo'])
             + sorted(barras_cc.values(), key=lambda b: b['codigo']))

    cargas = []
    for r in ler_csv(os.path.join(caso, 'dload.dat')):
        b = barras.get(int(r[4]), {})
        cargas.append(dict(codigo_carga=r[0], nome_carga=r[1].strip(), sistema=r[2], barra=r[4],
                           nome_barra=b.get('nome', ''), uf=b.get('uf', ''), metodo=b.get('metodo', '')))
    escrever('cargas_uf.csv', list(cargas[0].keys()) if cargas else [], cargas)

    for c in conexoes:
        b = barras.get(c['barra'], {})
        c.update(nome_barra=b.get('nome', ''), uf=b.get('uf', ''), metodo=b.get('metodo', ''),
                 uf_nome_usina=uf_do_nome_usina(c['nome_usina']) or '' if c['tipo_usina'] == 'R' else '')
    escrever('conexoes_usinas_uf.csv',
             ['sistema', 'tipo_usina', 'cod_usina', 'nome_usina', 'uf_nome_usina', 'barra',
              'nome_barra', 'uf', 'metodo'], conexoes)

    resumo = collections.defaultdict(collections.Counter)
    for b in barras.values():
        resumo[b['uf'] or '??']['barras'] += 1
    for c in cargas:
        resumo[c['uf'] or '??']['cargas'] += 1
    for c in conexoes:
        resumo[c['uf'] or '??']['usinas_' + c['tipo_usina']] += 1
    campos = ['uf', 'barras', 'cargas', 'usinas_H', 'usinas_T', 'usinas_R']
    escrever('resumo_uf.csv', campos,
             [dict(uf=u, **{k: resumo[u][k] for k in campos[1:]}) for u in sorted(resumo)])

    # --- relatório no terminal -------------------------------------------------
    print(f'Barras: {len(barras)} | ligações entre barras: {sum(len(v) for v in viz.values()) // 2}')
    print('Método de identificação (barras CA):')
    for m, n in collections.Counter(b['metodo'] for b in barras.values()).most_common():
        print(f'  {m:18s} {n:6d}  ({100 * n / len(barras):5.1f}%)')
    print('Barras CC:', dict(collections.Counter(b['metodo'] for b in barras_cc.values())))
    print('Validação (acerto contra a UF do nome):')
    for m, (ok, n) in valid.items():
        print(f'  {m:6s} {ok}/{n} = {100 * ok / max(n, 1):.1f}%')
    print(f'Cargas: {len(cargas)}, sem UF: {sum(1 for c in cargas if not c["uf"])}')
    print(f'Conexões de usinas: {len(conexoes)}, sem UF: {sum(1 for c in conexoes if not c["uf"])}')
    div = [c for c in conexoes if c['uf_nome_usina'] and c['uf'] and c['uf_nome_usina'] != c['uf']]
    print(f'Usinas renováveis cuja UF do nome difere da UF da barra: {len(div)}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
