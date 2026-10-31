# 运行组合

首个配置为 [adrl.example.yaml](adrl.example.yaml)，复制为 `adrl.local.yaml` 后绑定本机资源与镜像。实际操作统一见 [ADRL](../cases/adrl/README.md)。local YAML 不进入 Git。

当前 schema 仅覆盖 ADRL，不提前定义所有后端字段。输出相对 profile 位置解析，源资源通过工作区或用户级资源映射定位。PC/RoboPi 共用仿真组合，flight 的执行位置由对应控制入口选择。
