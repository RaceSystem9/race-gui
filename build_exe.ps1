$venvPath = Join-Path $PSScriptRoot '.venv'
if (-not (Test-Path $venvPath)) {
    py -3 -m venv $venvPath
}
& "$venvPath\Scripts\python" -m pip install --upgrade pip
& "$venvPath\Scripts\python" -m pip install -r .\requirements.txt
& "$venvPath\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name RaceControl --distpath .\dist --workpath .\build --add-data "src/config;src/config" .\main.py
