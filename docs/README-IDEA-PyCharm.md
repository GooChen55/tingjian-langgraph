# 用 IntelliJ IDEA 与 PyCharm 启动听见

这份指南针对当前目录 `D:\code\python\AI_tingshu_langgraph`，使用 **Windows 运行应用、192.168.6.100 运行中间件** 的 VM 模式。原版 `AI_tingshu` 是另一个项目，不要混用原版的端口、配置或运行目录。

本机已经保存 Run/Debug 配置，可按下面的“已保存配置”直接运行。后面的手动配置步骤用于理解参数或换电脑时参考。

## 已保存配置：本机直接 Run / Debug

两个 IDE 请打开不同目录，避免相互覆盖项目解释器设置：

| IDE | 打开的目录 | 运行下拉框 |
| --- | --- | --- |
| IntelliJ IDEA | `D:\code\python\AI_tingshu_langgraph\backend\java\tingshu-parent` | `Tingjian-Java-All`，包含 User-19201、Content-19202、Order-19204 三个 Application 配置 |
| PyCharm | `D:\code\python\AI_tingshu_langgraph` | `Tingjian-Python-All`，包含 Knowledge-29184、Operations-29185、Worker、Assistant-29183 四个 Python 配置 |

首次加载时，IDEA 等待 Maven 导入、索引完成；若提示是否加载 Maven 工程，选择加载。PyCharm 如果在配置生成时已经打开，请完整退出后重开一次，让它读取新增的项目虚拟环境注册。JDK 已指定本机 Java 17，Python 已指定本项目 `.venv`，各配置也已保存工作目录、环境变量和启动参数。

之后每天确认虚拟机可用，在 IDEA 选择 `Tingjian-Java-All` 点击 **Run**，然后在 PyCharm 选择 `Tingjian-Python-All` 点击 **Run**；需要断点时选择对应单项配置点击 **Debug**，也可 Debug 整个组合。组合内进程并行启动，等所有服务就绪再访问 `http://127.0.0.1:29183/listen/`。

Java 配置会先 Make 再运行源码入口，修改 Java 后重新运行即可；内容服务使用 `LocalContentApplication`。Python 配置直接运行模块，没有 uvicorn `--reload`，便于调试。前端没有修改时使用已有构建结果；修改 Vue 后仍须执行本文的 `build:h5`。

停止时在两个 IDE 的运行面板分别停止组合内所有进程，尤其不要遗漏 Worker。IDE 启动的进程由 IDE 管理，切勿再同时运行根目录 `Start.ps1` 启动第二套。

这些配置含本机私有环境变量，只保存在 Git 忽略的 `.idea/runConfigurations` 中。原文件备份在 `.runtime/ide/backups`；不要手动将这些目录加入 Git。配置或凭据更新后，在根目录执行以下命令重新生成，然后重新加载 IDE：

```powershell
.\scripts\dev\PrepareIde.ps1
```

虚拟机重启后若项目 Redis ACL 丢失，先在项目根目录执行 `.\.venv\Scripts\python.exe scripts/setup/ReconcileVmAccess.py`，再运行 IDE 配置；它只恢复本项目账号。

## 1. 先认识要启动的内容

| 部分 | 用哪个工具运行 | 端口 / 作用 |
| --- | --- | --- |
| Java 用户服务 | IDEA | 19201，身份、权限、会员、进度 |
| Java 内容服务 | IDEA | 19202，专辑、声音、可播放内容 |
| Java 订单服务 | IDEA | 19204，订单、售后、模拟支付退款 |
| Python 知识服务 | PyCharm | 29184，平台资料检索 |
| Python 运营服务 | PyCharm | 29185，只读运营问数 |
| Python 消息工作进程 | PyCharm | 无 HTTP 端口，处理搜索与公共/私人资料索引 |
| Python 助手入口 | PyCharm | 29183，助手、管理台和 H5 静态页面 |
| Vue / UniApp 前端 | 任一 IDE 的 Terminal | npm 构建，页面由 29183 提供 |

因此完整启动需要 **3 个 Java 进程、3 个 Python Web 进程、1 个 Python 工作进程**。不要把仓库里所有历史微服务都启动。

## 2. 环境与项目准备

当前机器可用的位置：

