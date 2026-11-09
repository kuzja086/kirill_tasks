<#
.SYNOPSIS
    Собирает архив навыка и создаёт новую версию функции в Yandex Cloud.

.DESCRIPTION
    В архив попадают только файлы рантайма: handler.py, alice_skill/,
    requirements.txt. Тесты, README и sql/ в функцию не загружаются.
    Переменные окружения берутся из файла .env (см. .env.example).

.EXAMPLE
    ./deploy.ps1 -FunctionId d4e********** -BuildOnly

.EXAMPLE
    ./deploy.ps1 -FunctionId d4e********** -EnvFile .env
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FunctionId,

    [string]$Entrypoint = 'handler.handler',
    [string]$Runtime = 'python312',
    [string]$EnvFile = '.env',
    [string]$BuildDirectory = '.build',
    [string]$Memory = '128m',
    [string]$ExecutionTimeout = '5s',
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$buildRoot = Join-Path $projectRoot $BuildDirectory
$archivePath = Join-Path $buildRoot 'skill.zip'

Write-Host "Сборка архива: $archivePath"
if (Test-Path -LiteralPath $buildRoot) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

# В архив попадают только файлы рантайма; кэш интерпретатора исключается.
$runtimeFiles = @()
foreach ($fileName in @('handler.py', 'requirements.txt')) {
    $runtimeFiles += Get-Item -LiteralPath (Join-Path $projectRoot $fileName)
}
foreach ($directoryName in @('alice_skill')) {
    $runtimeFiles += Get-ChildItem -LiteralPath (Join-Path $projectRoot $directoryName) -Recurse -File |
        Where-Object { $_.Extension -ne '.pyc' -and $_.FullName -notmatch '\\__pycache__\\' }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::Open(
    $archivePath,
    [System.IO.Compression.ZipArchiveMode]::Create
)
try {
    foreach ($file in $runtimeFiles) {
        $entryName = $file.FullName.Substring($projectRoot.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file.FullName,
            $entryName
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
}
Write-Host "Файлов в архиве: $($runtimeFiles.Count)"

if ($BuildOnly) {
    Write-Host 'Архив собран, версия функции не создавалась (-BuildOnly).'
    return
}

$envPath = Join-Path $projectRoot $EnvFile
if (-not (Test-Path -LiteralPath $envPath)) {
    throw "Не найден файл с переменными окружения: $envPath"
}

$environmentLines = Get-Content -LiteralPath $envPath |
    Where-Object { $_ -match '^\s*[^#\s][^=]*=' } |
    ForEach-Object { $_.Trim() }
$environment = $environmentLines -join ','

Write-Host "Создание версии функции $FunctionId ($Runtime, entrypoint $Entrypoint)"
yc serverless function version create `
    --function-id $FunctionId `
    --runtime $Runtime `
    --entrypoint $Entrypoint `
    --memory $Memory `
    --execution-timeout $ExecutionTimeout `
    --source-path $archivePath `
    --environment $environment
