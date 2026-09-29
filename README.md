# PaleonIA

Transcrição de manuscritos: importa JPG, marca cada linha do documento (D) e a linha transcrita (T), e lê o texto com um modelo de visão no Ollama.

## Ambiente

```powershell
cd C:\Documents\Projetos\mesa_transcricao
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

O `.env` na raiz do projeto concentra nome, porta, pasta da sessão, modelo e limites de imagem. O exemplo está em `.env.example`.

## Login

Com `AUTH_PASSWORD` preenchido, a mesa pede usuário e senha. O padrão do usuário é `paleonia`. `AUTH_SECRET` assina a sessão; se ficar vazio, a própria senha cumpre esse papel. Sem senha no `.env`, o login fica desligado. Depois de alterar o arquivo, suba o PaleonIA de novo.

## Leitura

`LLM_PROVIDER` escolhe de onde vem o texto:

- `ollama` — modelo local. O nome fica em `OLLAMA_MODEL` (padrão `qwen3-vl:8b-instruct`), ou em `LLM_MODEL` se este estiver preenchido.
- `openrouter` — API da OpenRouter. O modelo padrão é `qwen/qwen3-vl-8b-instruct`.
- `openai` — qualquer API no formato de chat da OpenAI. Informe `LLM_BASE_URL` e `LLM_MODEL`.

Para a OpenRouter, no `.env`:

```
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-...
LLM_MODEL=qwen/qwen3-vl-8b-instruct
```

`LLM_PROVIDER=openrouter` usa `https://openrouter.ai/api/v1`. Outro serviço compatível pede a URL:

```
LLM_PROVIDER=openai
LLM_BASE_URL=https://exemplo.com/v1
LLM_API_KEY=...
LLM_MODEL=qwen/qwen3-vl-8b-instruct
```

A chave fica só no `.env`, que não entra no git. Depois de alterar o arquivo, suba o PaleonIA de novo. O nome do provedor aparece no topo da mesa.

## Ollama

Com `LLM_PROVIDER=ollama`, a leitura usa o modelo local:

```powershell
ollama pull qwen3-vl:8b-instruct
```

Com `OLLAMA_HOST` vazio, o PaleonIA procura o Ollama em `127.0.0.1:11434` e, se existir, no IP do WSL. Se o serviço estiver no WSL, deixe-o a escutar em `0.0.0.0:11434` e grave no `.env`:

```
OLLAMA_HOST=http://<IP-do-WSL>:11434
```

## Kraken

As linhas do documento são localizadas pelo Kraken blla, no mesmo `.venv`. Se o Kraken estiver noutro Python, aponte `KRAKEN_PYTHON` (Windows) ou `KRAKEN_WSL_PYTHON` (WSL).

## Subir

A interface fica em Next.js. A API continua no Python.

```powershell
python -m paleonia --no-browser
```

Em outro terminal:

```powershell
cd web
npm install
npm run dev
```

A mesa abre em http://127.0.0.1:3000. A API fica em http://127.0.0.1:8878 e a sessão em `output/desk/`.

```powershell
python -m paleonia --port 8878 --no-browser
```

Os argumentos da linha de comando prevalecem sobre o `.env`. Se mudar `PALEONIA_PORT`, a pasta `web` precisa enxergar a mesma porta: o Next lê esse valor no `.env` da raiz.
