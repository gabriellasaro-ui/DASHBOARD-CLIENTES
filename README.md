# Dashboard de Performance

Dashboard multi-tenant para clientes de agência: Meta Ads e Google Ads na
mesma tela, autenticação persistida e identidade visual por cliente, feito em
**Python com Dash, Flask e PostgreSQL**.

Usuários, clientes, identidade visual e os vínculos das contas de mídia são
persistidos no schema PostgreSQL isolado `dashboard_clientes`. Os números vêm
das APIs oficiais **Meta Marketing API v25.0** e **Google Ads API v25**.

Gráficos em **Chart.js** (servido localmente em `assets/`). JavaScript escrito
à mão, só dois arquivos pequenos: `assets/50-charts.js`, que traduz a
especificação gerada em Python (`ui/charts.py`) para o Chart.js, e
`assets/60-theme-sync.js`, que espelha o tema do cliente no documento inteiro
(fundo da página e barras de rolagem) ao navegar sem recarregar.

---

## Rodar

```bash
pip install -r requirements.txt
python app.py
```

Abre em **http://127.0.0.1:8050**. Sem Node, sem build, sem `npm install`.

O sincronizador sobe junto: `python app.py` já mantém o ciclo de Meta/Google
rodando numa thread. Não é preciso um segundo terminal — antes, esquecer dele
deixava cliente novo zerado sem nenhum aviso.

Em hospedagem onde a sincronização é um serviço à parte, desligue a embutida e
use o processo dedicado:

```bash
ADS_SYNC_EMBEDDED=false python app.py
python sync_worker.py --interval 600
```

O dashboard lê somente `media_daily_metrics` no PostgreSQL. O worker consulta
Meta/Google a cada 10 minutos, atualiza os últimos 14 dias e completa o
histórico retroativamente em blocos de 60 dias. O intervalo e as janelas são
configuráveis por `ADS_SYNC_INTERVAL_SECONDS`, `ADS_SYNC_REFRESH_DAYS` e
`ADS_SYNC_BACKFILL_DAYS`.

Cadastrar um cliente ou trocar as contas vinculadas não espera pelo ciclo: o
painel dispara uma primeira carga de 30 dias na hora.

Para regravar o histórico inteiro (por exemplo, depois de uma correção na
coleta), com o painel fechado:

```bash
python sync_worker.py --rebuild 550
```

Armadilhas das APIs já tratadas na coleta:

- **Meta** — pedir `actions` junto com `spend` na quebra diária faz a API
  devolver gasto e impressões zerados em algumas contas, sem erro. Entrega e
  ações são buscadas em consultas separadas e juntadas por dia.
- **Meta, intermitente** — mesmo assim, de vez em quando a quebra diária volta
  zerada. Antes de gravar, a soma dos dias é conferida contra o total agregado
  do período; se não fechar após 3 tentativas, a sincronização falha e os dados
  anteriores ficam no banco.
- **Alcance** — a Meta não informa alcance por dia, e alcance não se soma entre
  dias. O alcance de cada período é consultado agregado e guardado em
  `media_period_reach` (período recente revalida a cada hora). A frequência é
  impressões ÷ esse alcance.
- **Google** — o total da conta vem do recurso `customer`, não da soma das
  campanhas, para incluir o gasto de campanhas removidas.

O primeiro acesso administrativo local é:

```text
Usuário: admin
Senha:   admin
```

Em qualquer ambiente compartilhado, configure `PULSE_SECRET_KEY`,
`PULSE_ADMIN_EMAIL` e `PULSE_ADMIN_PASSWORD` antes da primeira execução.
Copie `.env.example` para `.env`, configure `DATABASE_URL` e preencha também
as credenciais das APIs.
O arquivo `.env` está ignorado pelo Git.

---

## Produção (VPS com Docker)

```bash
# na VPS, na pasta do projeto, com o .env copiado
docker compose up -d --build
docker compose ps            # web "healthy" em alguns segundos
docker compose logs -f web sync
```

O painel fica em **http://IP-DA-VPS:7000**. São dois containers da mesma imagem:

