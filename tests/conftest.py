from pathlib import Path
import pytest

def pytest_collection_modifyitems(items):
    if not Path('eval/splits.json').exists():
        for item in items:
            if item.name == 'test_split_isolation_and_group_counts':
                item.add_marker(pytest.mark.skip(reason='Historical evaluation membership is intentionally absent from public export'))
