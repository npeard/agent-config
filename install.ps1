# Thin shim. The installer itself is install.py; see docs in that file.
$ErrorActionPreference = 'Stop'
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-Command pixi -ErrorAction SilentlyContinue) {
    & pixi run --manifest-path "$RepoDir\pixi.toml" -e dev python "$RepoDir\install.py" @args
    exit $LASTEXITCODE
}
Write-Error "pixi is not on PATH. This repo is pixi-managed; install pixi from https://pixi.sh and re-run."
exit 1
