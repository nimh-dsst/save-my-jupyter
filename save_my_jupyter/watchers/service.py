from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import sleep

from save_my_jupyter.domain import (
    CommitMode,
    NotebookContext,
    NotebookPath,
    PathEventType,
    RelativeWatchPath,
    UserId,
    UserMetadata,
    WatchedPathEvent,
    WatchedPathSnapshotRequest,
)
from save_my_jupyter.parsing import normalize_relative_path_text


@dataclass(slots=True, kw_only=True)
class RegisteredWatch:
    commit_mode: CommitMode
    notebook_context: NotebookContext
    notebook_path: NotebookPath
    root: Path
    user_id: UserId
    user_metadata: UserMetadata
    watch_paths: tuple[RelativeWatchPath, ...]
    known_state: dict[str, float | None] = field(default_factory=dict)


class DefaultWatchService:
    def __init__(
        self,
        *,
        event_callback: (
            Callable[[UserId, WatchedPathSnapshotRequest], None] | None
        ) = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._watches: dict[str, RegisteredWatch] = {}
        self._lock = Lock()
        self._event_callback = event_callback
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = Event()
        self._polling_thread: Thread | None = None

    def register_notebook_watch(
        self,
        *,
        commit_mode: CommitMode,
        notebook_context: NotebookContext,
        watch_paths: tuple[RelativeWatchPath, ...],
        root: Path,
        user_id: UserId,
        user_metadata: UserMetadata,
    ) -> None:
        notebook = Path(notebook_context.notebook_path).resolve()
        registered_watch = RegisteredWatch(
            commit_mode=commit_mode,
            notebook_context=notebook_context,
            notebook_path=notebook_context.notebook_path,
            root=root.resolve(),
            user_id=user_id,
            user_metadata=user_metadata,
            watch_paths=watch_paths,
        )
        registered_watch.known_state = self._snapshot_state(registered_watch)
        with self._lock:
            self._watches[str(notebook)] = registered_watch
        self.start()

    def unregister_notebook_watch(self, notebook_path: NotebookPath) -> None:
        notebook = Path(notebook_path).resolve()
        should_stop = False
        with self._lock:
            self._watches.pop(str(notebook), None)
            if not self._watches:
                should_stop = True
        if should_stop:
            self.stop()

    def dispatch_fs_event(
        self,
        path: str,
        event_type: str,
    ) -> tuple[WatchedPathEvent, ...]:
        candidate = Path(path).resolve()
        parsed_event_type = PathEventType(event_type)
        events: list[WatchedPathEvent] = []
        for registered_watch in self._watches.values():
            try:
                relative_path = candidate.relative_to(registered_watch.root)
            except ValueError:
                continue

            relative_text = normalize_relative_path_text(
                str(relative_path).replace("\\", "/")
            )
            if not self._matches_watch(relative_text, registered_watch.watch_paths):
                continue
            events.append(
                WatchedPathEvent(
                    relative_path=RelativeWatchPath(relative_text),
                    event_type=parsed_event_type,
                    timestamp=datetime.now(UTC),
                )
            )
        return tuple(events)

    def set_event_callback(
        self,
        callback: Callable[[UserId, WatchedPathSnapshotRequest], None],
    ) -> None:
        self._event_callback = callback

    def start(self) -> None:
        if self._polling_thread is not None and self._polling_thread.is_alive():
            return
        self._stop_event.clear()
        self._polling_thread = Thread(target=self._poll_loop, daemon=True)
        self._polling_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._polling_thread is not None and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=self._poll_interval_seconds * 2)
        self._polling_thread = None

    def poll_once(self) -> tuple[WatchedPathSnapshotRequest, ...]:
        requests: list[WatchedPathSnapshotRequest] = []
        with self._lock:
            watches = tuple(self._watches.values())

        for registered_watch in watches:
            new_state = self._snapshot_state(registered_watch)
            events = self._diff_states(registered_watch, new_state)
            if not events:
                continue
            registered_watch.known_state = new_state
            for event in events:
                requests.append(
                    WatchedPathSnapshotRequest(
                        notebook_context=registered_watch.notebook_context,
                        commit_mode=registered_watch.commit_mode,
                        user_metadata=registered_watch.user_metadata,
                        watched_path_event=event,
                    )
                )
        return tuple(requests)

    def _matches_watch(
        self,
        relative_path: str,
        watch_paths: tuple[RelativeWatchPath, ...],
    ) -> bool:
        return any(
            relative_path == str(watch_path)
            or relative_path.startswith(f"{watch_path}/")
            for watch_path in watch_paths
        )

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            snapshot_requests = self.poll_once()
            if self._event_callback is not None:
                for snapshot_request in snapshot_requests:
                    try:
                        self._event_callback(
                            self._user_id_for_request(snapshot_request),
                            snapshot_request,
                        )
                    except Exception:
                        continue
            sleep(self._poll_interval_seconds)

    def _user_id_for_request(self, request: WatchedPathSnapshotRequest) -> UserId:
        with self._lock:
            for registered_watch in self._watches.values():
                if registered_watch.notebook_context == request.notebook_context:
                    return registered_watch.user_id
        raise RuntimeError("Watch request could not be mapped back to a user.")

    def _snapshot_state(
        self,
        registered_watch: RegisteredWatch,
    ) -> dict[str, float | None]:
        state: dict[str, float | None] = {}
        for watch_path in registered_watch.watch_paths:
            absolute_path = registered_watch.root / str(watch_path)
            if absolute_path.is_dir():
                for child in absolute_path.rglob("*"):
                    if not child.is_file():
                        continue
                    relative_path = normalize_relative_path_text(
                        str(child.relative_to(registered_watch.root)).replace("\\", "/")
                    )
                    state[relative_path] = child.stat().st_mtime_ns
                continue

            normalized_watch_path = normalize_relative_path_text(str(watch_path))
            if absolute_path.exists() and absolute_path.is_file():
                state[normalized_watch_path] = absolute_path.stat().st_mtime_ns
            else:
                state.setdefault(normalized_watch_path, None)
        return state

    def _diff_states(
        self,
        registered_watch: RegisteredWatch,
        new_state: dict[str, float | None],
    ) -> tuple[WatchedPathEvent, ...]:
        events: list[WatchedPathEvent] = []
        known_keys = set(registered_watch.known_state)
        new_keys = set(new_state)

        for relative_path in sorted(new_keys | known_keys):
            previous_value = registered_watch.known_state.get(relative_path)
            current_value = new_state.get(relative_path)
            if previous_value is None and current_value is None:
                continue
            if relative_path not in known_keys and current_value is not None:
                events.append(
                    WatchedPathEvent(
                        relative_path=RelativeWatchPath(relative_path),
                        event_type=PathEventType.CREATED,
                        timestamp=datetime.now(UTC),
                    )
                )
                continue
            if relative_path not in new_keys and previous_value is not None:
                events.append(
                    WatchedPathEvent(
                        relative_path=RelativeWatchPath(relative_path),
                        event_type=PathEventType.DELETED,
                        timestamp=datetime.now(UTC),
                    )
                )
                continue
            if previous_value != current_value:
                events.append(
                    WatchedPathEvent(
                        relative_path=RelativeWatchPath(relative_path),
                        event_type=PathEventType.MODIFIED,
                        timestamp=datetime.now(UTC),
                    )
                )
        return tuple(events)
