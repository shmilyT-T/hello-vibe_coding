# Cassandra 可视化管理系统

> Python 3.9+ / Apache Cassandra 4.1.8 / Flask / 纯前端单页

## 功能

- 键空间管理（创建 / 查看 / 删除）
- 表管理（创建 / 查看结构 / 删除）
- 数据 CRUD（插入 / 编辑 / 删除 / 查询，支持 WHERE 过滤）
- CQL 编辑器（快捷模板 + 直接执行任意 CQL）
- 连接配置保存（多连接历史记录）

## 环境要求

- Python 3.9+
- Apache Cassandra 4.1.8（本地或远程均可）
- Cassandra 服务需正常启动并监听 `9042` 端口

## 安装依赖

```bash
pip install -r requirements.txt
```

Dependencies:
- `Flask>=2.3.0`
- `Flask-CORS>=4.0.0`
- `cassandra-driver>=3.28.0`

## 启动

```bash
python app.py
```

访问：**http://127.0.0.1:5000**

## 使用

1. 打开页面后，在「新建连接」填写主机 IP / 端口（默认 `127.0.0.1:9042`）
2. 点击「测试连接」验证，通过后点击「连接并进入」
3. 左侧树形导航选择键空间 → 表
4. 右侧可管理键空间、表结构、表数据，或直接用 CQL 编辑器执行语句

## 目录结构

```
cassandra_manager/
├── app.py              # Flask 后端
├── requirements.txt    # Python 依赖
└── frontend/
    └── index.html     # 前端单页（HTML/CSS/JS）
```
