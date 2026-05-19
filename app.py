"""
Cassandra 可视化管理系统 - Flask 后端
Python 3.9+ / Cassandra 4.1.x
依赖：Flask>=2.3, cassandra-driver>=3.28
"""
import json
import time
import os
import threading
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# ─── 全局状态（线程安全） ────────────────────────────────────────────────────
_state_lock = threading.Lock()
_cluster = None
_session = None
_current_connection_info = {}

CONNECTIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connections.json")

# ─── Flask 应用初始化 ─────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="frontend", static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})


# ══════════════════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════════════════

def get_session():
    if _session is None:
        raise RuntimeError("未连接到 Cassandra，请先建立连接")
    return _session


def get_cluster():
    if _cluster is None:
        raise RuntimeError("未连接到 Cassandra，请先建立连接")
    return _cluster


def load_connections():
    if not os.path.exists(CONNECTIONS_FILE):
        return []
    try:
        with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_connections(connections):
    with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(connections, f, ensure_ascii=False, indent=2)


def safe_value(val):
    """把 Cassandra 返回值转成可 JSON 序列化的形式"""
    if isinstance(val, (set, frozenset)):
        return sorted(val, key=str)
    if hasattr(val, "isoformat"):   # datetime
        return val.isoformat()
    return val


def rows_to_list(rows):
    """把 Cassandra 查询结果转成 dict 列表"""
    return [{col: safe_value(val) for col, val in row._asdict().items()} for row in rows]


def ok(data=None, msg="操作成功"):
    payload = {"success": True, "message": msg}
    if data is not None:
        payload["data"] = data
    return jsonify(payload)


def fail(msg, status=500):
    return jsonify({"success": False, "error": str(msg)}), status


def _close_current_cluster():
    global _cluster, _session, _current_connection_info
    with _state_lock:
        if _cluster is not None:
            try:
                _cluster.shutdown()
            except Exception:
                pass
            _cluster = None
            _session = None
            _current_connection_info = {}


# ══════════════════════════════════════════════════════════════════════════
#  静态页面
# ══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")


# ══════════════════════════════════════════════════════════════════════════
#  API：连接管理
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/connection/test", methods=["POST"])
def api_test_connection():
    from cassandra.cluster import Cluster
    from cassandra.auth import PlainTextAuthProvider

    data = request.get_json(force=True, silent=True) or {}
    host = data.get("host", "127.0.0.1")
    port = int(data.get("port", 9042))
    username = data.get("username", "")
    password = data.get("password", "")

    try:
        auth = PlainTextAuthProvider(username=username, password=password) if username else None
        cluster = Cluster(
            contact_points=[host],
            port=port,
            auth_provider=auth,
            connect_timeout=5,
        )
        session = cluster.connect()
        row = session.execute("SELECT release_version FROM system.local").one()
        version = row.release_version if row else "unknown"
        cluster.shutdown()
        return ok({"version": version}, msg=f"连接成功！Cassandra 版本: {version}")
    except Exception as e:
        return fail(f"连接失败: {e}", 400)


@app.route("/api/connection/connect", methods=["POST"])
def api_connect():
    global _cluster, _session, _current_connection_info

    data = request.get_json(force=True, silent=True) or {}
    host = data.get("host", "127.0.0.1")
    port = int(data.get("port", 9042))
    username = data.get("username", "")
    password = data.get("password", "")
    name = data.get("name", f"{host}:{port}")

    _close_current_cluster()

    try:
        from cassandra.cluster import Cluster
        from cassandra.auth import PlainTextAuthProvider

        auth = PlainTextAuthProvider(username=username, password=password) if username else None
        cluster = Cluster(
            contact_points=[host],
            port=port,
            auth_provider=auth,
            connect_timeout=8,
        )
        session = cluster.connect()
        with _state_lock:
            _cluster = cluster
            _session = session
            _current_connection_info = {
                "name": name,
                "host": host,
                "port": port,
                "username": username,
                "connected_at": datetime.now().isoformat(),
            }
        return ok(_current_connection_info, msg="连接成功")
    except Exception as e:
        with _state_lock:
            _cluster = None
            _session = None
        return fail(f"连接失败: {e}", 400)


