# GitLab 开发与 GitHub 发布

GitLab 是主开发仓库，`origin` 保持指向
`git@ipads.sjtu.edu.cn:robot-sig/leuav.git`。GitHub 使用独立的 `github`
remote，仅在需要发布时手动同步 `main`；不自动同步开发分支或全部标签。
日常分支、合并和问题处理仍在 GitLab 完成。

## 首次接入

创建 GitHub 目标仓库时保持空仓库，不额外初始化 README 或其他提交。
用实际地址添加 remote：

```sh
git remote add github git@github.com:<账号或组织>/leuav.git
git remote -v
```

地址中的账号、组织和仓库名须替换为实际值。当前尚未配置 GitHub 地址。

## 手动同步 main

在本地修改已按正常开发流程提交、GitLab 的 main 已更新后执行：

```sh
git fetch origin
git push github refs/remotes/origin/main:refs/heads/main
```

显式从 GitLab 的 main 推送，避免把当前开发分支误发为 GitHub main。
未提交文件不会被同步。推送失败时保留错误并检查原因，不使用强推覆盖
GitHub 独有提交，也不使用 `--mirror` 或 `--all`。

首次推送后，在 GitHub 仓库确认默认分支为 main 且 Actions 已启用。
GitHub 上若需修改内容，应先回到 GitLab 开发并合并，再重新同步，避免分叉。

## CI 与 Pages

[CI 配置](../.github/workflows/ci.yml) 在 GitHub main 推送、目标为 main 的 PR
以及手动触发时安装项目并运行现有离线测试。安装不启用 AirSim 可选依赖。
这些检查不包含 Docker 镜像构建、GPU/GUI、真实 ROS/DDS、设备或飞行验收。

网站源码和构建入口尚未建立，当前没有 Pages 部署任务，也未启用线上网站。
后续接入应用可视化时，使用同一次 main 推送触发构建，CI 成功后发布选定的
静态产物；GitHub 的 Settings → Pages → Source 选择 GitHub Actions。
发布输入明确列举网站所需文档和资源，不上传整个工作区、本机配置或 artifacts。
操作文档继续引用仓库现有唯一入口，网站不另维护一套命令。

GitHub 在线 CI、远端同步及 Pages 发布结果须在实际运行后确认，本地测试不能
代替远端验收。
