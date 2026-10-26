import pytest

from sigtool.demo import build_code, build_pe


@pytest.fixture
def make_build(tmp_path):
    def make(name: str = "game.exe", **kwargs) -> str:
        path = tmp_path / name
        path.write_bytes(build_pe(build_code(**kwargs)))
        return str(path)

    return make