| Serviço | O que faz |
|---|---|
| `web` | gunicorn na porta 7000 (2 processos x 8 threads, ajustável por `WEB_WORKERS`/`WEB_THREADS`) |
| `sync` | `sync_worker.py` a cada 10 min — o único processo que consulta Meta e Google |

O banco é o PostgreSQL do `DATABASE_URL`; nenhum dado fica nos containers.
O container roda em `America/Sao_Paulo` (o "ontem" dos períodos depende disso).

Antes de expor a porta:

1. **`PULSE_SECRET_KEY` no `.env`** — o compose não sobe sem ela.
2. **Troque a senha do master.** `PULSE_ADMIN_PASSWORD` só vale na primeira
   criação do usuário; se o banco já tem `admin`/`admin`, troque assim:

   ```bash
   docker compose exec web python -c "import getpass; from core import storage; u = storage.authenticate('admin', 'admin'); storage.set_user_password(u['id'], getpass.getpass('Nova senha do master: ')); print('senha trocada')"
   ```

3. Com domínio e HTTPS (nginx/Caddy na frente), ligue `PULSE_TRUST_PROXY=true`
   e `PULSE_COOKIE_SECURE=true`.

Atualizar a versão: copie o código novo e rode `docker compose up -d --build`.
Regravar o histórico (com o `sync` parado, para não consultarem as APIs em dobro):
`docker compose stop sync && docker compose run --rm sync python sync_worker.py --rebuild 550 && docker compose start sync`.

## Telas

| Rota | Tela | O que tem |
|---|---|---|
| `/login` | Login | Uma coluna com a marca do cliente (via `?next=/slug`), e-mail, senha com botão de mostrar e "manter conectado" |
| `/registro` | Registro | Desativado por padrão; pode ser habilitado explicitamente por ambiente |
| `/admin` | Administração | Cria clientes, acessos, identidade e vínculos Meta/Google |
| `/aparencia` | Aparência | O responsável do cliente muda logo, cores, fontes e tema do painel da empresa; o visualizador só vê quem pode mudar |
| `/` | Dashboard | Faixa de métricas selecionáveis, 4 gráficos, funil e a tabela de campanhas |
| `/meta-ads` | Meta Ads | 11 KPIs da plataforma, gráfico diário, painel de destaques, tabelas de campanhas / conjuntos / anúncios |
| `/google-ads` | Google Ads | 11 KPIs (inclui IS, Top IS, Search IS e Quality Score), painel de leilão, tabelas de campanhas / grupos / palavras-chave / anúncios |
| `/campanhas` | Campanhas | A tabela completa, com resumo no topo |

---

## Controles da topbar

- **Período** — Hoje, Ontem, Últimos 7/30/90 dias, Últimos 6 meses, Este mês
  e Este ano. As janelas "Últimos N dias" **terminam ontem**, como no
  Gerenciador da Meta e no Google Ads; Hoje, Este mês e Este ano incluem o dia
  corrente.
- **Métricas** — escolhe quais dos 12 indicadores aparecem na faixa do
  dashboard. A escolha fica salva no navegador (`localStorage`) e o menu
  **não fecha** a cada marcação, porque escolher métricas é uma tarefa de
  várias marcações seguidas.
- **Conta** — no acesso master, troca o tenant efetivo sem expor essa escolha ao cliente.
- **Atualizar** — busca agora os últimos 3 dias na Meta e no Google e refaz a
  tela. Sem clique, a tela só se refaz sozinha quando o worker grava dado novo.

A sidebar abre compacta, mostrando apenas ícones. O controle logo abaixo da
marca expande o menu para 232px; no celular ela continua funcionando como
gaveta completa.

### As 12 métricas

Investimento · Receita · CPA · CPL · Leads · CTR · CPM · CPC ·
Impressões · Alcance · Cliques · Sessões

Foram retiradas do produto: margem, lucro, pedidos, ticket médio, taxa de
conversão, conversões, CAC e **ROAS**.

**Conversões e ROAS saíram de tudo**, não só da faixa de KPIs:

