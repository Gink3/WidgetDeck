import re
from flask import current_app, Blueprint, abort, jsonify, redirect, render_template, request, url_for
from dashboard.auth import login_required
from .common_routes import named_values
from . import kanban_models as models

campaign_tools = Blueprint("campaign_tools", __name__)


@campaign_tools.route("/tools/kanban", methods=["GET", "POST"])
def kanban():
    if request.method == "POST":
        name = str(request.form.get("name") or "").strip()[:80] or "Untitled board"
        columns = named_values("column_name", ("To do", "In Progress", "Done"))
        return redirect(url_for("campaign_tools.kanban", board=models.create_kanban(name, columns)))
    if not request.args and current_app.config.get("LAUNCHER_ENABLED"):
        from dashboard.launcher import recent
        previous=recent(1,'kanban')
        if previous:return redirect(previous[0]['url'])
    boards = models.kanban_boards()
    board_id = request.args.get("board", type=int)
    selected = models.kanban_board(board_id) if board_id else (boards[0] if boards else None)
    columns = models.kanban_columns(selected["id"]) if selected else []
    raw_items = models.attach_efforts([dict(r) for r in models.kanban_items(selected["id"])]) if selected else []
    items = {column["id"]: [item for item in raw_items if item["column_id"] == column["id"]] for column in columns}
    return render_template("campaign_tools/kanban.html", boards=boards, selected=selected, columns=columns, items=items, efforts=models.kanban_efforts())



@campaign_tools.post("/tools/kanban/<int:board_id>/items")
def kanban_add_item(board_id):
    if not models.kanban_board(board_id):
        abort(404)
    column_id = request.form.get("column_id", type=int)
    title = str(request.form.get("title") or "").strip()[:160]
    if title and any(column["id"] == column_id for column in models.kanban_columns(board_id)):
        models.add_kanban_item(board_id, column_id, title, str(request.form.get("notes") or "").strip()[:5000])
    return redirect(url_for("campaign_tools.kanban", board=board_id))



