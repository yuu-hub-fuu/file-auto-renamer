@echo off
setlocal

for /f "delims=" %%i in ('python -c "import pathlib, site; print(pathlib.Path(site.getusersitepackages()).parent / 'Scripts' / 'pyinstaller.exe')"') do set "PYI=%%i"

if not exist "%PYI%" (
    echo 找不到 pyinstaller.exe，请先执行: python -m pip install pyinstaller
    exit /b 1
)

"%PYI%" --clean --onefile --windowed --runtime-tmpdir . --name 自动改名器 .\rename_tool.pyw