| O que tinha | O que ficou no lugar |
|---|---|
| Gráfico "ROAS por dia" | **Custo por lead** por dia |
| Coluna ROAS (com barra) nas 8 tabelas | **Receita** (com a barra de proporção) |
| Coluna Conversões e CPA nas tabelas | saíram; sobrou Leads e CPL |
| Destaques "Maior ROAS" / "Pior campanha por ROAS" | **Menor CPL** / **Pior campanha** pelo lead mais caro |
| Funil terminando em Vendas | funil termina em **Leads** |
| Card "ROAS consolidado" em Campanhas | **CPL médio** |

> Uma tensão que vale registrar: **CPA continua** como card de métrica (não
> estava na lista de remoções), mas conversões — o denominador dele — sumiu da
> interface. Se quiser coerência total, o caminho é retirar CPA também e
> deixar só CPL, que tem o denominador visível. O CPA ainda é calculado a
> partir das conversões retornadas pelas APIs, embora o total de conversões
> não apareça como card.

---

## Estrutura

```
app.py                    shell, rotas e as callbacks globais
requirements.txt

data/
  pulse.db                backend isolado usado somente nos testes locais

assets/                   carregado automaticamente pelo Dash, em ordem alfabética
  00-tokens.css           ← cores, raio, sombra, tipografia, movimento
  10-base.css             reset e hierarquia tipográfica
  20-components.css       card, badge, botão, campo, popover, paginação…
  30-layout.css           shell, sidebar, topbar, grades, tabela, funil, login
  40-responsive.css       breakpoints
  00-chart.umd.js         Chart.js 4.4.1
  50-charts.js            desenha os gráficos a partir do atributo data-chart
  60-theme-sync.js        leva o tema do #app-root para o <html> (fundo, rolagem)

core/
  auth.py                 sessão, usuário atual e autorização
  branding.py             tokens de cor dinâmicos por tenant
  tenant_theme.py         tema completo do cliente (fontes, cores, cantos, temas prontos)
  storage.py              PostgreSQL em produção e SQLite isolado nos testes
  sync.py                 coleta centralizada e gravação diária das APIs
  integrations.py         clientes REST da Meta e do Google Ads
  data.py                 normalização, consolidação, cache e contrato das telas
  mock.py                 constantes e gerador legado, sem dados exibidos em produção
  fmt.py                  formatação pt-BR (R$, %, datas, compactos)
  theme.py                paleta dos gráficos (cores por papel e por cliente)

ui/
  icons.py                ícones Lucide oficiais, embutidos como data-URI
  primitives.py           card, badge, botão, campo, avatar, empty state…
  kpi.py                  os cards de métrica + sparkline
  charts.py               especificações dos gráficos (Chart.js) e o funil
  tables.py               tabela com ordenação, busca e paginação
  shell.py                sidebar, topbar, filtro de período, seletor de métricas
  theme_editor.py         editor de aparência do /admin, com prévia ao vivo

pages/                    uma tela por arquivo (auto-registradas pelo Dash)
  login.py                autenticação por e-mail e senha
  registro.py             criação pública opcional, desativada por padrão
  admin.py                painel master de clientes e identidade visual
```

`sync_worker.py` guarda o ciclo de sincronização, usado tanto pela thread do
`app.py` quanto pelo comando avulso. Só uma instância trabalha por vez: as duas
disputam o mesmo lock local e quem chega depois desiste em silêncio.

---

## Aparência por cliente

No detalhe do cliente em `/admin`, a seção **Aparência do painel** define:

- **Fonte do texto** e **fonte dos títulos** (catálogo do Google Fonts, cada uma
  exibida nela mesma na lista);
- **Cor do texto**, **cor de fundo**, **cor dos cards** e **cor do menu lateral**;
- **Cantos**: retos, suaves ou arredondados;
- **Temas prontos** (Claro, Gelo, Areia, Menu escuro, Grafite, Escuro,
  Azul-noite) que preenchem as cores, ajustáveis depois.

O responsável do cliente faz o mesmo sozinho em `/aparencia` (logo, cores da
marca e tema; nome, endereço e contas continuam só no admin).

Uma prévia ao vivo mostra o painel com o tema, usando os mesmos tokens do
painel real. Tudo o mais é derivado em `core/tenant_theme.py`: tons de texto,
linhas, superfícies, sombras, modo claro/escuro e a tinta do menu (que sai da
cor do menu, para um menu escuro nunca ter texto escuro). As séries dos
gráficos são corrigidas contra a cor dos cards. Texto com contraste abaixo de
4,5:1 sobre o fundo ou os cards não é salvo. O tema fica em
`tenants.theme_data` (JSON).

