"""optimize_presets CLI 脚本测试"""
import sys
import ast
import tempfile
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


def test_build_presets_list_source_with_params():
    """构造预设列表源码 - 含参数"""
    from scripts.optimize_presets import _build_presets_list_source
    presets = [
        {"name": "🏆 激进高收益型", "params": {"lookback_momentum": 20, "top_n": 3}},
        {"name": "⚙️ 自定义参数", "params": None},
    ]
    src = _build_presets_list_source(presets)
    tree = ast.parse(src)
    assert isinstance(tree.body[0].value, ast.List)
    assert len(tree.body[0].value.elts) == 2
    assert "🏆 激进高收益型" in src
    assert "lookback_momentum" in src
    assert "None" in src


def test_update_presets_in_settings_replaces_correctly():
    """AST 精确替换 PARAM_PRESETS['多因子轮动']"""
    from scripts.optimize_presets import update_presets_in_settings

    tmpdir = tempfile.mkdtemp()
    settings_path = Path(tmpdir) / "settings.py"
    original = '''PARAM_PRESETS = {
    "多因子轮动": [
        {"name": "旧预设", "params": {"lookback_momentum": 60}},
        {"name": "⚙️ 自定义参数", "params": None},
    ],
}

OTHER_CONST = 42
'''
    settings_path.write_text(original, encoding='utf-8')

    new_presets = [
        {"name": "🏆 新预设", "params": {"lookback_momentum": 20, "lookback_volatility": 60, "top_n": 5, "rebalance_freq": 20}},
        {"name": "⚙️ 自定义参数", "params": None},
    ]
    update_presets_in_settings(str(settings_path), new_presets)

    new_src = settings_path.read_text(encoding='utf-8')
    tree = ast.parse(new_src)

    found_other = False
    found_presets = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == 'OTHER_CONST':
                    found_other = True
                elif node.targets[0].id == 'PARAM_PRESETS':
                    found_presets = True
                    value_node = node.value
                    assert isinstance(value_node, ast.Dict)
                    key = value_node.keys[0]
                    assert isinstance(key, ast.Constant) and key.value == "多因子轮动"
                    list_node = value_node.values[0]
                    assert len(list_node.elts) == 2
    assert found_other, "OTHER_CONST 应保留"
    assert found_presets, "PARAM_PRESETS 应存在"
    assert "旧预设" not in new_src
    assert "🏆 新预设" in new_src

    shutil.rmtree(tmpdir)


def test_update_presets_rollback_on_failure():
    """AST 写回失败时回滚 .bak

    传入不可序列化的 object() 作为 params，触发 _build_presets_list_source
    的 f-string 拼接抛 TypeError，验证原文件保持不变。
    """
    from scripts.optimize_presets import update_presets_in_settings

    tmpdir = tempfile.mkdtemp()
    settings_path = Path(tmpdir) / "settings.py"
    original = 'PARAM_PRESETS = {"多因子轮动": []}\n'
    settings_path.write_text(original, encoding='utf-8')

    with pytest.raises(Exception):
        update_presets_in_settings(str(settings_path), [{"name": "bad", "params": object()}])

    assert settings_path.read_text(encoding='utf-8') == original
    shutil.rmtree(tmpdir)


def test_multi_factor_param_ranges_exists():
    """MULTI_FACTOR_PARAM_RANGES 常量存在且组合数为144"""
    from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES
    total = 1
    for v in MULTI_FACTOR_PARAM_RANGES.values():
        total *= len(v)
    assert total == 144, f"期望144组合，实际{total}"


def test_dual_momentum_param_ranges_removed():
    """DUAL_MOMENTUM_PARAM_RANGES 已删除"""
    from strategy import optimizer
    assert not hasattr(optimizer, 'DUAL_MOMENTUM_PARAM_RANGES'), \
        "DUAL_MOMENTUM_PARAM_RANGES 应已删除"
