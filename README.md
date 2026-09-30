<div align="center">
  <img src="public/PaleonIA-logo-white.svg" alt="Logo do PaleonIA" width="100%">
  <p><strong>Uma mesa de trabalho para ler, revisar e organizar manuscritos linha a linha.</strong></p>
  <p>Criado por <strong>Marllon Barizão</strong></p>
  <p><a href="#instalação-passo-a-passo">Instalação</a> · <a href="#como-funciona-a-transcrição">Transcrição</a> · <a href="#como-contribuir">Contribuir</a> · <a href="LICENSE.md">Licença MIT</a></p>
</div>

---

O **PaleonIA** recebe imagens de documentos manuscritos, prepara a página para leitura, localiza linhas com o **Kraken blla** e usa um modelo de visão para sugerir a transcrição. A mesa mantém cada faixa da imagem ligada ao seu texto, para conferir, corrigir e exportar.

> A leitura automática é uma sugestão. Caligrafia difícil, rasuras e baixa qualidade de digitalização exigem revisão humana antes de usar o texto como transcrição definitiva.

## Tela do sistema

![Mesa do PaleonIA com documento carregado e linhas detectadas](docs/images/mesa-transcricao.png)

*Captura da aplicação local com um documento histórico. As faixas sobre a página correspondem às linhas editáveis da transcrição.*

## Recursos

| Recurso | O que faz |
| --- | --- |
| Importação | Recebe uma ou várias imagens JPG, JPEG, PNG, TIFF ou WEBP. PDF ainda não é aceito. |
| Tratamento | Mantém o original e prepara outra imagem com correções de borda, fundo, contraste e nitidez. |
| Detecção | O Kraken blla marca as linhas. É possível detectar novamente, desenhar, ajustar, dividir, omitir ou excluir faixas. |
| Leitura | Um modelo de visão transcreve grupos de linhas pelo Ollama local ou por API compatível com OpenAI, incluindo OpenRouter. |
| Revisão | Mostra a linha no documento (D) e a linha transcrita (T), com edição e confirmação humana. |
| Acervo | Guarda imagens e textos na sessão local. PostgreSQL com pgvector habilita busca por significado e precedentes conferidos. |
| Exportação | Baixa TXT pela interface; a API também oferece JSON com texto e coordenadas. |

## Como funciona a transcrição

1. **Importação:** cada arquivo é decodificado e salvo na pasta de trabalho. O sistema guarda o original e uma versão preparada.
2. **Preparação:** a página é corrigida e ampliada quando cabe no limite configurado. O tratamento clareia o papel, reduz sombras/molduras e reforça o traço.
3. **Segmentação:** o Kraken blla detecta as faixas e devolve caixas na imagem. Cada faixa recebe um número **D**. Em modo automático, o Kraken usa CUDA se o PyTorch detectar uma GPU; caso contrário, usa CPU.
4. **Leitura:** ao clicar em **Transcrever**, a API agrupa linhas próximas, recorta a imagem e pede ao modelo de visão um JSON com um texto por linha. A instrução solicita preservar a grafia, não traduzir ou modernizar e usar **[ilegível]** onde a imagem não sustentar a leitura.
5. **Associação:** a resposta é distribuída pelas faixas. O texto **T** fica vinculado à respectiva faixa **D**. O progresso aparece na mesa e a sessão é salva em <code>output/desk/session.json</code>.
6. **Revisão:** selecione uma faixa, ajuste sua posição, edite o texto e marque a correção como conferida. A releitura padrão processa linhas vazias, preservando textos já preenchidos. A numeração T pode diferir da D se uma faixa for omitida ou dividida.
7. **Saída:** baixe TXT ou consulte o JSON da API. Com banco configurado, as linhas são indexadas para busca; textos conferidos podem auxiliar uma releitura de trechos ilegíveis.

~~~text
Imagem → preparação → Kraken blla → faixas D → modelo de visão → textos T
                                                        ↓
                                           revisão humana → TXT / JSON
                                                        ↓
                                           pgvector (opcional)
~~~

## Instalação passo a passo