| 配置 | 当前值 |
| --- | --- |
| 项目根目录 | `D:\code\python\AI_tingshu_langgraph` |
| JDK | `D:\develop\JAVA\jdk\ms-17.0.18`，Java 17 |
| Python 解释器 | `D:\code\python\AI_tingshu_langgraph\.venv\Scripts\python.exe` |
| Node | 当前机器 `D:\develop\nodejs\node.exe`，也可使用 PATH 中的 node |
| Maven | Terminal 中 `mvn -version` 应能运行 |

换电脑时替换这些路径。Python 应使用项目的 `.venv`，不要选系统解释器或旁边项目的虚拟环境。

在 IDEA 或 PyCharm 下方打开 **Terminal / 终端**，确认当前目录是项目根目录：

以下命令使用 **PowerShell**，请在终端配置中选择 PowerShell，而不是 cmd。所有相对路径命令都从项目根目录执行；IDEA 若默认进入 Java 子目录，先执行下面的 `cd`。

```powershell
cd D:\code\python\AI_tingshu_langgraph
java -version
mvn -version
node -v
.\.venv\Scripts\python.exe --version
```

已有 `.venv` 且依赖安装完成时，不需要重复安装。首次建立环境才执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/requirements.lock.txt
npm.cmd --prefix frontend/uniapp ci
```

VM 必须开机，中间件必须可达。当前目录已经初始化；首次克隆或更换虚拟机时，先按 [部署与验收](部署与验收.md) 初始化项目专属资源。IDE 不会自动创建数据库、迁移表或安装中间件。

## 3. 最容易的方法：在 IDE 终端中启动

如果只是运行和浏览源码，直接在任一 IDE 的 Terminal 执行：

```powershell
.\Start.ps1 -Infrastructure vm -SkipBuild -UseLlm -WithKnowledge -WithOperations
```

首次构建、Java 或前端源码有变化时：

```powershell
.\Stop.ps1
.\Start.ps1 -Infrastructure vm -UseLlm -WithKnowledge -WithOperations
```

脚本默认 JDK 为上表路径，不同时添加 `-JavaHome '你的JDK17目录'`。Windows 运行中的 JAR 会被锁定，所以重新打包前要先停止。

打开：

- 听书端：<http://127.0.0.1:29183/listen/>
- 管理台：<http://127.0.0.1:29183/admin>
- 个人空间：<http://127.0.0.1:29183/listen/#/pages/knowledge/knowledge>

这种方式由脚本启动后台进程；**点击 IDE 的 Debug 不会自动连接到这些后台进程**。需要源码调试时，继续下面的步骤。

## 4. 准备供 IDE 使用的环境文件

在项目根目录运行：

```powershell
.\scripts\dev\PrepareIde.ps1
```

它读取已有的本项目私有配置，生成：

```text
.runtime/ide/
├── application.env       Java/Python 共用的环境变量
├── java.vmoptions        Java 虚拟机参数
├── java-user.args        用户服务的程序参数
├── java-album.args       内容服务的程序参数
└── java-order.args       订单服务的程序参数
```

生成过程不启动或停止服务，也不修改虚拟机服务配置。`application.env` 含数据库、Redis、RabbitMQ 和内部调用凭据；整个 `.runtime` 已被 Git 忽略，不要把环境文件内容复制进 README、共享运行配置或截图。

脚本同时调用 `ConfigureIde.py`，保存根目录的 PyCharm 配置、Java 子目录的 IDEA 配置，以及本机 PyCharm 的项目虚拟环境注册；保留其他解释器，修改前备份原文件。生成的运行配置已直接写入所需环境变量，无须再次手动选择环境文件。

**重要：IDE Terminal 中设置的 `$env:...` 不会自动进入已经打开的 IDE 的 Run/Debug 配置。** 后面的手动配置教程采用显式加载 `application.env` 的方式，与已保存配置中的环境变量等效。生成文件后不用手工录入项目密码。

项目移动目录、专属凭据更新后重新运行生成脚本。模型 API Key 仍由管理台保存并使用 Windows DPAPI 加密；环境文件只指定模型设置文件路径，不导出模型明文密钥。

VM 重启后、正式切换 IDE 启动前，可在根目录做一次预检：

```powershell
.\.venv\Scripts\python.exe scripts/setup/ReconcileVmAccess.py
.\.venv\Scripts\python.exe scripts/verify/VerifyVmInfrastructure.py
```

前者只核对并按需恢复本项目 Redis ACL；后者验证专属资源。如果共享中间件没有启动，先排查虚拟机，不要为了启动本项目接管其他项目的容器。

## 5. 在 IDEA 配置 Java 服务

### 5.1 导入 Maven 工程

1. IDEA 选择 **File → Open**，打开 `D:\code\python\AI_tingshu_langgraph\backend\java\tingshu-parent\pom.xml`，作为 Maven 工程导入。
2. 将 Project SDK 和 Maven 使用的 JDK 设为 **17**。
3. 等 Maven 依赖同步完成，必要时在 Maven 面板重新加载项目；构建时使用 `local-listening` Maven profile，与项目启动脚本保持一致。
4. 若依赖模块提示找不到，可在根目录 Terminal 执行下面的构建，将所需模块安装到本机 Maven 仓库：

```powershell
$env:JAVA_HOME='D:\develop\JAVA\jdk\ms-17.0.18'
$env:PATH="$env:JAVA_HOME\bin;$env:PATH"
$env:MAVEN_OPTS='-Xmx256m -XX:ActiveProcessorCount=2'
mvn -B -ntp -f backend/java/tingshu-parent/pom.xml -pl service/service-user,service/service-album,service/service-order -am -Plocal-listening -DskipTests install
```

Maven 的 `local-listening` 是构建 profile；运行时的 Spring profile 是 **vm**，两个名字不需要相同。

### 5.2 创建三个 Application 配置

打开 **Run → Edit Configurations → + → Application**。使用普通 Java Application 模板即可，不要求必须有 Spring Boot 专用配置模板。

| 配置名称 | Main class | Use classpath of module | Program arguments 来源 |
| --- | --- | --- | --- |
| 听见-用户 | `com.atguigu.tingshu.ServiceUserApplication` | `service-user` | `.runtime/ide/java-user.args` |
| 听见-内容 | `com.atguigu.tingshu.listeningcontent.LocalContentApplication` | `service-album` | `.runtime/ide/java-album.args` |
| 听见-订单 | `com.atguigu.tingshu.ServiceOrderApplication` | `service-order` | `.runtime/ide/java-order.args` |

三个配置共同填写：

| 字段 | 如何填写 |
| --- | --- |
| JRE / SDK | JDK 17 |
| Working directory | `D:\code\python\AI_tingshu_langgraph\backend\java\tingshu-parent` |
| Environment variables / .env files | 加载 `D:\code\python\AI_tingshu_langgraph\.runtime\ide\application.env` |
| VM options | 打开 `java.vmoptions`，把文件中的一整行内容复制到这里 |
| Program arguments | 打开本服务对应的 `.args` 文件，把一整行内容复制到这里 |

找不到某个字段时，在配置窗口的 **Modify options / 修改选项** 中展开。较旧版本没有环境文件入口时，可在环境变量的 Name/Value 表格中按行填写生成文件的值；`PYTHONPATH` 内的分号属于一个变量的值，不能拆成多个变量。

`.env` 值外面的双引号属于文件格式；手动填写 Name/Value 表格时不填写这层引号。

**不要把 `.args` 文件路径当成 Program arguments 的内容。** 这里复制的是文件里的参数文本。VM options 和 Program arguments 也不要互换。

内容模块同时存在原课程的 `ServiceAlbumApplication`。当前融合版要选表中的 **LocalContentApplication**；它的名字不代表只能使用 Spring local profile。生成参数已经指定 vm、192.168.6.100、本项目 Nacos namespace/group 和实例归属。

不要直接修改旧 `bootstrap.properties` 来绕过配置。若直接点旧启动类旁边的绿色三角而没有补齐参数，可能会启用旧 dev profile 或访问原课程 Nacos 地址。

### 5.3 启动与调试

准备从脚本模式切到 IDE 模式时，先在项目根目录执行一次 `.\Stop.ps1`，释放脚本启动的应用端口。然后依次运行三个 Application 配置。

成功后分别打开：

```text
http://127.0.0.1:19201/v3/api-docs
http://127.0.0.1:19202/v3/api-docs
http://127.0.0.1:19204/v3/api-docs
```

点击 **Debug / 小虫子** 启动对应配置即可打 Java 断点，不需要手工再启动同端口的 JAR。

## 6. 在 PyCharm 配置 Python 服务

### 6.1 打开项目与选择解释器

1. PyCharm 打开项目根目录 `D:\code\python\AI_tingshu_langgraph`。
2. 在项目 Python Interpreter 设置中选择已有解释器 `.venv\Scripts\python.exe`。
3. 可以把 `python/shared`、`python/assistant`、`python/knowledge`、`python/operations`、`python/workers` 标为 Sources Root，帮助编辑器解析导入；运行时仍加载生成环境文件中的完整 `PYTHONPATH`。

### 6.2 创建四个 Python 配置

打开 **Run → Edit Configurations → + → Python**。把入口类型从 **Script path** 切换为 **Module name**。

四个配置的解释器均为项目 `.venv`，Working directory 均为项目根目录，环境文件均为 `.runtime/ide/application.env`。

| 配置名称 | Module name | Parameters |
| --- | --- | --- |
| 听见-知识 | `uvicorn` | `app.listening.service:app --app-dir D:/code/python/AI_tingshu_langgraph/python/knowledge --host 127.0.0.1 --port 29184` |
| 听见-问数 | `uvicorn` | `listening.service:app --app-dir D:/code/python/AI_tingshu_langgraph/python/operations --host 127.0.0.1 --port 29185` |
| 听见-消息工作进程 | `listening_jobs.worker` | `--project-root D:/code/python/AI_tingshu_langgraph` |
| 听见-助手入口 | `uvicorn` | `atguigu.listening.app:app --app-dir D:/code/python/AI_tingshu_langgraph/python/assistant --host 127.0.0.1 --port 29183` |

注意表中的 `:app` 属于 Uvicorn 参数，Module name 栏只有 `uvicorn`。工作进程则直接运行 `listening_jobs.worker`，不用 Uvicorn，也没有 HTTP 端口。

不需要把 `app.py` 直接作为 Python 脚本运行；定义 FastAPI 的 app 对象不等于启动 HTTP 服务。首次调试先不要加 `--reload`，这样断点、进程和端口更容易对应。

### 6.3 启动顺序

1. IDEA：用户、内容、订单三个 Java 服务。
2. PyCharm：知识服务、问数服务。
3. PyCharm：消息工作进程。
4. PyCharm：助手入口。

工作进程日志应出现消费者就绪信息，心跳记录在 `.runtime/vm/search-worker.json`；遗漏它会造成知识资料或搜索同步任务一直待处理。

Python Web 服务检查地址：

```text
http://127.0.0.1:29184/health
http://127.0.0.1:29185/health
http://127.0.0.1:29183/health
```

知识索引按请求懒加载，刚启动 `/health` 中 `index_ready=false` 不一定是启动失败；配置好模型后第一次知识查询会构建或加载索引。

## 7. 前端怎样运行

当前前端提供的是 `build:h5` 构建脚本，不是一个单独运行的 Python 页面，也没有配置 `npm run dev`。

在根目录 Terminal 执行：

```powershell
$env:NODE_OPTIONS='--max-old-space-size=512'
npm.cmd --prefix frontend/uniapp run build:h5
```

首次启动助手入口前先构建，生成 `frontend/uniapp/dist/h5`。然后访问 29183 的 `/listen/`；不需要另开 8080，也不用 IDEA/PyCharm 单独打开 `index.html`。

修改 Vue 后重新构建，浏览器按 `Ctrl+F5` 刷新。当前指南不使用前端热更新服务器。

## 8. 每天开发时照这个顺序做

**首次配置完成后：**

1. 确认 VM 与中间件已启动。
2. 按需运行 `PrepareIde.ps1`；凭据或路径没变时，无须每次重生成。
3. 确认没有后台脚本启动的同端口服务。
4. 启动 IDEA 的三个 Java 配置。
5. 启动 PyCharm 的四个 Python 配置。
6. 前端有修改则运行 `build:h5`，随后打开听书端。

**停止：** 在两个 IDE 中分别点击这些配置的 Stop。`.\Stop.ps1` 主要管理启动脚本登记且身份匹配的进程，不能指望它自动停止 IDEA 新建的 Java Application 配置。

需要回到脚本模式时，先停止 IDE 配置，再运行 `Start.ps1`。不要同时用脚本和 IDE 各启动一套应用或消息工作进程。VM 模式的停止脚本不会停止共享中间件容器。

## 9. 练习一次跨语言调试

以“保存带时间点的个人笔记”为例：

1. IDEA 在用户身份接口或内容声音接口打断点，Debug 对应 Java 服务。
2. PyCharm 在 `python/assistant/atguigu/listening/personal.py` 的保存入口打断点，Debug 助手入口。
3. 页面登录，从播放器进入“记笔记”，填写并保存，观察 Java 身份/内容校验与 Python 保存请求。
4. 若想观察异步向量或文本索引，再在 `python/shared/personal_knowledge/engine.py` 的 `process_item` 打断点，Debug 消息工作进程。

HTTP 请求结束后，消息工作进程仍可能继续处理，这是异步流程。长时间停在断点会导致浏览器或内部服务请求超时，调试时注意及时继续执行。

运行 Python 单测可在 PyCharm Terminal 执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

涉及真实服务重启的 `VerifyAll.ps1 -Live` 使用脚本登记的进程信息。需要完整联调验收时，先回到脚本模式，再按 [部署与验收](部署与验收.md) 操作。

## 10. 常见问题

| 现象 | 优先检查 |
| --- | --- |
| PowerShell 提示“意外的标记”、中文乱码，并在 `$env:PATH` 等正常代码处报语法错误 | Windows PowerShell 5.1 需要脚本使用 UTF-8 with BOM；本项目 `.ps1` 已按此保存，编辑器请保留 BOM（见 `.editorconfig`）。不要只改 PATH 行；可用 PowerShell 7 执行同一命令 |
| `Address already in use` | 后台脚本、IDE 或旧运行配置是否已占用端口；先停止自己启动的对应配置，不要批量杀掉所有 java/python |
| 连接 `192.168.200.6` 或旧 Nacos | 没加载对应 `.args`，或误启动旧入口；检查 vm profile 与本项目 namespace/group |
| `Could not resolve placeholder LISTENING_...` | IDEA 配置没有加载环境文件，或文件路径不正确 |
| MySQL / Redis / RabbitMQ 认证失败 | 不要填共享服务 root/guest 凭据；使用生成的项目专属环境文件，VM 重启后先做项目 ACL 预检 |
| `No module named atguigu / app / listening_jobs` | 解释器、Module name、PYTHONPATH、Working directory 或 `--app-dir` 不对 |
| 私人空间提示需要 VM 环境 | 检查环境文件是否加载，`LISTENING_INFRASTRUCTURE` 应为 vm；不要混用 local 数据 |
| 上传一直待处理 | 消息工作进程未启动，或工作进程没加载同一套环境变量 |
| `/listen/` 没页面 / 旧页面 | 检查 H5 是否构建，是否访问 29183，是否需要 Ctrl+F5 |
| 模型配置能看到，但调用失败 | 管理台测试对话 JSON/工具调用及向量维度；模型设置文件应指向 `.runtime/vm/model-settings.json` |
| 换 Windows 用户后模型密钥不可用 | DPAPI 密钥绑定原 Windows 用户，需要在管理台重新填写 |
| Maven 编译或 Lombok 方法报红 | JDK是否为17、Maven是否同步完成、所需模块是否安装、IDE注解处理是否启用 |

管理员账号 `admin`，密码保存在 `.runtime/admin-password`；普通听友在页面自行注册。生成环境文件不会替你创建新的用户账号。

## 11. 相关文档

- [完整部署与验收](部署与验收.md)
- [个人知识空间与云接入](个人知识空间与云服务接入.md)
- [项目结构](项目结构.md)
- JetBrains 官方：[IDEA 程序参数、VM 参数与环境变量](https://www.jetbrains.com/help/idea/program-arguments-and-environment-variables.html)、[Java Application 配置](https://www.jetbrains.com/help/idea/run-debug-configuration-java-application.html)、[PyCharm Python 配置](https://www.jetbrains.com/help/pycharm/run-debug-configuration-python.html)。菜单显示会随版本或语言变化，以字段名称为准。