## Autenticação e tenants

- Senhas são armazenadas somente como hash pelo Werkzeug.
- Produção usa apenas `dashboard_clientes.tenants` e
  `dashboard_clientes.users`; nenhum schema anterior é alterado.
- Cada usuário de cliente pertence a um único `tenant_id`.
- O administrador master não pertence a tenant, vê `/admin` e pode abrir os
  dashboards de qualquer cliente usando o seletor do topo.
- O cliente é fixado ao próprio `tenant_id`; IDs enviados pelo navegador não
  alteram o tenant efetivo.
- Cada conta Meta ou Google só pode estar vinculada a um tenant por vez.
- Clientes inativos não conseguem iniciar ou manter uma sessão.
- Logo, nome e cores são carregados novamente do banco a cada abertura da
  aplicação; uma alteração no admin aparece para o cliente no próximo reload.
- Logos aceitas: PNG, JPG ou WEBP de até 1,5 MB.
- O cadastro público fica desativado por padrão. A criação normal de clientes
  é feita pelo master em `/admin`.

### A tela `/admin`

Dois estados, nunca os dois ao mesmo tempo:

- **Lista** — todos os clientes numa tabela, com um **lápis** por linha e um
  botão *Novo cliente* no topo.
- **Detalhe** — abre no lápis e ocupa a tela: dados do cliente, identidade
  visual, contas de mídia, status e acessos, em coluna única.

O desenho anterior mantinha três formulários visíveis em paralelo (criar,
editar, acessos) mais um seletor de cliente separado da tabela — dava para
começar a editar o cliente errado. Agora o cliente é escolhido clicando nele,
e tudo que aparece depois é sobre ele. **Formulário só existe quando há um
alvo.**

Detalhes de comportamento:

- Salvar identidade e mexer em acessos são ações independentes: gerar um
  convite **não** redesenha o formulário de identidade, então nada que estiver
  digitado se perde.
- Criar um cliente abre direto o detalhe dele — o passo seguinte quase sempre
  é convidar alguém ou conferir a marca.
- Trocar de tela limpa o aviso da anterior: "Cliente criado" pairando sobre
  outro cliente seria informação errada.
- O estado da tela mora num `dcc.Store`, que vive no navegador. Valor
  adulterado ou corrompido cai na lista em vez de virar erro 500
  (`_as_view` em `pages/admin.py`).

### Acessos de um cliente

Um cliente pode ter várias pessoas. Tudo fica na seção **Acessos**, dentro do
detalhe do cliente:

| Ação | Como funciona |
|---|---|
| **Convidar pessoa** | Gera um link `/convite?token=…`, válido por 7 dias. O convidado abre, define a **própria senha** e já entra. |
| **Redefinir senha** | Define uma nova senha para um acesso existente. |
| **Ativar / desativar** | Suspende o login sem apagar o histórico da pessoa. |
| **Entrar como** | O master passa a ver o painel exatamente como aquela pessoa vê. |

O **e-mail do responsável** é editável no mesmo lugar: trocá-lo move o login
na hora, e o e-mail antigo deixa de autenticar.

Dois perfis: **Responsável** (`client_admin`) e **Visualizador** (`client`).

Regras que o banco garante, não só a tela:

- **Todo cliente mantém pelo menos um responsável ativo.** Rebaixar ou
  desativar o último é recusado — sem isso o ambiente ficaria sem ninguém
  para administrá-lo.
- **Um convite pendente por e-mail.** Convidar de novo substitui o link
  anterior, então não ficam dois links válidos circulando.
- **Convite é de uso único** e traz o e-mail travado: ele autoriza aquela
  pessoa, não qualquer uma que receba o link.
- Trocar o e-mail do responsável **move o login**: o antigo deixa de
  autenticar na hora.

Não há envio de e-mail configurado. O convite é um **link que o administrador
copia e envia** pelo canal que preferir — de propósito: senha provisória
transmitida por mensagem é a que vaza e nunca é trocada.

### Simulação de acesso ("Entrar como")