@app.route("/api/connection/disconnect", methods=["POST"])
def api_disconnect():
    _close_current_cluster()
    return ok(msg="已断开连接")


@app.route("/api/connection/status", methods=["GET"])
def api_connection_status():
    if _session is None:
        return ok({"connected": False})
    return ok({"connected": True, "info": _current_connection_info})


@app.route("/api/connections/saved", methods=["GET"])
def api_get_saved_connections():
    return ok(load_connections())


@app.route("/api/connections/save", methods=["POST"])
def api_save_connection():
    data = request.get_json(force=True, silent=True) or {}
    connections = load_connections()
    name = data.get("name", "")
    # 去重
    connections = [c for c in connections if c.get("name") != name]
    connections.insert(0, {
        "name": name,
        "host": data.get("host", "127.0.0.1"),
        "port": int(data.get("port", 9042)),
        "username": data.get("username", ""),
        "saved_at": datetime.now().isoformat(),
    })
    save_connections(connections[:20])
    return ok(msg="连接已保存")


@app.route("/api/connections/delete/<name>", methods=["DELETE"])
def api_delete_saved_connection(name):
    connections = [c for c in load_connections() if c.get("name") != name]
    save_connections(connections)
    return ok(msg="已删除")


# ══════════════════════════════════════════════════════════════════════════
#  API：键空间管理
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/keyspaces", methods=["GET"])
def api_list_keyspaces():
    try:
        session = get_session()
        rows = session.execute(
            "SELECT keyspace_name, replication FROM system_schema.keyspaces"
        )
        result = []
        for row in rows:
            rep = dict(row.replication) if row.replication else {}
            strategy = rep.pop("class", "").split(".")[-1]
            factor = rep.get("replication_factor", rep.get("datacenter1", "?"))
            result.append({
                "name": row.keyspace_name,
                "strategy": strategy,
                "replication_factor": factor,
                "replication": rep,
            })
        return ok(result)
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces", methods=["POST"])
def api_create_keyspace():
    try:
        data = request.get_json(force=True, silent=True) or {}
        name = (data.get("name") or "").strip()
        strategy = data.get("strategy", "SimpleStrategy")
        factor = int(data.get("replication_factor", 1))
        durable = "true" if data.get("durable_writes", True) else "false"

        if not name:
            return fail("键空间名称不能为空", 400)

        if strategy == "SimpleStrategy":
            cql = (
                f"CREATE KEYSPACE IF NOT EXISTS {name} "
                f"WITH replication = {{'class': 'SimpleStrategy', "
                f"'replication_factor': {factor}}} "
                f"AND durable_writes = {durable}"
            )
        else:
            dc = data.get("datacenter", "datacenter1")
            cql = (
                f"CREATE KEYSPACE IF NOT EXISTS {name} "
                f"WITH replication = {{'class': 'NetworkTopologyStrategy', "
                f"'{dc}': {factor}}} "
                f"AND durable_writes = {durable}"
            )

        session = get_session()
        session.execute(cql)
        return ok({"cql": cql}, msg=f"键空间 '{name}' 创建成功")
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>", methods=["DELETE"])
def api_drop_keyspace(keyspace_name):
    try:
        session = get_session()
        cql = f"DROP KEYSPACE IF EXISTS {keyspace_name}"
        session.execute(cql)
        return ok({"cql": cql}, msg=f"键空间 '{keyspace_name}' 已删除")
    except Exception as e:
        return fail(e)


