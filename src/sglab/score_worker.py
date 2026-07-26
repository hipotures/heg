from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
import hashlib
import os
import select
import struct
import time

from .locations import score_worker_path
from .model import BitGraph
from .resources import set_address_space_limit


PROTOCOL_VERSION = 1
COMMAND_SCORE = 1
COMMAND_QUIT = 2
STATUS_OK = 0
STATUS_DOMINATED = 2
MAXIMUM_FRAME_BYTES = 64 * 1024
DEFAULT_REQUEST_TIMEOUT_SECONDS = 2.0
DEFAULT_WORKER_MEMORY_BYTES = 64 * 1024 * 1024

_REQUEST_PREFIX = struct.Struct("<4sHHI")
_REQUEST_BODY = struct.Struct("<QHHIIIIIII")
_RESPONSE_HEADER = struct.Struct("<4sHHQHHI")
_COUNT_RESULT = struct.Struct("<HBBIQQ")


class ScoreWorkerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CycleCountResult:
    length: int
    count: int
    complete: bool
    nodes: int
    elapsed_ns: int


@dataclass(frozen=True, slots=True)
class ScoreWorkerResponse:
    results: tuple[CycleCountResult, ...]
    dominated: bool


class PersistentScoreWorker:
    """One bounded binary-protocol C++ scorer process."""

    def __init__(
        self,
        binary: Path | None = None,
        *,
        timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        memory_limit_bytes: int = DEFAULT_WORKER_MEMORY_BYTES,
    ):
        if timeout_seconds <= 0:
            raise ValueError("score-worker timeout must be positive")
        if memory_limit_bytes < 16 * 1024 * 1024:
            raise ValueError("score-worker memory limit is too small")
        self.binary = (binary or score_worker_path()).resolve()
        self.timeout_seconds = timeout_seconds
        self.memory_limit_bytes = memory_limit_bytes
        self.process: Popen[bytes] | None = None
        self.request_id = 0
        self.binary_sha256 = (
            hashlib.sha256(self.binary.read_bytes()).hexdigest()
            if self.binary.is_file()
            else None
        )

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if not self.binary.is_file():
            raise ScoreWorkerError(
                f"score worker is unavailable: {self.binary}"
            )

        def child_setup() -> None:
            set_address_space_limit(self.memory_limit_bytes)

        try:
            self.process = Popen(
                [str(self.binary), "--serve"],
                stdin=PIPE,
                stdout=PIPE,
                stderr=DEVNULL,
                bufsize=0,
                start_new_session=True,
                preexec_fn=child_setup,
            )
        except OSError as error:
            raise ScoreWorkerError(
                f"could not start score worker: {error}"
            ) from error

    def score(
        self,
        graph: BitGraph,
        *,
        limit: int,
        node_budget: int,
        cutoff: tuple[int, int, int] | None = None,
        cutoff_inclusive: bool = False,
    ) -> ScoreWorkerResponse:
        if limit < 1 or node_budget < 1:
            raise ValueError("score-worker bounds must be positive")
        if self.process is None:
            self.start()
        elif self.process.poll() is not None:
            raise ScoreWorkerError("score worker exited before request")
        process = self._active_process()
        self.request_id += 1
        request_id = self.request_id
        word_count = (graph.n + 63) // 64
        payload = bytearray(graph.n * word_count * 8)
        offset = 0
        for row in graph.rows:
            struct.pack_into("<Q", payload, offset, row & ((1 << 64) - 1))
            offset += 8
            if word_count == 2:
                struct.pack_into("<Q", payload, offset, row >> 64)
                offset += 8
        request = (
            _REQUEST_PREFIX.pack(
                b"SGSC",
                PROTOCOL_VERSION,
                COMMAND_SCORE,
                len(payload),
            )
            + _REQUEST_BODY.pack(
                request_id,
                graph.n,
                word_count,
                limit,
                node_budget,
                1 if cutoff is not None else 0,
                cutoff[0] if cutoff is not None else 0,
                cutoff[1] if cutoff is not None else 0,
                cutoff[2] if cutoff is not None else 0,
                int(cutoff_inclusive),
            )
            + payload
        )
        if len(request) > MAXIMUM_FRAME_BYTES:
            raise ScoreWorkerError("score-worker request is oversized")
        started = time.monotonic()
        self._write_all(process, request)
        header = self._read_exact(
            process,
            _RESPONSE_HEADER.size,
            started=started,
        )
        (
            magic,
            version,
            status,
            response_id,
            result_count,
            reserved,
            payload_bytes,
        ) = _RESPONSE_HEADER.unpack(header)
        if (
            magic != b"SGSR"
            or version != PROTOCOL_VERSION
            or response_id != request_id
            or reserved != 0
            or payload_bytes != result_count * _COUNT_RESULT.size
            or payload_bytes > MAXIMUM_FRAME_BYTES
        ):
            raise ScoreWorkerError("invalid score-worker response header")
        response_payload = self._read_exact(
            process,
            payload_bytes,
            started=started,
        )
        if status not in {STATUS_OK, STATUS_DOMINATED}:
            raise ScoreWorkerError("score worker rejected the request")
        results = []
        for index in range(result_count):
            (
                length,
                complete,
                record_reserved,
                count,
                nodes,
                elapsed_ns,
            ) = _COUNT_RESULT.unpack_from(
                response_payload, index * _COUNT_RESULT.size
            )
            if complete not in (0, 1) or record_reserved != 0:
                raise ScoreWorkerError("invalid score-worker count record")
            results.append(
                CycleCountResult(
                    length=length,
                    count=count,
                    complete=bool(complete),
                    nodes=nodes,
                    elapsed_ns=elapsed_ns,
                )
            )
        return ScoreWorkerResponse(
            results=tuple(results),
            dominated=status == STATUS_DOMINATED,
        )

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(
                    _REQUEST_PREFIX.pack(
                        b"SGSC",
                        PROTOCOL_VERSION,
                        COMMAND_QUIT,
                        0,
                    )
                )
                process.stdin.flush()
                process.wait(timeout=0.5)
            except (BrokenPipeError, OSError, TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()

    def restart(self) -> None:
        self.close()
        self.start()

    @property
    def pid(self) -> int | None:
        process = self.process
        return (
            process.pid
            if process is not None and process.poll() is None
            else None
        )

    def _active_process(self) -> Popen[bytes]:
        process = self.process
        if (
            process is None
            or process.poll() is not None
            or process.stdin is None
            or process.stdout is None
        ):
            raise ScoreWorkerError("score worker is not running")
        return process

    def _write_all(self, process: Popen[bytes], payload: bytes) -> None:
        if process.stdin is None:
            raise ScoreWorkerError("score-worker stdin is unavailable")
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise ScoreWorkerError("score-worker request failed") from error

    def _read_exact(
        self,
        process: Popen[bytes],
        size: int,
        *,
        started: float,
    ) -> bytes:
        if process.stdout is None:
            raise ScoreWorkerError("score-worker stdout is unavailable")
        result = bytearray()
        descriptor = process.stdout.fileno()
        while len(result) < size:
            remaining = self.timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise ScoreWorkerError("score-worker request timed out")
            readable, _, _ = select.select([descriptor], [], [], remaining)
            if not readable:
                raise ScoreWorkerError("score-worker request timed out")
            chunk = os.read(descriptor, size - len(result))
            if not chunk:
                raise ScoreWorkerError("score worker closed its response")
            result.extend(chunk)
        return bytes(result)

    def __enter__(self) -> PersistentScoreWorker:
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