@campaign_tools.post("/api/tools/kanban/boards/<int:board_id>/items")
@login_required
def kanban_create_item(board_id):
    if not models.kanban_board(board_id):
        return jsonify(error="Board not found."), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="An item is required."), 400
    title, notes = payload.get("title"), payload.get("notes", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        return jsonify(error="Use an item title between 1 and 160 characters."), 400
    if not isinstance(notes, str) or len(notes) > 5000:
        return jsonify(error="Notes must be 5,000 characters or fewer."), 400
    if type(payload.get("column_id")) is not int:
        return jsonify(error="A destination column is required."), 400
    try:
        item_id = models.add_kanban_item(board_id, payload["column_id"], title.strip(), notes, payload.get("effort_ids"))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    if item_id is None:
        return jsonify(error="Board not found."), 404
    response = jsonify(item=models.kanban_item_detail(item_id))
    response.status_code = 201
    response.headers["Location"] = url_for("campaign_tools.kanban_get_item", item_id=item_id)
    response.headers["Cache-Control"] = "private, no-store"
    return response



@campaign_tools.post("/api/tools/kanban/boards/<int:board_id>/columns/reorder")
@login_required
def kanban_reorder_columns(board_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or any(
            not isinstance(payload.get(field), list) or any(type(value) is not int for value in payload[field])
            for field in ("column_ids", "expected_order")):
        return jsonify(error="Supply ordered column IDs and their previous order."), 400
    try:
        columns = models.reorder_kanban_columns(board_id, payload["column_ids"], payload["expected_order"])
    except models.ItemConflict as error:
        return jsonify(error=str(error)), 409
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(columns=columns) if columns is not None else (jsonify(error="Board not found."), 404)



@campaign_tools.get("/api/tools/kanban/items/<int:item_id>")
@login_required
def kanban_get_item(item_id):
    item = models.kanban_item_detail(item_id)
    return jsonify(item=item) if item else (jsonify(error="Item not found."), 404)



@campaign_tools.get("/api/tools/kanban/boards")
@login_required
def kanban_list_boards():
    name = request.args.get("name")
    boards = [{key: row[key] for key in ("id", "name", "created_at")}
              for row in models.kanban_boards()
              if name is None or row["name"].casefold() == name.strip().casefold()]
    response = jsonify(boards=boards, api_version=1)
    response.headers["Cache-Control"] = "private, no-store"
    return response



@campaign_tools.get("/api/tools/kanban/boards/<int:board_id>")
@login_required
def kanban_read_board(board_id):
    board = models.kanban_board_snapshot(board_id)
    response = jsonify(board=board, api_version=1) if board else jsonify(error="Board not found.")
    response.status_code = 200 if board else 404
    response.headers["Cache-Control"] = "private, no-store"
    return response



@campaign_tools.patch("/api/tools/kanban/items/<int:item_id>")
@login_required
def kanban_update_item(item_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="An item update is required."), 400
    title, notes = payload.get("title"), payload.get("notes")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 160:
        return jsonify(error="Use an item title between 1 and 160 characters."), 400
    if not isinstance(notes, str) or len(notes) > 5000:
        return jsonify(error="Notes must be 5,000 characters or fewer."), 400
    if type(payload.get("column_id")) is not int or type(payload.get("revision")) is not int:
        return jsonify(error="A column and item revision are required."), 400
    try:
        item = models.update_kanban_item(item_id, title.strip(), notes, payload["column_id"], payload["revision"])
    except models.ItemConflict as error:
        return jsonify(error=str(error)), 409
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(item=item) if item else (jsonify(error="Item not found."), 404)



@campaign_tools.post("/api/tools/kanban/items/<int:item_id>/move")
@login_required
def kanban_move_item(item_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or type(payload.get("column_id")) is not int:
        return jsonify(error="A destination column is required."), 400
    if payload.get("before_id") is not None and type(payload["before_id"]) is not int:
        return jsonify(error="A valid destination item is required."), 400
    if payload.get("revision") is not None and type(payload["revision"]) is not int:
        return jsonify(error="A valid item revision is required."), 400
    try:
        item = models.move_kanban_item(item_id, payload["column_id"], payload.get("before_id"), payload.get("revision"))
    except models.ItemConflict as error:
        return jsonify(error=str(error)), 409
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(ok=True, item=item) if item else (jsonify(error="Item not found."), 404)



@campaign_tools.post("/api/tools/kanban/items/<int:item_id>/transfer")
@login_required
def kanban_transfer_item(item_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or any(type(payload.get(field)) is not int
                                            for field in ("board_id", "column_id", "revision")):
        return jsonify(error="A destination board, column and item revision are required."), 400
    if payload.get("before_id") is not None and type(payload["before_id"]) is not int:
        return jsonify(error="A valid destination item is required."), 400
    try:
        item = models.transfer_kanban_item(item_id, payload["board_id"], payload["column_id"],
                                          payload["revision"], payload.get("before_id"))
    except models.ItemConflict as error:
        return jsonify(error=str(error)), 409
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(item=item) if item else (jsonify(error="Item or board not found."), 404)



@campaign_tools.delete("/api/tools/kanban/items/<int:item_id>")
@login_required
def kanban_delete_item(item_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or type(payload.get("revision")) is not int:
        return jsonify(error="An item revision is required."), 400
    try:
        deleted = models.delete_kanban_item(item_id, payload["revision"])
    except models.ItemConflict as error:
        return jsonify(error=str(error)), 409
    return ("", 204) if deleted else (jsonify(error="Item not found."), 404)



@campaign_tools.post("/api/tools/kanban/items/<int:item_id>/cancel")
@login_required
def kanban_cancel_item(item_id):
    payload = request.get_json(silent=True)
    if (not isinstance(payload, dict) or type(payload.get("revision")) is not int
            or type(payload.get("cancelled", True)) is not bool):
        return jsonify(error="An item revision and boolean cancelled value are required."), 400
    try:
        item = models.cancel_kanban_item(item_id, payload.get("cancelled", True), payload["revision"])
    except models.ItemConflict as error:
        return jsonify(error=str(error)), 409
    return jsonify(item=item) if item else (jsonify(error="Item not found."), 404)



@campaign_tools.route('/api/tools/kanban/boards/<int:board_id>/columns',methods=['POST'])
@campaign_tools.route('/api/tools/kanban/boards/<int:board_id>/columns/<int:column_id>',methods=['DELETE'])
@login_required
def kanban_manage_column(board_id,column_id=None):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict) or not isinstance(payload.get('expected_order'),list) or any(type(i) is not int for i in payload['expected_order']):
        return jsonify(error='Supply the current ordered column IDs.'),400
    if payload.get('destination_id') is not None and type(payload['destination_id']) is not int:
        return jsonify(error='Destination must be a column ID.'),400
    try:
        columns=models.manage_kanban_column(board_id,payload['expected_order'],payload.get('name'),column_id,payload.get('destination_id'))
    except models.ItemConflict as error:return jsonify(error=str(error)),409
    except ValueError as error:return jsonify(error=str(error)),400
    return (jsonify(columns=columns),201 if column_id is None else 200) if columns is not None else (jsonify(error='Board not found.'),404)



@campaign_tools.route('/api/tools/kanban/items/<int:item_id>/comments',methods=['GET','POST'])
@campaign_tools.route('/api/tools/kanban/items/<int:item_id>/comments/<int:comment_id>',methods=['PATCH','DELETE'])
@login_required
def kanban_comments(item_id,comment_id=None):
    if request.method=='GET':
        item=models.kanban_item_detail(item_id)
        return jsonify(comments=item['comments']) if item else (jsonify(error='Item not found.'),404)
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Supply a JSON object.'),400
    try:
        item=models.change_kanban_comment(item_id,payload.get('body'),comment_id,payload.get('revision'),request.method=='DELETE')
    except models.ItemConflict as error:return jsonify(error=str(error)),409
    except ValueError as error:return jsonify(error=str(error)),400
    return (jsonify(item=item),201 if comment_id is None else 200) if item else (jsonify(error='Item or comment not found.'),404)



@campaign_tools.put('/api/tools/kanban/items/<int:item_id>/links')
@login_required
def kanban_update_links(item_id):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Supply a JSON object.'),400
    try:item=models.update_kanban_links(item_id,payload.get('links'),payload.get('revision'))
    except models.ItemConflict as error:return jsonify(error=str(error)),409
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(item=item) if item else (jsonify(error='Item not found.'),404)


@campaign_tools.route('/api/tools/kanban/efforts',methods=['GET','POST'])
@campaign_tools.route('/api/tools/kanban/efforts/<int:effort_id>',methods=['PATCH','DELETE'])
@login_required
def kanban_manage_effort(effort_id=None):
    if request.method=='GET':return jsonify(efforts=models.kanban_efforts())
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Supply a JSON object.'),400
    try:
        result=models.change_kanban_effort(payload.get('name'),effort_id,payload.get('revision'),request.method=='DELETE')
    except models.ItemConflict as error:return jsonify(error=str(error)),409
    except ValueError as error:return jsonify(error=str(error)),400
    if result is None:return jsonify(error='Effort not found.'),404
    if request.method=='DELETE':return '',204
    return jsonify(effort=result),201 if request.method=='POST' else 200


@campaign_tools.put('/api/tools/kanban/items/<int:item_id>/efforts')
@login_required
def kanban_item_efforts(item_id):
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Supply a JSON object.'),400
    try:item=models.update_kanban_efforts(item_id,payload.get('effort_ids'),payload.get('revision'))
    except models.ItemConflict as error:return jsonify(error=str(error)),409
    except ValueError as error:return jsonify(error=str(error)),400
    return jsonify(item=item) if item else (jsonify(error='Item not found.'),404)


@campaign_tools.get('/api/tools/kanban/efforts/<int:effort_id>/items')
@login_required
def kanban_effort_items(effort_id):
    items=models.kanban_effort_items(effort_id)
    return jsonify(items=items) if items is not None else (jsonify(error='Effort not found.'),404)