O master já enxergava os dados de qualquer cliente pelo seletor de contas. A
simulação serve para ver a **interface** como o cliente vê: sem o menu de
administração, com a marca e as permissões dele.

- Uma faixa preta fixa no topo avisa que a simulação está ativa e traz o
  caminho de volta. Sem ela, é fácil concluir que "o admin sumiu do menu".
- O id do administrador fica guardado à parte na sessão, então o retorno
  sempre existe.
- Um cliente que tente acessar `/entrar-como/...` é barrado.

---

## Design system

### Cores

Tudo sai de `assets/00-tokens.css`. Nenhum hexadecimal aparece solto no resto
do CSS.

| Papel | Token | Valor |
|---|---|---|
| Fundo da aplicação | `--plane` | `#FFFFFF` |
| Card | `--surface` | `#FFFFFF` |
| Sidebar | `--surface-tint` | `#FAFAFB` |
| Borda | `--line` | `#E6E7EA` |
| Texto principal | `--ink` | `#0B0B0D` |
| Texto secundário | `--ink-secondary` | `#52565E` |
| **Marca / ação** | `--brand` | `#E5001A` |
| Positivo | `--positive` | `#16A34A` |
| Negativo | `--negative` | `#E5001A` |
| Atenção | `--warning` | `#B45309` |

Duas decisões que valem explicação:

- **Um vermelho só.** O mesmo `#E5001A` serve para ação (botão, item ativo) e
  para variação negativa. Dois vermelhos quase iguais confundiriam mais do que
  ajudariam, e a direção nunca depende da cor: vem sempre com seta e sinal.
- **Amarelo puro não vira texto.** `#FACC15` tem 1,4:1 no branco — ilegível.
  O tom de atenção é o âmbar escuro `#B45309`, com 5:1.

### Whitelabel: a cor do cliente governa tudo

A cor escolhida em `/admin` **não pinta só o botão**. `core/branding.py`
deriva dela uma paleta inteira, e ela chega em:

| Onde | Como |
|---|---|
| Botões, item ativo, foco, links | `--brand` e derivados |
| **Favicon** | logo do cliente; sem logo, um quadrado com a inicial na cor da marca |
| **Tela de login** | resolvida pelo slug em `/login?next=/cliente` — antes de existir sessão |
| **Séries dos gráficos** | a marca vira a série 1; as outras duas são escolhidas por separação medida |
| **Sparkline dos KPIs** | traço e ponto final na cor da marca |
| **Rampa do funil** | matiz única derivada da marca |
| **Marcador de canal nas tabelas** | mesma paleta das séries |

As cores vão no `<head>` por `interpolate_index`, e não só no elemento raiz:
um `<style>` aplicado antes da primeira pintura evita a tela piscar no
vermelho padrão antes de virar a cor do cliente.

**Três coisas que a cor do cliente deliberadamente NÃO governa:**

1. **As três séries não viram todas a mesma cor.** Um gráfico de três linhas
   precisa de três matizes distinguíveis. A marca é a série 1; as companheiras
   saem de um conjunto de dez candidatas, escolhendo o par que **maximiza a
   menor separação do trio**, medida em ΔE OKLab sobre visão normal **e** as
   três dicromacias. Distância de matiz não serve: rosa e verde-azulado ficam
   a 150° um do outro e mesmo assim colapsam sob deuteranopia (ΔE 4,1).
2. **Verde e vermelho de status ficam fixos.** Marca verde não pode fazer
   "caiu 8%" aparecer em verde.
3. **Grade e eixos continuam cinza recessivo** em qualquer marca.

**Duas correções automáticas**, porque o cliente escolhe a cor da marca dele,
não a cor de um gráfico:

- **Contraste.** Marca clara é ilegível como traço de 2px no branco. Para
  DADO a cor é escurecida no mesmo matiz até passar de 3:1; para BOTÃO a
  original é mantida, porque ali o texto é branco por cima e o cálculo é
  outro. Exemplo real: `#0FD7FF` (1,72:1) vira `#009DBC` (3,21:1) no gráfico
  e segue ciano vivo no botão.
