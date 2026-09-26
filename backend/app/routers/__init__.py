"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import berth as router_berth
from app.routers import vessel as router_vessel
from app.routers import voyage as router_voyage
from app.routers import crane as router_crane
from app.routers import loading as router_loading
from app.routers import yard as router_yard
from app.routers import container as router_container
from app.routers import yardstore as router_yardstore
from app.routers import gate as router_gate
from app.routers import truck as router_truck
from app.routers import tally as router_tally
from app.routers import damage as router_damage
from app.routers import manifest as router_manifest
from app.routers import docarchive as router_docarchive
from app.routers import storage as router_storage
from app.routers import pilot as router_pilot
from app.routers import safety as router_safety
from app.routers import customer as router_customer
from app.routers import settle as router_settle

ROUTERS = [router_berth, router_vessel, router_voyage, router_crane, router_loading, router_yard, router_container, router_yardstore, router_gate, router_truck, router_tally, router_damage, router_manifest, router_docarchive, router_storage, router_pilot, router_safety, router_customer, router_settle]
