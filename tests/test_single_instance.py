import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from localdictate import single_instance


class TestSingleInstance:
    def test_second_acquire_is_refused_and_lock_is_reusable(self, tmp_path):
        lock = tmp_path / "ld.lock"
        with patch.object(single_instance, "_lock_path", return_value=lock):
            first = single_instance.acquire()
            assert hasattr(first, "fileno")  # got a real held lock

            second = single_instance.acquire()
            assert second is None  # second instance refused

            first.close()  # releasing lets a fresh instance start
            third = single_instance.acquire()
            assert hasattr(third, "fileno")
            third.close()

    def test_lock_is_released_when_holding_process_exits(self, tmp_path):
        """A crashed/killed instance must not leave a stale lock behind."""
        lock = str(tmp_path / "ld.lock")
        child_code = (
            "import sys, time\n"
            "from pathlib import Path\n"
            "from unittest.mock import patch\n"
            "from localdictate import single_instance\n"
            "with patch.object(single_instance, '_lock_path', return_value=Path(sys.argv[1])):\n"
            "    h = single_instance.acquire()\n"
            "    print('READY' if hasattr(h, 'fileno') else 'FAIL', flush=True)\n"
            "    time.sleep(10)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", child_code, lock], stdout=subprocess.PIPE, text=True
        )
        try:
            assert child.stdout.readline().strip() == "READY"

            with patch.object(single_instance, "_lock_path", return_value=Path(lock)):
                assert single_instance.acquire() is None  # refused while child alive
        finally:
            child.terminate()
            child.wait()

        time.sleep(0.2)  # let the OS reclaim the fd/lock
        with patch.object(single_instance, "_lock_path", return_value=Path(lock)):
            handle = single_instance.acquire()
        assert hasattr(handle, "fileno")  # lock freed after holder exited
        handle.close()