# ══════════════════════════════════════════════════════════════════════════
#  API：表管理
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/keyspaces/<keyspace_name>/tables", methods=["GET"])
def api_list_tables(keyspace_name):
    try:
        session = get_session()
        rows = session.execute(
            "SELECT table_name FROM system_schema.tables WHERE keyspace_name=%s",
            [keyspace_name],
        )
        tables = [row.table_name for row in rows]
        return ok(tables)
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>/tables/<table_name>/schema", methods=["GET"])
def api_get_table_schema(keyspace_name, table_name):
    try:
        session = get_session()
        col_rows = session.execute(
            "SELECT column_name, type, kind FROM system_schema.columns "
            "WHERE keyspace_name=%s AND table_name=%s",
            [keyspace_name, table_name],
        )
        columns = [
            {"name": r.column_name, "type": r.type, "kind": r.kind}
            for r in col_rows
        ]
        kind_order = {"partition_key": 0, "clustering": 1, "regular": 2, "static": 3}
        columns.sort(key=lambda c: kind_order.get(c["kind"], 9))
        return ok({"columns": columns})
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>/tables", methods=["POST"])
def api_create_table(keyspace_name):
    try:
        data = request.get_json(force=True, silent=True) or {}
        table_name = (data.get("table_name") or "").strip()
        columns = data.get("columns", [])

        if not table_name:
            return fail("表名不能为空", 400)
        if not columns:
            return fail("至少需要一个字段", 400)

        pk_cols = [c["name"] for c in columns if c.get("is_partition_key")]
        ck_cols = [c["name"] for c in columns if c.get("is_clustering_key")]

        if not pk_cols:
            return fail("至少需要一个分区键", 400)

        col_defs = ", ".join(f"{c['name']} {c['type']}" for c in columns)

        # 构建 PRIMARY KEY
        if ck_cols:
            inner = f"({', '.join(pk_cols)})" if len(pk_cols) > 1 else pk_cols[0]
            pk_def = f"{inner}, {', '.join(ck_cols)}"
        else:
            pk_def = f"({', '.join(pk_cols)})" if len(pk_cols) > 1 else pk_cols[0]

        cql = (
            f"CREATE TABLE IF NOT EXISTS {keyspace_name}.{table_name} "
            f"({col_defs}, PRIMARY KEY ({pk_def}))"
        )

        session = get_session()
        session.execute(cql)
        return ok({"cql": cql}, msg=f"表 '{table_name}' 创建成功")
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>/tables/<table_name>", methods=["DELETE"])
def api_drop_table(keyspace_name, table_name):
    try:
        session = get_session()
        cql = f"DROP TABLE IF EXISTS {keyspace_name}.{table_name}"
        session.execute(cql)
        return ok({"cql": cql}, msg=f"表 '{table_name}' 已删除")
    except Exception as e:
        return fail(e)


# ══════════════════════════════════════════════════════════════════════════
#  API：数据增删查改
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/keyspaces/<keyspace_name>/tables/<table_name>/data", methods=["GET"])
def api_query_data(keyspace_name, table_name):
    try:
        session = get_session()
        limit = min(int(request.args.get("limit", 100)), 1000)
        where_clause = (request.args.get("where") or "").strip()

        cql = f"SELECT * FROM {keyspace_name}.{table_name}"
        if where_clause:
            cql += f" WHERE {where_clause}"
        cql += f" LIMIT {limit}"

        t0 = time.time()
        rows = session.execute(cql)
        elapsed = round((time.time() - t0) * 1000, 2)

        data = rows_to_list(rows)
        return ok({
            "rows": data,
            "count": len(data),
            "elapsed_ms": elapsed,
            "cql": cql,
        })
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>/tables/<table_name>/data", methods=["POST"])
def api_insert_data(keyspace_name, table_name):
    try:
        data = request.get_json(force=True, silent=True) or {}
        row = data.get("row", {})
        if not row:
            return fail("数据不能为空", 400)

        cols = ", ".join(row.keys())
        placeholders = ", ".join(["%s"] * len(row))
        values = list(row.values())

        cql = f"INSERT INTO {keyspace_name}.{table_name} ({cols}) VALUES ({placeholders})"
        session = get_session()
        session.execute(cql, values)
        return ok({"cql": cql}, msg="数据插入成功")
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>/tables/<table_name>/data", methods=["PUT"])
def api_update_data(keyspace_name, table_name):
    try:
        data = request.get_json(force=True, silent=True) or {}
        updates = data.get("updates", {})
        where = data.get("where", {})
        if not updates:
            return fail("更新字段不能为空", 400)
        if not where:
            return fail("WHERE 条件不能为空（需要主键）", 400)

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        where_clause = " AND ".join(f"{k} = %s" for k in where)
        values = list(updates.values()) + list(where.values())

        cql = f"UPDATE {keyspace_name}.{table_name} SET {set_clause} WHERE {where_clause}"
        session = get_session()
        session.execute(cql, values)
        return ok({"cql": cql}, msg="数据更新成功")
    except Exception as e:
        return fail(e)