- **Marca sem matiz.** Preto ou cinza não conseguem ser identidade num
  gráfico — ao lado de outra série leem como "sem cor". A série 1 cai para um
  azul e o funil usa rampa neutra; o preto segue mandando em botão, menu e
  favicon. Sem isso, uma marca preta produzia um funil **azul**.

Dez marcas de teste (incluindo amarelo, lima, ciano, preto e rosa) passam o
validador de paleta em todos os pares. As garantias estão fixadas em
`tests/test_access_and_branding.py`.

### Gráfico personalizável

O card **Desempenho** do dashboard é montado pelo cliente: botão
*Personalizar* → escolhe as métricas e a cor de cada uma. A escolha fica
salva no navegador (`localStorage`).

Métricas disponíveis: Investimento, CPL, CPC, CPM, Leads, Cliques,
Impressões, Alcance e CTR.

**A regra de um eixo continua valendo, e é ela que decide o modo:**

| Seleção | Como é plotado |
|---|---|
| Mesma unidade (só R$, ou só contagens) | valores absolutos, um eixo |
| Unidades diferentes (ex.: investimento + CTR) | tudo indexado em **base 100** no primeiro dia |

Base 100 é a alternativa documentada ao segundo eixo: com duas escalas, duas
curvas parecem se cruzar sem se cruzarem, e a leitura fica errada. Indexado,
o que se compara é o **ritmo** de variação. O tooltip mostra sempre o valor
real — ninguém quer saber que algo está em "112 pontos de base".

Duas proteções: a última métrica não pode ser desmarcada (gráfico vazio não
tem caminho de volta óbvio), e a configuração é higienizada na leitura, já
que vem do navegador.

### Receita saiu do produto

Não há mais métrica, coluna, gráfico nem destaque de receita. A barra de
proporção das tabelas migrou para **Investimento**, e o destaque "melhor
campanha" passou a ser por **volume de leads**.

A receita **continua sendo ingerida** da Meta e do Google e gravada no banco
— ela só não aparece em lugar nenhum da interface. Voltar a exibi-la é
recolocar a entrada em `METRICS` (`core/data.py`).

### Regras seguidas em todos os gráficos

- **Um eixo Y só.** Nunca dois eixos com escalas diferentes. Investimento e
  receita dividem o mesmo eixo porque são a mesma unidade — a distância entre
  as curvas é literalmente a margem bruta.
- **Grade só na horizontal**, 1px, sólida. Vertical vira ruído.
- **Legenda em HTML, fora do gráfico**, com quadradinho de cor + nome + valor:
  a identidade da série nunca depende só da cor.
- **Rótulo seletivo.** Número em cima de cada ponto não é lido; o eixo, a
  legenda e o tooltip carregam o resto.
- **A cor segue a entidade, nunca o ranking.** Filtrar uma campanha não
  repinta as outras.

### Outros parâmetros

- **Tipografia:** Inter (400 / 500 / 600 / 700). `tabular-nums` só em coluna
  de tabela e eixo — em número grande deixa o valor frouxo.
- **Raio:** 18px nos cards, 10px nos controles.
- **Movimento:** 250ms com `cubic-bezier(0.22, 0.61, 0.36, 1)`. Hover de KPI
  cresce 2%. Nada além disso.
- **Ícones:** Lucide oficial (pacote `lucide-static`), embutido como data-URI
  e aplicado via `mask-image` com `currentColor` — o ícone herda a cor do
  texto, então hover e estado ativo saem de graça.

### Responsividade

Mobile-first. Cada breakpoint só **acrescenta** colunas, nunca desfaz o
anterior.

| Largura | Grade de KPI | Sidebar |
|---|---|---|
| < 480px | 2 colunas | gaveta |
| ≥ 480px | 3 colunas | gaveta |
| ≥ 768px | 4 colunas | gaveta |
| ≥ 1024px | 4 colunas | fixa |
| ≥ 1280px | 5 colunas | fixa |

Abaixo de 640px a sparkline dos KPIs some — fica ilegível antes de ficar útil.

---

## Integrações de mídia

As integrações usam chamadas somente de leitura e mantêm as credenciais da
agência no ambiente. O banco recebe apenas `meta_ad_account_id` e
`google_ads_customer_id` por tenant.

