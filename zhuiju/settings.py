# -*- coding: utf-8 -*-
"""这台机器上的运行设置：后台页面上能改的那几项，存在 zhuiju/data/settings.json。

为什么是**文件**而不是 stats.db：
  * stats.db 是"发生过什么"（每一次搜索、每一次点开），本设置是"以后要怎么做"。
    日志库会被 `KEEP_DAYS` 裁剪、也有人会整个删掉重统计，配置不该跟着一起没。
  * 那个库是隐私数据（IP / UA / 关键词），本设置不是；混在一起，将来"这个库能不能
    拷给别人看分布"就要多想一层。
  * 读的时机也相反：每次访问都要判"今天该不该更新"，用 SQLite 就得跟着开库连接；
    文件只在内容变了（mtime）之后重读一次，改完立刻生效，也不给每次请求添开销。
真正需要库的场景是"多台实例共享同一份设置"或"要查谁在什么时候改的"，本机单进程用不上。

与 admin.json 的分工：那个文件里是**口令与密钥**（含秘密，不能外传），
这里放**不敏感的行为设置**；两者都是运行时可写、都不进版本库。
`ZHUIJU_REFRESH_HOUR` 环境变量仍然优先于文件 —— 部署时想用环境定死就该定得下来，
但页面上会明说现在被环境变量顶着（不然"我明明改成 6 点了怎么还是 2 点"最难查）。
"""
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PATH = BASE / "zhuiju" / "data" / "settings.json"

# 默认值同时是"合法的键有哪些"的唯一清单：页面上渲染什么、存什么、认什么，都从这里出
DEFAULTS = {"refresh_hour": 2, "human_gate": 1, "human_hours": 12}
# 每项的范围与说法。下限 0 上限 23 是因为这就是"几点"，写 24 会被当成 0 天的下一天，
# 负数更是直接把逻辑日推到明天去。
# kind 只管**页面上怎么渲染**（number 还是 开/关 下拉），校验一律按 0..max 的整数走：
# 少一种类型就少一处"表单和后端各判各的"的口子
SPEC = {
    "refresh_hour": {
        "label": "每日更新时间（小时）",
        "hint": "到这个点之后的第一次访问才真的跑更新；这一整天没人访问就不会跑（本站不用系统计划任务）。",
        "min": 0, "max": 23, "kind": "int",
        "env": "ZHUIJU_REFRESH_HOUR",
    },
    "human_gate": {
        "label": "真人滑块验证",
        "hint": "关掉就等于全站对脚本敞开：所有页面与接口都不再要 cookie（搜索引擎爬虫豁免那条逻辑本身也不走了）。",
        "min": 0, "max": 1, "kind": "bool",
        "env": "ZHUIJU_HUMAN_GATE",
    },
    "human_hours": {
        "label": "验证通过后管多久（小时）",
        "hint": "只影响签发的 cookie 有效期；改小了已经发出去的那枚还是按老时长走完（签名里带的是签发那一刻的到期时间）。",
        "min": 1, "max": 720, "kind": "int",
        "env": "ZHUIJU_HUMAN_HOURS",
    },
}

_cached = {"mtime": None, "vals": {}}


def _file_values() -> tuple[dict, float | None]:
    """读文件；缺失/坏了都回空字典（坏文件不该让站点起不来，也不该偷偷改回去）。"""
    try:
        mt = PATH.stat().st_mtime
    except OSError:
        return {}, None
    if _cached["mtime"] == mt:
        return dict(_cached["vals"]), mt
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _cached.update(mtime=mt, vals={})
        return {}, mt
    vals = raw if isinstance(raw, dict) else {}
    _cached.update(mtime=mt, vals=dict(vals))
    return dict(vals), mt


def _coerce(key, raw):
    """把任何一种来路（文件、表单、环境变量）的值收成合法整数；不合法返回 None。"""
    spec = SPEC[key]
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return n if spec["min"] <= n <= spec["max"] else None


def effective() -> dict:
    """每一项当前生效的值。优先级：环境变量 > settings.json > 代码里的默认值。"""
    file_vals, _ = _file_values()
    out = {}
    for key, dflt in DEFAULTS.items():
        env = os.environ.get(SPEC[key]["env"]) if SPEC[key].get("env") else None
        val = _coerce(key, env) if env is not None else None
        if val is None:
            val = _coerce(key, file_vals.get(key))
        out[key] = dflt if val is None else val
    return out


def source_of(key: str) -> str:
    """这一项当前是谁定的：'env' / 'file' / 'default'。页面上要能把判据摆在脸上。"""
    spec = SPEC[key]
    env = os.environ.get(spec["env"]) if spec.get("env") else None
    if env is not None and _coerce(key, env) is not None:
        return "env"
    file_vals, _ = _file_values()
    if _coerce(key, file_vals.get(key)) is not None:
        return "file"
    return "default"


def set_value(key: str, raw):
    """校验并落盘。返回 (是否改动, 错误说明) —— 不合法就一条都不写，别存半套。"""
    if key not in SPEC:
        return False, f"没有「{key}」这一项设置"
    val = _coerce(key, raw)
    if val is None:
        spec = SPEC[key]
        return False, f"「{spec['label']}」要是 {spec['min']}–{spec['max']} 之间的整数，你给的是「{raw}」"
    file_vals, _ = _file_values()
    # 只保留 SPEC 里认识的键：手抖写进去的别的东西（或者以后删掉的一项设置）不该长期留着，
    # 否则这个文件会变成没人敢动的垃圾场
    kept = {k: file_vals[k] for k in SPEC if k in file_vals}
    kept[key] = val
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PATH)
    _cached.update(mtime=None, vals={})          # 强制下次重读，改完立刻生效
    return True, None


def refresh_hour() -> int:
    """每天几点算新的一天（逻辑日分界）。autoupdate.logical_day() 用它。"""
    return effective()["refresh_hour"]


def human_gate() -> bool:
    """全站真人门禁开不开。关掉等于对脚本敞开，页面上会写明这一点。"""
    return effective()["human_gate"] == 1


def human_hours() -> int:
    """滑块通过后签发的 cookie 管多少小时。"""
    return effective()["human_hours"]


def fields() -> list:
    """后台「设置」那一节要渲染的每一项：(键, 说法, 当前生效值)。

    表单从 DEFAULTS 生成而不是在模板里写死字段：加一项设置只改这一处，
    不会出现"后端认这个键、页面上没有那一格"或者反过来。
    """
    eff = effective()
    return [(k, SPEC[k], eff[k]) for k in DEFAULTS]