Os exemplos usam **PowerShell no Windows**. Instale [Python 3.12](https://www.python.org/downloads/windows/), [Node.js 22](https://nodejs.org/en/download), [Git](https://git-scm.com/downloads/win) e, para o modelo local, [Ollama](https://ollama.com/download). Siga os instaladores oficiais e abra um novo terminal após a instalação. [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) é opcional para PostgreSQL. Uma GPU NVIDIA também é opcional.

Confira os comandos antes de continuar:

~~~powershell
py -3.12 --version
node --version
npm --version
git --version
~~~

### 1. Obtenha o código e crie o ambiente Python

~~~powershell
git clone <URL_DO_REPOSITORIO>
cd mesa_transcricao
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
~~~

Se você já tem o código, entre na pasta e comece pelo comando <code>py -3.12 -m venv .venv</code>. O Kraken é instalado por <code>requirements.txt</code>. Caso esteja em outro Python, informe o caminho do executável em <code>KRAKEN_PYTHON</code> no <code>.env</code>.

Substitua <code>&lt;URL_DO_REPOSITORIO&gt;</code> pela URL do projeto no GitHub. Se recebeu o projeto como ZIP, extraia os arquivos e entre na pasta antes de criar o ambiente.

### 2. Prepare o modelo de visão

Inicie o Ollama e baixe o modelo padrão:

~~~powershell
ollama pull qwen3-vl:8b-instruct
~~~

O padrão é <code>LLM_PROVIDER=ollama</code>, <code>OLLAMA_MODEL=qwen3-vl:8b-instruct</code> e <code>OLLAMA_HOST=http://127.0.0.1:11434</code>. O modelo ocupa vários gigabytes; confira espaço e memória disponíveis.

### 3. Configure o arquivo .env

O arquivo copiado já contém os padrões locais. Confira estes valores:

~~~dotenv
PALEONIA_HOST=127.0.0.1
PALEONIA_PORT=8878
PALEONIA_WORK_DIR=output/desk
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen3-vl:8b-instruct
KRAKEN_DEVICE=auto
~~~

Para usar **OpenRouter** em vez de Ollama:

~~~dotenv
LLM_PROVIDER=openrouter
LLM_API_KEY=sua_chave
LLM_MODEL=qwen/qwen3-vl-8b-instruct
~~~

Para outra **API compatível com o formato de chat da OpenAI**, configure <code>LLM_PROVIDER=openai</code>, <code>LLM_BASE_URL</code>, <code>LLM_API_KEY</code> e <code>LLM_MODEL</code>. O modelo deve aceitar imagens. Recortes da página são enviados ao provedor externo nessa modalidade. O <code>.env</code> não entra no Git; variáveis do sistema prevalecem sobre ele. Reinicie a API após alterá-lo.

### 4. Instale a interface

~~~powershell
cd web
npm ci
cd ..
~~~

### 5. Inicie os dois serviços

No **primeiro terminal**, com o ambiente Python ativado:

~~~powershell
python -m paleonia --no-browser
~~~

No **segundo terminal**:

~~~powershell
cd web
npm run dev
~~~

Abra **http://127.0.0.1:3000**. A API fica em **http://127.0.0.1:8878**. O Next.js encaminha <code>/api</code>, <code>/images</code> e <code>/brand</code> à API Python. Se mudar <code>PALEONIA_PORT</code>, reinicie também o Next.js, que lê a porta do <code>.env</code> ao iniciar. Para outro endereço de API, defina <code>PALEONIA_API_URL</code> no ambiente do Next.js.

### 6. Faça a primeira transcrição

1. Clique em **Importar** e escolha uma ou mais imagens.
2. Aguarde a preparação da página e a detecção das faixas.
3. Confira as faixas na **Mesa**. Use **Detectar linhas** ou **Nova linha** se necessário.
4. Clique em **Transcrever** e acompanhe o progresso.
5. Revise o texto junto da imagem. A aba **Correções** ajuda a organizar a conferência.
6. Clique em **Baixar texto** para exportar o TXT.

### Banco e busca por significado (opcionais)

Com Docker Desktop e Ollama ativos:

~~~powershell
docker compose up -d
ollama pull nomic-embed-text
~~~

Adicione ou descomente no <code>.env</code>:

~~~dotenv
DATABASE_URL=postgresql://paleonia:paleonia@127.0.0.1:5432/paleonia
EMBED_PROVIDER=ollama
EMBED_MODEL=nomic-embed-text
EMBED_DIMENSIONS=768
~~~

Aplique as migrações e reinicie a API:

~~~powershell
python -m paleonia.db
~~~

O <code>docker-compose.yml</code> traz credenciais locais de exemplo: troque a senha antes de expor o banco em rede. A migração cria um vetor de **768 dimensões**; outro tamanho exige alteração da migração. Sem <code>DATABASE_URL</code>, transcrição e exportação continuam disponíveis, mas a busca vetorial fica desativada.

### Login (opcional)

Sem banco, preencher <code>AUTH_USERNAME</code> e <code>AUTH_PASSWORD</code> no <code>.env</code> ativa o login local; com senha vazia, a mesa abre diretamente. Com banco, essas variáveis criam o primeiro usuário se a tabela estiver vazia. Para adicionar outro:

~~~powershell
python -m paleonia.db add-user maria
~~~

A senha é solicitada no terminal e armazenada como hash. Configure <code>AUTH_SECRET</code> para assinar o cookie da sessão. Para acesso remoto, adapte autenticação e rede à sua implantação.

## Configuração rápida

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| <code>PALEONIA_PORT</code> | 8878 | Porta da API Python |
| <code>PALEONIA_WORK_DIR</code> | output/desk | Imagens e sessão |
| <code>LLM_PROVIDER</code> | ollama | ollama, openrouter ou openai |
| <code>OLLAMA_MODEL</code> | qwen3-vl:8b-instruct | Modelo local se LLM_MODEL estiver vazio |
| <code>KRAKEN_DEVICE</code> | auto | Dispositivo da detecção de linhas |
| <code>KRAKEN_PYTHON</code> | vazio | Outro Python com Kraken |
| <code>DATABASE_URL</code> | vazio | Habilita Postgres e busca |
| <code>AUTH_PASSWORD</code> | vazio | Ativa login local ou usuário inicial |

Todos os limites de imagem, tempos de espera, parâmetros do modelo e embeddings estão em [<code>.env.example</code>](.env.example).

## Estrutura do projeto

~~~text
paleonia/
  api/             FastAPI, rotas e autenticação
  image_enhance/   preparação e ajustes da imagem
  segment/         detecção de linhas com Kraken
  reading/         modelo de visão e precedentes
  session/         imagens, linhas, revisão e exportação
  vectors/         embeddings e busca
  db/              migrações e usuários do PostgreSQL
web/               Next.js, React e Ant Design
public/            logos SVG
tests/             testes automatizados do backend
~~~

Por padrão, os dados importados ficam em <code>output/desk/</code> e são ignorados pelo Git. Para a interface em modo de produção, execute <code>npm run build</code> e <code>npm run start</code> em <code>web/</code>, mantendo a API Python em execução.

## API principal

| Rota | Uso |
| --- | --- |
| <code>GET /api/session</code> | Consulta as páginas e linhas da sessão. |
| <code>POST /api/pages</code> | Importa imagens. |
| <code>POST /api/pages/{id}/detect</code> | Redetecta as faixas da página. |
| <code>POST /api/pages/{id}/transcribe</code> | Inicia a transcrição em segundo plano. |
| <code>GET /api/pages/{id}/transcribe</code> | Consulta o progresso. |
| <code>PUT /api/pages/{id}</code> | Salva ajustes e revisão das linhas. |
| <code>GET /api/search?q=...</code> | Busca no acervo, quando o banco está ativo. |
| <code>GET /api/export.txt</code> / <code>GET /api/export.json</code> | Exporta a sessão. |

A documentação interativa da API fica em **http://127.0.0.1:8878/docs** quando a API estiver em execução.

## Teste com NVIDIA GeForce RTX 4060 8 GB

O projeto foi usado nesta máquina com uma **NVIDIA GeForce RTX 4060 de 8 GB** (o driver informa **8188 MiB**). A sessão local registra a importação de uma página histórica em italiano, a detecção de **99 faixas** e texto preenchido em **91** delas. A captura acima mostra a página na mesa. Apenas **uma linha** está marcada como conferida; as demais ainda requerem revisão humana.

Esse registro demonstra o fluxo de importação, detecção e edição nessa configuração. **Não há benchmark de tempo, medição de acurácia ou registro de uso da GPU por etapa**. O modo <code>KRAKEN_DEVICE=auto</code> escolhe CUDA somente se o PyTorch a detectar; o uso da GPU pelo Ollama depende da instalação local. A presença da RTX 4060 não comprova aceleração de todas as etapas.

Para verificar seu ambiente:

~~~powershell
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
python -m unittest discover -s tests
~~~

Execute a verificação do PyTorch no mesmo ambiente usado pelo Kraken. Avalie a qualidade da transcrição contra referências revisadas por pessoas.

Para rodar os testes sem configurar banco, deixe <code>DATABASE_URL</code> vazio no processo. A suíte de autenticação local pressupõe esse modo; com um banco definido no <code>.env</code>, ela pode falhar por usar o fluxo de login do PostgreSQL.

## Como contribuir

Contribuições de código, documentação, acessibilidade e testes com manuscritos são bem-vindas.

1. Abra uma *issue* com passos para reproduzir o problema, versões de Python/Node, provedor do modelo e mensagens de erro, sem credenciais ou documentos privados.
2. Faça um *fork*, crie uma branch e implemente uma alteração focada.
3. Rode as verificações:

   ~~~powershell
   python -m unittest discover -s tests
   cd web
   npx tsc --noEmit
   npm run build
   ~~~

4. Abra um *pull request* explicando o que mudou e como foi testado. Para mudanças visuais, inclua captura com dados que possam ser publicados.

Evite enviar <code>.env</code>, <code>output/</code> ou páginas de terceiros sem autorização de uso. Preserve a relação entre faixa **D** e texto **T** ao alterar o fluxo.

## Criador

**Marllon Barizão** é o criador do PaleonIA. O projeto reúne a imagem do manuscrito, o texto sugerido pela IA e a revisão humana no mesmo fluxo de transcrição.

## Licença

Distribuído sob a [licença MIT](LICENSE.md), que permite uso, modificação e distribuição, inclusive comercial, mantendo o aviso de copyright e a licença. Dependências e modelos externos conservam suas próprias licenças e termos.
