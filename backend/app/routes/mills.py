from decimal import Decimal

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.mill_status import apply_status_changes, grinding_conflict, normalize_status
from app.models.mill import Mill
from app.models.workshop import Workshop
from app.serializers import mill_json
from app.utils import error

bp = Blueprint("mills", __name__, url_prefix="/api/mills")


def _validate(body: dict) -> str | None:
    workshop_id = int(body.get("workshopId") or 0)
    if workshop_id <= 0:
        return "请选择所属车间"

    mill_code = str(body.get("millCode", "")).strip()
    if not mill_code:
        return "研磨机编号不能为空"

    pigment_base = str(body.get("pigmentBase", "")).strip()
    if not pigment_base:
        return "色浆基料不能为空"

    if normalize_status(body.get("status") or "idle") is None:
        return "状态无效，应为 grinding / idle / wash"

    db = SessionLocal()
    try:
        if not db.get(Workshop, workshop_id):
            return "所属车间不存在"
    finally:
        db.close()

    return None


@bp.get("")
@jwt_required()
def list_mills():
    db = SessionLocal()
    try:
        rows = db.query(Mill).order_by(Mill.id.desc()).all()
        return jsonify([mill_json(r) for r in rows])
    finally:
        db.close()


@bp.post("")
@jwt_required()
def create_mill():
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return error(err, 400)

    db = SessionLocal()
    try:
        row = Mill(
            workshop_id=int(body["workshopId"]),
            mill_code=str(body["millCode"]).strip(),
            pigment_base=str(body["pigmentBase"]).strip(),
            bowl_liters=Decimal(str(body.get("bowlLiters", 0))),
            status=normalize_status(body.get("status")) or "idle",
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return error("该车间下研磨机编号已存在", 400)
        # 新建机台没有跳转来源，但仍须满足“同一车间最多一台研磨中”
        err = grinding_conflict(db, {row.workshop_id})
        if err:
            db.rollback()
            return error(err, 409)
        db.commit()
        db.refresh(row)
        return jsonify(mill_json(row)), 201
    finally:
        db.close()


@bp.put("/<int:item_id>")
@jwt_required()
def update_mill(item_id: int):
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return error(err, 400)

    db = SessionLocal()
    try:
        row = db.get(Mill, item_id)
        if not row:
            return error("研磨机不存在", 404)

        row.workshop_id = int(body["workshopId"])
        row.mill_code = str(body["millCode"]).strip()
        row.pigment_base = str(body["pigmentBase"]).strip()
        row.bowl_liters = Decimal(str(body.get("bowlLiters", 0)))

        # 与批量更新共用同一套状态机规则；失败则整体回滚
        new_status = normalize_status(body.get("status")) or "idle"
        try:
            err = apply_status_changes(db, [(row, new_status)])
        except IntegrityError:
            db.rollback()
            return error("该车间下研磨机编号已存在", 400)
        if err:
            db.rollback()
            return error(err, 409)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return error("该车间下研磨机编号已存在", 400)
        db.refresh(row)
        return jsonify(mill_json(row))
    finally:
        db.close()


@bp.post("/batch-status")
@jwt_required()
def batch_update_status():
    body = request.get_json(silent=True) or {}

    raw_ids = body.get("millIds")
    if not isinstance(raw_ids, list) or not raw_ids:
        return error("请选择要批量更新的研磨机", 400)
    try:
        mill_ids = [int(i) for i in raw_ids]
    except (TypeError, ValueError):
        return error("研磨机 id 无效", 400)

    status = normalize_status(body.get("status"))
    if status is None:
        return error("状态无效，应为 grinding / idle / wash", 400)

    db = SessionLocal()
    try:
        rows = db.query(Mill).filter(Mill.id.in_(mill_ids)).all()
        by_id = {m.id: m for m in rows}
        missing = [i for i in mill_ids if i not in by_id]
        if missing:
            return error(
                "部分研磨机不存在：id " + "、".join(str(i) for i in missing), 404
            )

        # 去重并保持请求顺序；任一失败则整批回滚，库中状态保持原样
        ordered = list(dict.fromkeys(mill_ids))
        err = apply_status_changes(db, [(by_id[i], status) for i in ordered])
        if err:
            db.rollback()
            return error(err, 409)

        db.commit()
        return jsonify({"updated": len(ordered)})
    finally:
        db.close()


@bp.delete("/<int:item_id>")
@jwt_required()
def delete_mill(item_id: int):
    db = SessionLocal()
    try:
        row = db.get(Mill, item_id)
        if not row:
            return error("研磨机不存在", 404)
        db.delete(row)
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