@app.route("/api/keyspaces/<keyspace_name>/tables/<table_name>/data", methods=["DELETE"])
def api_delete_data(keyspace_name, table_name):
    try:
        data = request.get_json(force=True, silent=True) or {}
        where = data.get("where", {})
        if not where:
            return fail("WHERE 条件不能为空（需要主键）", 400)

        where_clause = " AND ".join(f"{k} = %s" for k in where)
        values = list(where.values())

        cql = f"DELETE FROM {keyspace_name}.{table_name} WHERE {where_clause}"
        session = get_session()
        session.execute(cql, values)
        return ok({"cql": cql}, msg="数据删除成功")
    except Exception as e:
        return fail(e)


# ══════════════════════════════════════════════════════════════════════════
#  API：CQL 编辑器
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/cql/execute", methods=["POST"])
def api_execute_cql():
    try:
        data = request.get_json(force=True, silent=True) or {}
        cql = (data.get("cql") or "").strip()
        if not cql:
            return fail("CQL 不能为空", 400)

        session = get_session()
        t0 = time.time()
        result = session.execute(cql)
        elapsed = round((time.time() - t0) * 1000, 2)

        try:
            rows = rows_to_list(result)
            columns = list(rows[0].keys()) if rows else []
        except Exception:
            rows = []
            columns = []

        return ok({
            "rows": rows,
            "columns": columns,
            "count": len(rows),
            "elapsed_ms": elapsed,
            "cql": cql,
        })
    except Exception as e:
        return fail(e)


@app.route("/api/cql/templates", methods=["GET"])
def api_get_cql_templates():
    templates = [
        {"name": "查询所有数据", "cql": "SELECT * FROM keyspace_name.table_name LIMIT 100;"},
        {"name": "创建键空间", "cql": "CREATE KEYSPACE IF NOT EXISTS my_keyspace\nWITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};"},
        {"name": "创建表", "cql": "CREATE TABLE IF NOT EXISTS my_keyspace.my_table (\n  id UUID PRIMARY KEY,\n  name TEXT,\n  created_at TIMESTAMP\n);"},
        {"name": "插入数据", "cql": "INSERT INTO my_keyspace.my_table (id, name) VALUES (uuid(), 'example');"},
        {"name": "更新数据", "cql": "UPDATE my_keyspace.my_table SET name = 'new_value' WHERE id = <uuid>;"},
        {"name": "删除数据", "cql": "DELETE FROM my_keyspace.my_table WHERE id = <uuid>;"},
        {"name": "查看集群信息", "cql": "SELECT * FROM system.local;"},
        {"name": "查看所有键空间", "cql": "SELECT * FROM system_schema.keyspaces;"},
        {"name": "查看表结构", "cql": "SELECT * FROM system_schema.columns\nWHERE keyspace_name='my_keyspace' AND table_name='my_table';"},
    ]
    return ok(templates)


# ══════════════════════════════════════════════════════════════════════════
#  健康检查
# ══════════════════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "cassandra-manager", "py": "3.9+"})


# ══════════════════════════════════════════════════════════════════════════
#  启动入口
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  Cassandra 可视化管理系统 - 后端服务 (Python 3.9+ / Cassandra 4.x)")
    print("  访问地址：http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
