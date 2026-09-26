"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
需要跨重启保留数据的模块（如单证材料归档）可登记持久化：落盘为 JSON 文件，
写盘走"先写临时文件再替换"的原子方式，写到一半断掉也不会留下半份数据。
未登记的模块行为不变，仍然只是内存数据。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._persisted: set[str] = set()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def enable_persistence(self, module: str) -> None:
        """把模块登记为持久化：已有落盘数据就接着用，之后的 save 才会写盘。"""
        self._persisted.add(module)
        path = self._data_path(module)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # 落盘文件读不出来就先顶着示例数据跑，不把服务拖垮
        if isinstance(data, list):
            self._tables[module] = [dict(row) for row in data]

    def save(self, module: str) -> None:
        """把已登记模块的当前数据原子写盘；未登记的模块调用直接跳过。"""
        if module not in self._persisted:
            return
        path = self._data_path(module)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.rows(module), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    @staticmethod
    def _data_path(module: str) -> Path:
        return DATA_DIR / f"{module}.json"

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
