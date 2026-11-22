import json
import logging
import os
import threading
import time
from contextlib import contextmanager

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger("browser_lock")

DEFAULT_LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "playwright.lock")
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_STALE_SECONDS = 300.0

_GLOBAL_THREAD_LOCK = threading.RLock()
_CURRENT_OWNER = {"pid": None, "thread_id": None, "caller": None, "acquired_at": None}
_REENTRANCY_COUNT = 0


def _is_process_alive(pid):
    """Verifica se um PID existe e está ativo no sistema operacional."""
    if not pid or pid <= 0:
        return False
    try:
        if psutil and hasattr(psutil, "pid_exists"):
            return psutil.pid_exists(pid)
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return True


def _read_lock_file(lock_path):
    """Lê metadados do lockfile se existir."""
    if not os.path.exists(lock_path):
        return None
    try:
        with open(lock_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def _cleanup_stale_lock(lock_path, max_stale_seconds):
    """Verifica se o lock existente é órfão (processo morto ou tempo expirado) e limpa se necessário."""
    info = _read_lock_file(lock_path)
    if info is None:
        return True

    pid = info.get("pid")
    acquired_at = info.get("acquired_at", 0)
    now = time.time()

    is_dead = pid and not _is_process_alive(pid)
    is_expired = (now - acquired_at) > max_stale_seconds if acquired_at else False

    if is_dead or is_expired:
        reason = "processo morto" if is_dead else f"idade de {now - acquired_at:.1f}s excedeu {max_stale_seconds}s"
        logger.warning(f"[BrowserLock] Removendo lockfile órfão ({reason}): {lock_path}")
        try:
            os.remove(lock_path)
            return True
        except OSError:
            return False
    return False


class BrowserLockManager:
    """
    Gerenciador central de exclusividade mútua para instâncias de Chromium/Playwright.
    Garante que no host inteiro (entre threads e entre processos) apenas 1 navegador
    rode por vez, preservando a memória RAM em ambientes restritos (como 1 GB de RAM).
    """

    def __init__(self, lock_path=None, max_stale_seconds=DEFAULT_MAX_STALE_SECONDS):
        self.lock_path = lock_path or DEFAULT_LOCK_PATH
        self.max_stale_seconds = max_stale_seconds

    def acquire(self, timeout=DEFAULT_TIMEOUT, caller="unspecified", on_wait=None):
        """
        Adquire a trava de thread e a trava de arquivo a nível de SO.
        Aguarda até 'timeout' segundos. Chama 'on_wait()' periodicamente durante a espera.
        """
        global _REENTRANCY_COUNT
        current_thread = threading.get_ident()

        # Reentrância na mesma thread: se já possui o lock, incrementa contador
        if _CURRENT_OWNER.get("thread_id") == current_thread and _CURRENT_OWNER.get("pid") == os.getpid():
            _REENTRANCY_COUNT += 1
            return True

        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        deadline = time.monotonic() + max(0.1, float(timeout))
        fd = None

        # 1. Trava em nível de thread no processo atual
        time_for_thread = max(0.1, deadline - time.monotonic())
        thread_acquired = _GLOBAL_THREAD_LOCK.acquire(timeout=time_for_thread)
        if not thread_acquired:
            owner = _CURRENT_OWNER.get("caller") or "outra thread"
            raise TimeoutError(
                f"[BrowserLock] Timeout ({timeout}s) aguardando liberação do Chromium por outra thread ({owner})."
            )

        try:
            # 2. Trava em nível de processo no sistema operacional (arquivo atômico)
            while True:
                try:
                    fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    payload = {
                        "pid": os.getpid(),
                        "thread_id": current_thread,
                        "caller": str(caller)[:120],
                        "acquired_at": time.time(),
                    }
                    os.write(fd, json.dumps(payload).encode("utf-8"))
                    os.close(fd)
                    fd = None

                    _CURRENT_OWNER.update({
                        "pid": os.getpid(),
                        "thread_id": current_thread,
                        "caller": str(caller)[:120],
                        "acquired_at": time.time(),
                    })
                    _REENTRANCY_COUNT = 1
                    return True
                except FileExistsError:
                    if _cleanup_stale_lock(self.lock_path, self.max_stale_seconds):
                        continue

                # Verifica deadline
                if time.monotonic() >= deadline:
                    owner_info = _read_lock_file(self.lock_path) or _CURRENT_OWNER
                    caller_name = owner_info.get("caller") or "desconhecido"
                    pid = owner_info.get("pid") or "?"
                    raise TimeoutError(
                        f"[BrowserLock] Timeout ({timeout}s) aguardando liberação do Chromium pelo processo PID {pid} ({caller_name})."
                    )

                if on_wait and callable(on_wait):
                    try:
                        on_wait()
                    except Exception:
                        pass

                time.sleep(0.2)
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            _GLOBAL_THREAD_LOCK.release()
            raise

    def release(self):
        """Libera a trava de arquivo e a trava de thread com suporte a reentrância."""
        global _REENTRANCY_COUNT
        current_thread = threading.get_ident()

        if _CURRENT_OWNER.get("thread_id") == current_thread and _CURRENT_OWNER.get("pid") == os.getpid():
            _REENTRANCY_COUNT -= 1
            if _REENTRANCY_COUNT > 0:
                return

        try:
            info = _read_lock_file(self.lock_path)
            if info and info.get("pid") == os.getpid():
                try:
                    os.remove(self.lock_path)
                except OSError:
                    pass
        finally:
            _CURRENT_OWNER.update({"pid": None, "thread_id": None, "caller": None, "acquired_at": None})
            _REENTRANCY_COUNT = 0
            try:
                _GLOBAL_THREAD_LOCK.release()
            except RuntimeError:
                pass

    def is_locked(self):
        """Retorna True se o lock estiver ativo em qualquer thread ou processo."""
        if _CURRENT_OWNER.get("pid") is not None:
            return True
        info = _read_lock_file(self.lock_path)
        if not info:
            return False
        pid = info.get("pid")
        return bool(pid and _is_process_alive(pid))

    def get_lock_info(self):
        """Retorna metadados da tarefa que detém o lock atualmente."""
        return _read_lock_file(self.lock_path) or dict(_CURRENT_OWNER)

    def force_release(self):
        """Liberação de emergência em casos de recuperação de estado."""
        global _REENTRANCY_COUNT
        try:
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except OSError:
            pass
        _CURRENT_OWNER.update({"pid": None, "thread_id": None, "caller": None, "acquired_at": None})
        _REENTRANCY_COUNT = 0
        while _GLOBAL_THREAD_LOCK.locked():
            try:
                _GLOBAL_THREAD_LOCK.release()
            except RuntimeError:
                break


_DEFAULT_MANAGER = BrowserLockManager()


@contextmanager
def acquire_browser_lock(timeout=DEFAULT_TIMEOUT, caller="unspecified", on_wait=None, lock_path=None):
    """
    Context manager centralizado para uso com 'with':
    with acquire_browser_lock(timeout=120, caller="GoogleMapsSource"):
        with sync_playwright() as p:
            browser = p.chromium.launch(...)
    """
    manager = BrowserLockManager(lock_path=lock_path) if lock_path else _DEFAULT_MANAGER
    manager.acquire(timeout=timeout, caller=caller, on_wait=on_wait)
    try:
        yield manager
    finally:
        manager.release()
