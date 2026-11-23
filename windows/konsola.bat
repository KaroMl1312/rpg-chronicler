@echo off
rem Konsola RPG Chronicles: komendy rpg-chronicler i ffmpeg z folderu programu.
chcp 65001 >nul
set "RPG_ROOT=%~dp0.."
set "PATH=%RPG_ROOT%\.venv\Scripts;%RPG_ROOT%\ffmpeg\bin;%PATH%"
set PYTHONUTF8=1
cd /d "%RPG_ROOT%"
title RPG Chronicles
type "%~dp0pomoc.txt"
