# 轻量提交前检查：语言配置、文档索引/语言矩阵、截图画廊生成物。
# 完整构建与实机验收仍走 check.ps1 / CI。
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
python (Join-Path $repo "src\tools\precommit.py")
exit $LASTEXITCODE
