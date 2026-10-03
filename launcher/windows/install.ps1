# 仮想環境と依存を準備し、デスクトップにランチャーのショートカットを置く。依存を更新したときも再実行する。
# ショートカットは venv の python.exe を直接起動する。バッチを挟むと Ctrl+C の後に
# 「バッチ ジョブを終了しますか (Y/N)?」が出て、停止後にウインドウが自動で閉じなくなるため。
$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Venv = Join-Path $Repo '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'
$ShortcutName = 'html-preview-hub.lnk'

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "コマンドが失敗しました: $File $($Arguments -join ' ')" }
}

Set-Location $Repo
if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        Invoke-Checked 'py' @('-3', '-m', 'venv', $Venv)
    } else {
        Invoke-Checked 'python' @('-m', 'venv', $Venv)
    }
}
Invoke-Checked $Python @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
Invoke-Checked $Python @('-m', 'pip', 'install', '--quiet', '-r', 'requirements.txt')

# OneDrive でデスクトップがリダイレクトされていても正しい場所を返す
$Shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) $ShortcutName
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($Shortcut)
$link.TargetPath = $Python
$link.Arguments = '-m hph --pause-on-exit 3'
$link.WorkingDirectory = $Repo
$link.Description = 'html-preview-hub を起動する'
$link.Save()
Write-Host "デスクトップに「${ShortcutName}」を作成しました。ダブルクリックで起動します。"
