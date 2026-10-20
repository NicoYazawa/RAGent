"""冒烟：app 包可导入（此前无任何测试，先证明 pytest 装好了）"""


def test_app_importable():
    from app import config, main  # noqa: F401
    assert config.settings is not None
