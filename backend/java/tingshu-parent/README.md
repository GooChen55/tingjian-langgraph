# 听见 · Java 后端

Java 17、Spring Boot、MyBatis-Plus、MySQL、Redis 与 MongoDB 构成业务后端。当前运行用户、内容、订单三个服务，负责确定性业务规则与事务，AI 服务通过认证接口访问。

| 服务 | 端口 | 职责 |
| --- | --- | --- |
| service-user | 19201 | 听友账号、独立管理会话、RBAC、会员与收听进度 |
| service-album | 19202 | 公开分类、专辑和章节；使用 local-listening 构建配置 |
| service-order | 19204 | 订单、售后确认与审核、模拟支付退款、持久化任务和事件 |

common、model、service-client 为公共模块。其他保留模块不由默认启动脚本运行。

## 构建和运行

推荐使用项目根目录的 Start.ps1，自动编排独立数据库、配置和就绪检查。修改 Java 源码前先运行 Stop.ps1，避免 Windows 锁定 JAR；重新启动时不加 SkipBuild。

在本目录手动构建选定服务：

```powershell
mvn -pl 'service/service-user,service/service-album,service/service-order' -am -Plocal-listening package -DskipTests
```

本地支付与退款不连接真实支付渠道，不扣款、不授予付费播放权益。业务身份由 Java 校验，模型不拥有交易和审批工具。SQL 迁移由项目脚本管理，已执行文件不可修改。

完整启动、验收和限制见 [项目首页](../../../README.md)，交易设计见 [支付退款设计](../../../docs/支付退款设计与接口.md)，归属信息见 [来源与第三方说明](../../../docs/来源与第三方说明.md)。
