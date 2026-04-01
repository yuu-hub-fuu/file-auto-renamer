@echo off
setlocal

where pythonw >nul 2>nul
if %errorlevel%==0 (
    pythonw "%~dp0rename_tool.pyw" %*
) else (
    python "%~dp0rename_tool.pyw" %*
)
