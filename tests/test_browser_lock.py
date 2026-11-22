import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest

from browser_lock import (
    BrowserLockManager,
    acquire_browser_lock,
)


def _worker_process_task(lock_path, results_queue, sleep_duration=0.15):
    """Função executada por subprocessos para testar concorrência a nível de SO."""
    manager = BrowserLockManager(lock_path=lock_path)
    try:
        manager.acquire(timeout=5.0, caller="worker_process")
        results_queue.put({"event": "acquired", "pid": os.getpid(), "time": time.time()})
        time.sleep(sleep_duration)
        results_queue.put({"event": "released", "pid": os.getpid(), "time": time.time()})
    finally:
        manager.release()


class BrowserLockThreadConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self.temp_dir.name, "test_playwright.lock")
        self.manager = BrowserLockManager(lock_path=self.lock_path)

    def tearDown(self):
        self.manager.force_release()
        self.temp_dir.cleanup()

    def test_single_thread_concurrency_at_a_time(self):
        """Garante que múltiplas threads concorrentes nunca executem o Chromium simultaneamente."""
        active_instances = 0
        max_concurrent = 0
        state_lock = threading.Lock()
        execution_order = []

        def worker(thread_idx):
            nonlocal active_instances, max_concurrent
            with acquire_browser_lock(timeout=10.0, caller=f"thread_{thread_idx}", lock_path=self.lock_path):
                with state_lock:
                    active_instances += 1
                    if active_instances > max_concurrent:
                        max_concurrent = active_instances
                execution_order.append(f"start_{thread_idx}")
                time.sleep(0.08)
                with state_lock:
                    active_instances -= 1
                execution_order.append(f"end_{thread_idx}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(1, max_concurrent, "Nunca deve haver mais de 1 instância simultânea")
        self.assertEqual(8, len(execution_order))

    def test_timeout_raised_when_lock_cannot_be_acquired(self):
        """Garante que quando outra thread detém o lock, TimeoutError é lançado após o tempo especificado."""
        lock_held_event = threading.Event()
        release_event = threading.Event()

        def blocker():
            with acquire_browser_lock(timeout=5.0, caller="blocking_thread", lock_path=self.lock_path):
                lock_held_event.set()
                release_event.wait(timeout=2.0)

        t_blocker = threading.Thread(target=blocker)
        t_blocker.start()

        self.assertTrue(lock_held_event.wait(timeout=2.0))
        started_at = time.monotonic()
        with self.assertRaises(TimeoutError) as ctx:
            with acquire_browser_lock(timeout=0.3, caller="timed_out_thread", lock_path=self.lock_path):
                pass
        duration = time.monotonic() - started_at

        self.assertGreaterEqual(duration, 0.25)
        self.assertIn("blocking_thread", str(ctx.exception))

        release_event.set()
        t_blocker.join()

    def test_lock_released_on_unhandled_exception(self):
        """Garante que a trava é liberada mesmo quando uma exceção ocorre no bloco."""
        with self.assertRaises(ZeroDivisionError):
            with acquire_browser_lock(timeout=2.0, caller="failing_thread", lock_path=self.lock_path):
                _ = 1 / 0

        self.assertFalse(self.manager.is_locked())
        self.assertFalse(os.path.exists(self.lock_path))

        # Uma chamada seguinte deve conseguir adquirir o lock imediatamente sem erro
        acquired = False
        with acquire_browser_lock(timeout=1.0, caller="subsequent_thread", lock_path=self.lock_path):
            acquired = True
        self.assertTrue(acquired)

    def test_reentrant_lock_same_thread(self):
        """Garante suporte a reentrância na mesma thread sem causar deadlock."""
        with acquire_browser_lock(timeout=2.0, caller="outer", lock_path=self.lock_path):
            self.assertTrue(os.path.exists(self.lock_path))
            with acquire_browser_lock(timeout=2.0, caller="inner", lock_path=self.lock_path):
                self.assertTrue(self.manager.is_locked())
            self.assertTrue(self.manager.is_locked())
        self.assertFalse(self.manager.is_locked())
        self.assertFalse(os.path.exists(self.lock_path))


class BrowserLockProcessConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self.temp_dir.name, "process_playwright.lock")
        self.manager = BrowserLockManager(lock_path=self.lock_path)

    def tearDown(self):
        self.manager.force_release()
        self.temp_dir.cleanup()

    def test_multi_process_concurrency_serializes_execution(self):
        """Garante que processos distintos respeitem a exclusão mútua no arquivo de lock."""
        queue = multiprocessing.Queue()
        processes = [
            multiprocessing.Process(target=_worker_process_task, args=(self.lock_path, queue, 0.1))
            for _ in range(3)
        ]

        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=6.0)

        events = []
        while not queue.empty():
            events.append(queue.get())

        self.assertEqual(6, len(events))
        # Verifica se entre qualquer 'acquired' e 'released', não houve outro 'acquired'
        currently_active = 0
        max_active = 0
        for ev in sorted(events, key=lambda x: x["time"]):
            if ev["event"] == "acquired":
                currently_active += 1
                if currently_active > max_active:
                    max_active = currently_active
            elif ev["event"] == "released":
                currently_active -= 1

        self.assertEqual(1, max_active, "Nunca deve haver mais de 1 processo executando simultaneamente")

    def test_stale_lockfile_from_dead_process_is_cleaned_up(self):
        """Garante que se um processo morrer sem liberar o lockfile, ele é removido automaticamente."""
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        # Escreve um lockfile fingindo ser um PID inexistente
        fake_payload = {
            "pid": 99999999,  # PID garantidamente inexistente
            "thread_id": 1,
            "caller": "crashed_worker",
            "acquired_at": time.time() - 50,
        }
        with open(self.lock_path, "w", encoding="utf-8") as f:
            json.dump(fake_payload, f)

        # Deve detectar processo morto, limpar o arquivo e adquirir normalmente
        with acquire_browser_lock(timeout=2.0, caller="recovery_worker", lock_path=self.lock_path):
            self.assertTrue(self.manager.is_locked())
            info = self.manager.get_lock_info()
            self.assertEqual(os.getpid(), info.get("pid"))

        self.assertFalse(os.path.exists(self.lock_path))


if __name__ == "__main__":
    unittest.main()
