from __future__ import annotations

import argparse
import base64
import queue
import json
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import paleonia.api.auth as auth
from paleonia.api.schemas import DetectBody, LinesBody, LoginBody, TranscribeBody
from paleonia.config import PROJECT_ROOT, get_settings
from paleonia.db.users import UserDirectory
from paleonia.reading import page as page_read
from paleonia.session.store import DeskStore
from paleonia.image_enhance.preprocess import encode_jpeg
from paleonia.vectors.index import (
    VectorIndex,
    _safe_message,
    persist_page,
    schedule_embed_outstanding,
    schedule_remove,
)

PUBLIC_DIR = PROJECT_ROOT / "public"


def _job(**overrides) -> dict:
    payload = {"status": "idle", "message": "", "done": 0, "total": 0, "page": None}
    payload.update(overrides)
    return payload


def _call(action: Callable, *, errors: tuple[type[Exception], ...] = (ValueError,)):
    try:
        return action()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except errors as exc:
        raise HTTPException(400, str(exc)) from exc


def _download(content: str, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _public_path(path: str) -> bool:
    if path in {"/api/auth", "/api/login", "/api/logout"}:
        return True
    return not path.startswith("/api/") and not path.startswith("/images/")


def _login_required(users: UserDirectory) -> bool:
    if users.settings.database_url:
        return True
    return auth.enabled(users.settings)


def _authenticated(request: Request, users: UserDirectory) -> bool:
    if not _login_required(users):
        return True
    token = request.cookies.get(auth.COOKIE, "")
    return auth.read_username(token, users.settings) is not None


def _user_id(request: Request) -> int | None:
    users: UserDirectory = request.app.state.users
    if not users.active:
        return None
    name = auth.read_username(request.cookies.get(auth.COOKIE, ""), users.settings)
    if not name:
        return None
    return users.id_of(name)


def begin_transcription(
    store: DeskStore,
    jobs: dict,
    guard: threading.Lock,
    page_id: str,
    only_empty: bool = True,
    index: VectorIndex | None = None,
    user_id: int | None = None,
) -> dict:
    store._require(page_id)
    with guard:
        if any(item.get("status") == "running" for item in jobs.values()):
            raise RuntimeError("Já há uma transcrição em andamento.")
        job = _job(status="running", message="Preparando a leitura…")
        jobs[page_id] = job

    def worker() -> None:
        def progress(message: str, done: int, total: int) -> None:
            job["message"] = message
            job["done"] = done
            job["total"] = total
            try:
                job["page"] = store.public_page(store._require(page_id))
            except FileNotFoundError:
                job["page"] = None

        try:
            page_read.read_page_lines(
                store,
                page_id,
                only_empty=only_empty,
                progress=progress,
                precedents=index if index is not None and index.enabled else None,
                user_id=user_id,
            )
            job["status"] = "done"
            if not job["message"] or job["message"] == "Preparando a leitura…":
                job["message"] = "Transcrição pronta."
        except Exception as exc:
            job["status"] = "error"
            job["message"] = str(exc)
        try:
            page = store._require(page_id)
            job["page"] = store.public_page(page)
        except FileNotFoundError:
            page = None
        if index is not None and page is not None:
            try:
                persist_page(index, page, user_id)
            except Exception as exc:
                note = _safe_message(exc)
                job["message"] = f"{job['message']} O texto não entrou no Postgres: {note}".strip()

    threading.Thread(target=worker, daemon=True).start()
    return job


def _jpeg(path: Path | None) -> FileResponse:
    if path is None:
        raise HTTPException(404, "Imagem não encontrada")
    return FileResponse(path, media_type="image/jpeg")


def create_app(work_dir: str | Path | None = None) -> FastAPI:
    settings = get_settings()
    root = Path(work_dir or settings.work_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = DeskStore(root)
    users = UserDirectory(settings)
    users.prepare()
    index = VectorIndex(settings)

    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.state.store = store
    app.state.users = users
    app.state.vectors = index
    if index.enabled and not users.error:
        schedule_embed_outstanding(index)
    app.state.jobs = {}
    app.state.jobs_guard = threading.Lock()

    @app.get("/api/session")
    def session() -> dict:
        return store.public_session()

    @app.post("/api/pages")
    async def upload(files: list[UploadFile] = File(...)) -> dict:
        created = []
        errors: list[str] = []
        for upload_file in files:
            name = upload_file.filename or "manuscrito.jpg"
            data = await upload_file.read()
            if not data:
                errors.append(f"{name}: arquivo vazio")
                continue
            try:
                created.append(store.add_page(name, data))
            except (ValueError, RuntimeError) as exc:
                errors.append(f"{name}: {exc}")
        if not created:
            raise HTTPException(400, errors[0] if errors else "Nenhuma imagem recebida")
        return {"pages": created, "errors": errors}

    @app.post("/api/pages/stream")
    async def upload_stream(files: list[UploadFile] = File(...)):
        inputs = [(item.filename or "manuscrito.jpg", await item.read()) for item in files]
        events = queue.Queue(maxsize=8)
        stopped = threading.Event()

        def emit(event):
            while not stopped.is_set():
                try:
                    events.put(event, timeout=0.2)
                    return
                except queue.Full:
                    pass
            raise RuntimeError("Importação interrompida")

        def work():
            created, errors = [], []
            try:
                for name, data in inputs:
                    def progress(stage, image, x, y, scale, done, total):
                        event = dict(stage=stage, filename=name, x=x, y=y,
                                     scale=scale, done=done, total=total)
                        if image is not None:
                            event.update(width=int(image.shape[1]), height=int(image.shape[0]),
                                         image="data:image/jpeg;base64," + base64.b64encode(encode_jpeg(image)).decode())
                        emit(event)
                    try:
                        created.append(store.add_page(name, data, progress=progress))
                    except Exception as exc:
                        if stopped.is_set():
                            return
                        errors.append(f"{name}: {_safe_message(exc)}")
                emit(dict(stage="complete", pages=created, errors=errors))
            finally:
                if not stopped.is_set():
                    emit(None)

        def stream():
            threading.Thread(target=work, daemon=True).start()
            try:
                while True:
                    event = events.get()
                    if event is None:
                        break
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            finally:
                stopped.set()

        return StreamingResponse(stream(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.put("/api/pages/{page_id}")
    def update_page(page_id: str, payload: LinesBody, request: Request) -> dict:
        page = _call(
            lambda: store.replace_lines(
                page_id,
                [line.model_dump() for line in payload.lines],
                sensitivity=payload.sensitivity,
            )
        )
        _remember(page_id, request)
        return page

    @app.post("/api/pages/{page_id}/detect")
    def detect(page_id: str, request: Request, payload: DetectBody | None = None) -> dict:
        options = payload or DetectBody()
        page = _call(
            lambda: store.redetect(page_id, options.sensitivity),
            errors=(ValueError, RuntimeError),
        )
        _remember(page_id, request)
        return page

    @app.post("/api/pages/{page_id}/transcribe")
    def start_transcribe(page_id: str, request: Request, payload: TranscribeBody | None = None) -> dict:
        options = payload or TranscribeBody()
        try:
            return begin_transcription(
                store,
                app.state.jobs,
                app.state.jobs_guard,
                page_id,
                options.only_empty,
                app.state.vectors,
                _user_id(request),
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/pages/{page_id}/transcribe")
    def transcribe_status(page_id: str) -> dict:
        _call(lambda: store._require(page_id))
        return app.state.jobs.get(page_id) or _job()

    @app.delete("/api/pages/{page_id}")
    def delete_page(page_id: str) -> dict:
        _call(lambda: store.delete_page(page_id))
        schedule_remove(app.state.vectors, page_id)
        return store.public_session()

    @app.get("/api/search")
    def search(request: Request, q: str = "", limit: int = 8) -> dict:
        query = q.strip()
        if not query:
            raise HTTPException(400, "Informe o texto da busca.")
        query = query[:2000]
        vectors = request.app.state.vectors
        if not vectors.enabled:
            return {
                "enabled": False,
                "query": query,
                "results": [],
                "detail": "Defina DATABASE_URL no .env e suba o Postgres com pgvector para buscar no acervo.",
            }
        try:
            results = vectors.search(query, limit=limit, user_id=_user_id(request))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, _safe_message(exc)) from exc
        return {"enabled": True, "query": query, "results": results}

    @app.get("/api/export.txt")
    def export_txt() -> Response:
        stem = get_settings().download_stem
        return _download(store.export_text(), "text/plain; charset=utf-8", f"{stem}.txt")

    @app.get("/api/export.json")
    def export_json() -> Response:
        stem = get_settings().download_stem
        body = json.dumps(store.export_document(), ensure_ascii=False, indent=2) + "\n"
        return _download(body, "application/json; charset=utf-8", f"{stem}.json")

    @app.get("/images/{page_id}/original")
    def page_original(page_id: str) -> FileResponse:
        return _jpeg(store.original_path(page_id))

    @app.get("/images/{page_id}/thumb")
    def page_thumb(page_id: str) -> FileResponse:
        return _jpeg(store.thumb_path(page_id))

    @app.get("/images/{page_id}")
    def page_image(page_id: str) -> FileResponse:
        _call(lambda: store.ensure_prepared(page_id))
        return _jpeg(store.image_path(page_id))

    @app.get("/api/auth")
    def auth_status(request: Request) -> dict:
        settings = get_settings()
        required = _login_required(users)
        authenticated = _authenticated(request, users)
        token_name = auth.read_username(request.cookies.get(auth.COOKIE, ""), settings) if authenticated and required else None
        return {
            "required": required,
            "authenticated": authenticated,
            "username": token_name or (settings.auth_username if required else ""),
        }

    @app.post("/api/login")
    def login(payload: LoginBody) -> JSONResponse:
        settings = get_settings()
        if settings.database_url:
            if users.error:
                raise HTTPException(503, users.error)
            if not users.active:
                raise HTTPException(503, "Não há usuários no Postgres. Rode: python -m paleonia.db add-user NOME")
            try:
                name = users.authenticate(payload.username, payload.password)
            except Exception as exc:
                raise HTTPException(503, _safe_message(exc)) from exc
            if not name:
                raise HTTPException(401, "Usuário ou senha incorretos.")
            return _session_cookie(name)
        if not auth.enabled(settings):
            return JSONResponse({"authenticated": True, "required": False})
        if not auth.credentials_match(settings, payload.username, payload.password):
            raise HTTPException(401, "Usuário ou senha incorretos.")
        return _session_cookie(settings.auth_username)

    @app.post("/api/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(auth.COOKIE, path="/")
        return response

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        if _login_required(users) and not _public_path(request.url.path) and not _authenticated(request, users):
            return JSONResponse({"detail": "Faça login para continuar."}, status_code=401)
        return await call_next(request)

    if PUBLIC_DIR.is_dir():
        app.mount("/brand", StaticFiles(directory=str(PUBLIC_DIR)), name="brand")
    return app


def _session_cookie(username: str) -> JSONResponse:
    settings = get_settings()
    response = JSONResponse({"authenticated": True, "required": True, "username": username})
    response.set_cookie(
        auth.COOKIE,
        auth.issue_token(settings, username),
        httponly=True,
        samesite="lax",
        max_age=auth.TTL_SECONDS,
        path="/",
    )
    return response


def _remember(page_id: str, request: Request) -> None:
    index: VectorIndex = request.app.state.vectors
    if not index.enabled:
        return
    try:
        page = request.app.state.store._require(page_id)
    except FileNotFoundError:
        return
    try:
        persist_page(index, page, _user_id(request))
    except Exception as exc:
        raise HTTPException(503, _safe_message(exc)) from exc


def _session_dir(value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=f"{settings.app_name}: importar manuscritos e transcrever linha a linha.")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Pasta da sessão. O padrão é output/desk na raiz do projeto.",
    )
    parser.add_argument("--host", default=settings.web_host)
    parser.add_argument("--port", type=int, default=settings.web_port)
    parser.add_argument("--no-browser", action="store_true", help="Não abre o navegador")
    args = parser.parse_args(argv)
    work_dir = _session_dir(args.work_dir, settings.work_dir)

    url = f"http://{args.host}:{args.port}"
    ui_url = "http://127.0.0.1:3000"
    print(f"{settings.app_name} API em {url}  (sessão: {work_dir.resolve()})")
    if settings.database_url:
        print(f"Busca vetorial no Postgres com {settings.embed_model} ({settings.embed_dimensions} dimensões)")
    print(f"Interface em {ui_url}  (pasta web: npm run dev)")
    if settings.open_browser and not args.no_browser:
        timer = threading.Timer(0.7, lambda: webbrowser.open(ui_url))
        timer.daemon = True
        timer.start()

    import uvicorn

    uvicorn.run(create_app(work_dir), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
