import threading
import time

import pytest

from darc_lib import DotArcError
from darc_lib.lock import locked


def test_lock_creates_file_and_releases(tmp_path):
    p = tmp_path / "lock"
    with locked(str(p), timeout_s=1):
        assert p.exists()
    with locked(str(p), timeout_s=1):
        pass


def test_second_holder_times_out(tmp_path):
    p = str(tmp_path / "lock")
    inside = threading.Event()
    release = threading.Event()

    def holder():
        with locked(p, timeout_s=1):
            inside.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    inside.wait(2)
    t0 = time.monotonic()
    with pytest.raises(DotArcError) as e:
        with locked(p, timeout_s=0.3):
            pass
    assert e.value.code == "LOCK_TIMEOUT" and e.value.exit_code == 5
    assert 0.25 <= time.monotonic() - t0 < 2
    release.set()
    t.join()
    with locked(p, timeout_s=1):
        pass
