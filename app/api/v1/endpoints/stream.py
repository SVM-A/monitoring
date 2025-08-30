import asyncio
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Security, WebSocket, WebSocketDisconnect, WebSocketException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.base_api import AnwillUserAPI
from app.db.models.tables import User, Avatar
from app.services.stream.progress import progress_registry
from app.services.s3.tasks import validate_image_file, upload_and_prepare_images, delete_photo_file
from app.utils.logger import logger

class StreemAPI(AnwillUserAPI):

    def __init__(self):
        super().__init__()
        # Установка маршрутов и тегов
        self.tags = ['Streem']
        self.router = APIRouter(tags=self.tags)

    async def setup_routes(self):
        await self.put_avatar_progress_sse()
        await self.put_avatar_progress_ws()
        await self.put_avatar_progress_ws_info()

    async def put_avatar_progress_sse(self):
        @self.router.get("/sse/me/profile/avatar/stream")
        async def put_avatar_progress_sse(user_id: int = Security(self.get_current_sse_user)) -> StreamingResponse:
            """
            **Аутентификация (приоритет):**
            1. Cookie `stream_token` (HttpOnly).
            2. `Authorization: Bearer <stream_jwt>`.

            **Заголовки ответа:**
            ```
            Content-Type: text/event-stream
            Cache-Control: no-cache
            Connection: keep-alive
            X-Accel-Buffering: no
            ```

            **Формат событий:**
            ```
            event: progress
            data: {"task_id":"...","percent":85,"step":"uploading","status":"running"}

            : keep-alive
            ```

            **Fallback (Bearer):**
            ```javascript
            const resp = await fetch("/sse/me/profile/avatar/stream", {
              headers: { Authorization: `Bearer ${streamJwt}`, Accept: "text/event-stream" }
            });
            ```

             **Request Testing (Bearer):**
            ```shell
            curl -N -H "Authorization: Bearer <stream_jwt>" \\
                 -H "Accept: text/event-stream" \\
                 "https://api.anwill.fun/sse/me/profile/avatar/stream"
            ```

            **Request Testing (Cookie):**
            ```shell
            curl -N -H "Cookie: stream_token=<stream_jwt>" \\
                 -H "Accept: text/event-stream" \\
                 "https://api.anwill.fun/sse/me/profile/avatar/stream"
            ```

            """

            async def event_generator():
                yield self.sse_event(progress_registry.snapshot(user_id) or {"status": "idle"})
                queue = progress_registry.get_queue(user_id)
                try:
                    while True:
                        try:
                            msg = await asyncio.wait_for(queue.get(), timeout=25)
                            yield self.sse_event(msg)
                        except asyncio.TimeoutError:
                            yield ": keep-alive\n\n"
                except (asyncio.CancelledError, GeneratorExit):
                    return

            headers = {
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
            return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    async def put_avatar_progress_ws(self):
        @self.router.websocket("/ws/me/profile/avatar/stream")
        async def put_avatar_progress_ws(websocket: WebSocket):
            """
            **Аутентификация (приоритет):**
            1) Cookie `stream_token` (HttpOnly),
            2) `Authorization: Bearer <stream_jwt>`,

            **События:** JSON, например:
            {"event":"progress","data":{"task_id":"...","percent":85,"step":"uploading","status":"running"}}

            Пинг каждые ~25 сек для keep-alive.
            """
            await websocket.accept()
            user_id = await self._auth_ws_user(websocket)
            if not user_id:
                # 4401 — кастомный код закрытия "Unauthorized"
                await websocket.close(code=4401)
                return

            # начальное состояние
            snap = progress_registry.snapshot(user_id) or {"status": "idle"}
            try:
                await websocket.send_json({"event": "progress", "data": snap})
            except RuntimeError:
                await websocket.close()
                return

            queue = progress_registry.get_queue(user_id)

            async def sender():
                try:
                    while True:
                        try:
                            msg = await asyncio.wait_for(queue.get(), timeout=25)
                            await websocket.send_json({"event": "progress", "data": msg})
                            # закрываем по завершению
                            if msg.get("status") in {"done", "error"}:
                                await websocket.close(code=1000)
                                break
                        except asyncio.TimeoutError:
                            # keep-alive ping; если нужен Pong — активируй ниже
                            await websocket.send_json({"event": "keepalive"})
                except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
                    return

            async def receiver():
                # опционально читаем входящие (для Pong/команд клиента)
                try:
                    while True:
                        _ = await websocket.receive_text()
                        # можно обрабатывать команды клиента тут
                except WebSocketDisconnect:
                    return
                except WebSocketException:
                    return

            sender_task = asyncio.create_task(sender())
            receiver_task = asyncio.create_task(receiver())
            done, pending = await asyncio.wait(
                {sender_task, receiver_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

    async def put_avatar_progress_ws_info(self):
        @self.router.get("/ws/me/profile/avatar/stream")
        async def put_avatar_progress_ws_info():
            """
            **WebSocket: статус загрузки аватарки**

            **URL:** `wss://api.anwill.fun/ws/me/profile/avatar/stream`

            **Аутентификация (приоритет):**
            1. Cookie `stream_token` (HttpOnly);
            2. Заголовок `Authorization: Bearer <stream_jwt>`;

            **События (JSON):**
            - Первое сообщение — снапшот:
            ```json
            {"event":"progress","data":{"task_id":"...","percent":0,"step":"queued","status":"running"}}
            ```
            - Обновления:
            ```json
            {"event":"progress","data":{"task_id":"...","percent":85,"step":"uploading","status":"running"}}
            ```
            - Keep-alive каждые ~25 секунд:
            ```json
            {"event":"keepalive"}
            ```
            - Завершение:
            ```json
            {"event":"progress","data":{"task_id":"...","percent":100,"status":"done"}}
            ```
            или
            ```json
            {"event":"progress","data":{"task_id":"...","percent":95,"status":"error","error":"db_error"}}
            ```

            **Коды закрытия:**
            - `1000` — нормальное завершение по `done`/`error`.
            - `4401` — неавторизован (невалидный/просроченный токен).

            **Примеры подключения:**

            *Browser JS (cookie):*
            ```js
            const ws = new WebSocket("wss://api.anwill.fun/ws/me/profile/avatar/stream");
            ws.onmessage = (e) => {
              const msg = JSON.parse(e.data);
              if (msg.event === "progress") {
                const { percent, step, status } = msg.data || {};
                // update UI...
                if (status === "done" || status === "error") ws.close();
              }
            };
            ```

            *Android (OkHttp):*
            ```kotlin
            val request = Request.Builder()
                .url("wss://api.anwill.fun/ws/me/profile/avatar/stream")
                // .addHeader("Authorization", "Bearer " + streamJwt)
                .build()
            val ws = OkHttpClient().newWebSocket(request, object: WebSocketListener() {
                override fun onMessage(ws: WebSocket, text: String) { /* parse JSON */ }
            })
            ```

            *iOS (URLSessionWebSocketTask):*
            ```swift
            let url = URL(string: "wss://api.anwill.fun/ws/me/profile/avatar/stream")!
            let task = URLSession.shared.webSocketTask(with: url)
            task.resume()
            func receive() { task.receive { result in /* parse */; receive() } }
            receive()
            ```

            **Заготовка фронт‑логики:**
            - Если соединение падает до завершения — можно переподключиться и получить снапшот прогресса (`snapshot` приходит первым сообщением).
            - При сетевых проблемах использовать fallback `GET /me/profile/avatar/status`.
            """
            return JSONResponse({"ok": True, "message": "See description above"})


    @staticmethod
    async def process_avatar_task(
            user_id: int,
            file_bytes: bytes,
            filename: str,
            db_session_factory,
    ):
        # Новый сессионный контекст, чтобы не зависеть от контекста запроса
        async with db_session_factory() as db:
            try:
                # 0 → 5%
                progress_registry.update(user_id, 5, "validate")
                is_valid = await validate_image_file(file_bytes, filename)  #
                if not is_valid:
                    raise HTTPException(status_code=404, detail="Invalid image")

                # 5 → 30% (конвертация)
                progress_registry.update(user_id, 30, "convert_to_webp")
                # конвертация внутри upload_and_prepare_images; можно вручную вызвать convert_to_webp если нужно
                # 30 → 60% (превью/resize)
                progress_registry.update(user_id, 60, "make_preview")
                user = await db.get(User, user_id)
                old = user.profile.avatar
                if old:
                    try:
                        await delete_photo_file(old.orig_photo)
                        await delete_photo_file(old.preview_photo)
                    except Exception:
                        logger.warning("Не смогли удалить старую аватарку")
                user.profile.avatar = None
                await db.flush()
                # 60 → 85% (загрузка)
                progress_registry.update(user_id, 85, "uploading")
                await db.refresh(user, attribute_names=["profile"])
                today_date = datetime.now()
                s3_key_orig, s3_key_preview = await upload_and_prepare_images(
                    photo_id=str(uuid4()),
                    orig_file_buffer=file_bytes,
                    date=today_date,
                    object_type='avatar'
                )

                # 85 → 95% (запись в БД)
                progress_registry.update(user_id, 95, "db_write")


                avatar_obj = Avatar(
                    id=user.profile_id,
                    profile_id=user.profile_id,
                    orig_photo=s3_key_orig,
                    preview_photo=s3_key_preview
                )
                db.add(avatar_obj)
                await db.flush()
                await db.refresh(user.profile)

                await db.commit()
                progress_registry.finish(user_id, ok=True)
            except SQLAlchemyError as exp:
                await db.rollback()
                logger.error(f"DB error on avatar: {exp}")
                progress_registry.finish(user_id, ok=False, error="db_error")
            except Exception as exp:
                await db.rollback()
                logger.error(f"Unexpected avatar error: {exp}")
                progress_registry.finish(user_id, ok=False, error="unexpected")