- Meta: `META_ADS_ACCESS_TOKEN` e `META_ADS_API_VERSION=v25.0`.
- Google: OAuth 2.0, developer token e `GOOGLE_ADS_API_VERSION=v25`.
- MCC: `GOOGLE_ADS_LOGIN_CUSTOMER_ID` é enviado como `login-customer-id`; o
  `customer_id` operacional é sempre o cliente escolhido no admin.
- O refresh token gera access tokens curtos automaticamente.
- Período atual e anterior são consultados para calcular as variações.
- Campanhas, conjuntos/grupos, palavras-chave e anúncios são normalizados no
  mesmo contrato consumido pela interface.
- Se uma plataforma não estiver vinculada ou falhar, a outra continua
  funcionando e a tela mostra o estado da conexão.

O dicionário devolvido por `core.data.get_dataset(period_id)` mantém este
formato:

```python
{
  "period":  {"id", "label", "days", "compare"},
  "range":   {"start", "end"},               # ISO
  "series":  [{"date", "investimento", "receita", "impressoes", "cliques",
               "leads", "conversoes", "cpl", "cpc",
               "receita_acumulada"}, ...],
  "totals":  {...},                          # as métricas agregadas
  "previous":{...},                          # mesmas chaves, período anterior
  "kpis":    [{"key", "label", "icon", "type", "good",
               "value", "variation", "spark"}, ...],
  "channels":[{"key", "nome", "valor"}, ...],
  "funnel":  [{"etapa", "valor", "taxa", "do_topo"}, ...],
  "campaigns": [...],
  "meta":    {"metrics", "campaigns", "adsets", "ads", "highlights", "series"},
  "google":  {"metrics", "campaigns", "groups", "keywords", "ads", "series"},
}
```

O campo `good` (`"up"` / `"down"` / `"neutral"`) é o que faz o CPA subindo 12%
aparecer com seta **vermelha** — sem ele, todo número que cresce parece boa
notícia. Investimento fica em cinza: subir não é bom nem ruim. Receita depende
dos valores de conversão enviados a cada plataforma; sem esse tracking ela
aparece como zero, sem estimativa inventada.

---

## Notas de implementação

- **Popovers sem JavaScript.** Todo menu já nasce no HTML com a classe `hide`;
  abrir é trocar classe. O clique-fora é um `scrim` transparente em tela
  cheia atrás do menu. Nada é criado ou destruído — se o elemento não
  existisse, a callback que escuta o clique dele não teria como ser acionada.
- **`min-width: 0` nos itens da grade.** Item de grade nasce com
  `min-width: auto`, ou seja, nunca fica menor que o conteúdo. O SVG do Plotly
  tem largura mínima própria, então sem isso o card estoura a coluna e passa
  por cima do vizinho — era a causa dos cards sobrepostos.
- **O container do gráfico recebe a mesma altura declarada na figura**, e o
  template usa `automargin=False` com margens explícitas. Sem isso o Plotly
  recalcula a própria caixa e escapa do card.
- **A busca da tabela enxerga o canal**, não só o nome. As campanhas se
  chamam `[GAD] …` e `[MET] …`, e ninguém digita "GAD" — digita "google".
- **Criativos da Meta são buscados em lote, pelos ids.** Pedir
  `{conta}/ads` inteiro fazia a Meta recusar com *"Please reduce the amount
  of data you're asking for"* em conta com muitos anúncios — o limite é do
  TAMANHO da resposta, e a expansão de `creative` é pesada. Agora vai em
  lotes de 40 e, se ainda assim a API reclamar, o lote se divide pela metade
  e é reenviado. A falha de criativo não derruba a sincronização (métrica
  vale mais que imagem), mas agora **vai para o log** — era um `except`
  mudo, e o sintoma virava "os anúncios não têm imagem" sem nada apontando
  a causa.
- **A seleção de métricas é higienizada na leitura.** Ela vive no
  `localStorage`, então quem usou uma versão anterior tem chaves de métricas
  que não existem mais. Chave desconhecida é descartada; se **todas** forem
  desconhecidas, a seleção volta ao padrão — senão o painel abriria vazio sem
  o cliente entender por quê (`_sanitize` em `pages/dashboard.py`).
