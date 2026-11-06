# UF das barras elétricas – estudo_perdas_2025

Gerado por `scripts/barras_uf.py` a partir do caso SDDP (versão 18.0.11rc).

```
python scripts/barras_uf.py <pasta_do_caso> resultados/estudo_perdas_2025
```

Os CSV usam `;` como separador e UTF-8 com BOM, para abrir direto no Excel.

## Arquivos do SDDP usados

| Arquivo | Conteúdo |
|---|---|
| `dbus.dat` | Barras CA: código, nome, sistema, área, tensão |
| `ddcbus.dat` | Barras CC dos elos (numeração própria, repete códigos das barras CA) |
| `dcirc.dat`, `dtrans.dat`, `dseriescap.dat`, `dsvc.dat` | Linhas, transformadores, capacitores série e SVC (ligações entre barras) |
| `dcnvlcc.dat`, `ddcline.dat` | Conversores CA/CC e linhas CC |
| `dload.dat` | Cargas e a barra onde cada uma está conectada |
| `busconnection.dat` | Barra de conexão de cada usina (H = hidro, T = térmica, R = renovável) |
| `cgnd??.dat`, `chidro??.dat`, `ctermi??.dat` | Nomes das usinas renováveis, hidros e térmicas por sistema |
| `gcbus.dat` | Latitude/longitude de parte das barras |
| `sistem.dat`, `darea.dat` | Nomes dos sistemas e das áreas elétricas |

## Como a UF é identificada (coluna `metodo`)

1. **nome**: nome da barra no padrão ANAREDE `NOMEXX-UFkkk` (ex.: `S.BONF-BA138` = Senhor do Bonfim, BA, 138 kV). Cobre 81,7% das barras.
2. **usina**: barras de usina sem UF no nome (`...EOL034`, `...UFV034`...) recebem a UF que aparece no nome das usinas renováveis ligadas a elas (ex.: `EOLRN031759`). Cobre 10,1%.
3. **rede**: as barras restantes (UHE, UTE, compensadores síncronos `SIN`, `CAP`, `CER`...) recebem a UF predominante entre as barras vizinhas na rede, propagada a partir das barras já identificadas. Cobre 8,2%.
4. **conversor**: barras CC recebem a UF da barra CA do respectivo conversor.

Também existem os métodos de reserva `coord` (barra mais próxima por coordenadas) e `area` (UF predominante na área elétrica), mas neste caso nenhuma barra precisou deles.

### Validação

Cada método foi testado nas barras que têm UF no nome, escondendo essa UF e comparando com o resultado:

| Método | Acerto |
|---|---|
| rede (maioria dos vizinhos) | 98,9% |
| usina (UF no nome da usina) | 98,8% |
| área elétrica | 99,6% |
| coordenadas | 95,2% |

## Arquivos de saída

- `barras_uf.csv`: todas as barras (CA e CC) com UF, método, subsistema, área, tensão, coordenadas e número de ligações (`grau`).
- `cargas_uf.csv`: cada carga do `dload.dat` com a barra e a UF.
- `conexoes_usinas_uf.csv`: cada usina do `busconnection.dat` com a barra de conexão e a UF. Para renováveis, `uf_nome_usina` traz a UF do nome da usina e `uf` traz a UF da barra. Em 146 conexões as duas diferem, o que costuma indicar usina perto da divisa conectada em subestação do estado vizinho (ex.: `MMGDMG1921` → `JULIUS-RJ069`).
- `resumo_uf.csv`: contagem de barras, cargas e usinas (H/T/R) por UF.
