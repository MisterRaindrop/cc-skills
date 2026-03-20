# PXF Development Automation Plugin

Docker 环境管理、编译、测试、结果解析一站式自动化，基于 `pxf-cbdb-dev` 容器。

## Commands

| Command | Description |
|---------|------------|
| `/pxf:docker-up` | 启动 Docker 开发环境（Cloudberry + Hadoop + Hive + HBase + MinIO） |
| `/pxf:docker-down` | 停止/清理 Docker 环境 |
| `/pxf:build` | 编译 PXF（全量/server/单模块/快速部署） |
| `/pxf:test` | 运行自动化测试（按 group 或指定用例） |
| `/pxf:parse-results` | 解析 surefire XML 测试报告 |

## Prerequisites

- Docker Desktop（已启动）
- [cloudberry-pxf](https://github.com/apache/cloudberry-pxf) 源码仓库（脚本会自动定位）

## Installation

三种安装方式，任选其一。

### Option A: Quick Test（临时加载，不持久）

```bash
# 直接指定插件目录启动 Claude Code
claude --plugin-dir /path/to/cc-skills/plugins/pxf
```

关闭 Claude Code 后插件即消失，无需清理。

### Option B: From Local Marketplace（持久安装）

```bash
# 1. 启动 Claude Code
claude

# 2. 添加 marketplace（只需一次）
/plugin marketplace add /path/to/cc-skills

# 3. 安装 pxf 插件
/plugin install pxf@cc-skills-marketplace
```

安装范围可选：
- `--scope user`（默认）— 所有项目可用
- `--scope project` — 仅当前 git 仓库

### Option C: From GitHub（无需 clone）

```bash
claude

/plugin marketplace add MisterRaindrop/cc-skills
/plugin install pxf@cc-skills-marketplace
```

### Update（已安装过，更新到新版本）

```bash
# 1. 刷新 marketplace 索引
/plugin marketplace update cc-skills-marketplace

# 2. 更新插件
/plugin update pxf@cc-skills-marketplace

# 3. 重载生效
/reload-plugins
```

如果 update 不生效，可以先卸后装：

```bash
/plugin uninstall pxf
/plugin install pxf@cc-skills-marketplace
/reload-plugins
```

### Verify

安装后输入 `/` 应能看到：

```
/pxf:docker-up
/pxf:docker-down
/pxf:build
/pxf:test
/pxf:parse-results
```

## Usage

### 启动开发环境

```
/pxf:docker-up
```

首次启动约 10-20 分钟（编译 Cloudberry、配置 Hadoop 栈）。后续重启用 `--skip-init` 跳过初始化。

### 编译

```
/pxf:build                  # 全量编译（默认）
/pxf:build server            # 仅 server
/pxf:build pxf-hdfs          # 单模块
/pxf:build quick             # 跳过编译，仅部署
/pxf:build test              # 运行单元测试
```

### 运行测试

```
/pxf:test                    # smoke 测试（默认）
/pxf:test hdfs               # HDFS 测试组
/pxf:test smoke TEST=HdfsSmokeTest          # 指定测试类
/pxf:test hdfs TEST=HdfsReadableTextTest#testTextFormatSimple  # 指定方法
```

### 查看测试结果

```
/pxf:parse-results           # 自动查找报告目录
/pxf:parse-results --json    # JSON 格式输出
/pxf:parse-results --failures-only  # 只看失败用例
```

### 停止环境

```
/pxf:docker-down             # 停止容器（保留状态，快速重启）
/pxf:docker-down --clean     # 彻底删除容器和卷
/pxf:docker-down --status    # 查看当前容器状态
```

## Architecture

```
cc-skills/plugins/pxf/                  Docker (pxf-cbdb-dev)
  scripts/                              ─────────────────────
    docker-up.sh ──docker compose──>    entrypoint.sh
    build.sh ──docker exec──>             ├── build Cloudberry / PXF
    test.sh ──docker exec──>              ├── start Hadoop/Hive/HBase/MinIO
    parse-results.sh                      └── run_tests.sh
    detect-pxf-repo.sh
                                        Volume mount:
  commands/                              cloudberry-pxf/ <──>
    docker-up.md   (skill definition)      /home/gpadmin/workspace/cloudberry-pxf/
    build.md
    test.md
    ...
```

脚本打包在插件的 `scripts/` 目录中，通过 `detect-pxf-repo.sh` 自动定位 cloudberry-pxf 仓库。

脚本也可以直接在终端运行（需要 cd 到 cloudberry-pxf 目录下）：

```bash
/path/to/cc-skills/plugins/pxf/scripts/docker-up.sh
/path/to/cc-skills/plugins/pxf/scripts/build.sh pxf-hdfs
/path/to/cc-skills/plugins/pxf/scripts/test.sh smoke
/path/to/cc-skills/plugins/pxf/scripts/parse-results.sh --failures-only
```

## Uninstall

```
/plugin uninstall pxf
```
