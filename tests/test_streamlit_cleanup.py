"""Streamlit 清理验证测试"""
import sys
import ast
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_streamlit_app_syntax_valid():
    """streamlit_app.py 语法正确"""
    src = Path('presentation/streamlit_app.py').read_text(encoding='utf-8')
    ast.parse(src)


def test_streamlit_app_no_dual_momentum_references():
    """streamlit_app.py 不再引用双动量"""
    src = Path('presentation/streamlit_app.py').read_text(encoding='utf-8')
    forbidden = [
        'dual_momentum',
        '双动量轮动',
        'DUAL_MOMENTUM_PARAM_RANGES',
        'generate_walk_forward_presets',
        'optimize_clicked',
        'wf_presets',
        'strategy_type',
    ]
    found = [f for f in forbidden if f in src]
    assert not found, f"streamlit_app.py 仍有残留引用: {found}"


def test_settings_no_dual_momentum_preset():
    """settings.py 中 PARAM_PRESETS 不含双动量轮动键"""
    from config.settings import PARAM_PRESETS
    assert '双动量轮动' not in PARAM_PRESETS, "PARAM_PRESETS 仍含双动量轮动键"
    assert '多因子轮动' in PARAM_PRESETS, "PARAM_PRESETS 应含多因子轮动键"
