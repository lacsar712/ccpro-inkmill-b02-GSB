"""研磨机状态机：单条更新（PUT）与批量更新（batch-status）共用的同一套规则。

规则：
1. 合法跳转仅限 idle→grinding、idle→wash、grinding→wash、grinding→idle、wash→idle；
   其它跳转一律拒绝（调用方返回 409，中文错误并带 millCode）。
2. 同一车间同时最多一台 status=grinding；任何一次写入导致违反则整次失败。
3. 写入前必须先把 status 归一为 grinding / idle / wash（见 normalize_status）。
"""

from app.models.mill import MILL_STATUSES, Mill

#: 合法跳转表：(当前状态, 目标状态)
ALLOWED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("idle", "grinding"),
        ("idle", "wash"),
        ("grinding", "wash"),
        ("grinding", "idle"),
        ("wash", "idle"),
    }
)

STATUS_LABELS = {"grinding": "研磨中", "idle": "待机", "wash": "清洗"}


def normalize_status(raw: object) -> str | None:
    """把输入归一为 grinding / idle / wash；无法归一时返回 None。"""
    text = str(raw or "").strip().lower()
    return text if text in MILL_STATUSES else None


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def check_transition(mill: Mill, new_status: str) -> str | None:
    """校验单台机台的状态跳转。合法返回 None，否则返回中文错误（含 millCode）。"""
    old = mill.status
    if old == new_status:
        return None  # 状态未变化，不构成跳转
    if (old, new_status) not in ALLOWED_TRANSITIONS:
        return (
            f"研磨机 {mill.mill_code} 不允许从「{status_label(old)}」"
            f"切换为「{status_label(new_status)}」"
        )
    return None


def grinding_conflict(db, workshop_ids: set[int]) -> str | None:
    """检查给定车间是否出现多台 grinding；冲突时返回中文错误（含 millCode）。"""
    for workshop_id in workshop_ids:
        grinding = (
            db.query(Mill)
            .filter(Mill.workshop_id == workshop_id, Mill.status == "grinding")
            .order_by(Mill.id)
            .all()
        )
        if len(grinding) > 1:
            codes = "、".join(m.mill_code for m in grinding)
            return f"同一车间最多一台研磨中机台，以下机台冲突：{codes}"
    return None


def apply_status_changes(db, changes: list[tuple[Mill, str]]) -> str | None:
    """校验并应用一组状态变更（单条更新 = 长度为 1 的列表）。

    返回 None 表示全部合法且已写入当前会话（调用方负责 commit）；
    返回中文错误表示整批失败，调用方必须 rollback，库中状态保持原样。
    """
    for mill, new_status in changes:
        err = check_transition(mill, new_status)
        if err:
            return err

    workshop_ids: set[int] = set()
    for mill, new_status in changes:
        mill.status = new_status
        workshop_ids.add(mill.workshop_id)

    db.flush()
    return grinding_conflict(db, workshop_ids)
