@echo off
rem Harness Kit isolated launcher: runs Claude Code with this project's own global config.
rem Settings and hooks in the user profile .claude folder are NOT applied.
rem   claude-isolated.cmd                              start Claude Code
rem   claude-isolated.cmd py scripts\execute.py 0-mvp   run a harness phase
rem setlocal: CLAUDE_CONFIG_DIR and cd are undone when this script ends,
rem so the calling cmd window does not stay in the isolated environment.
setlocal
set "CLAUDE_CONFIG_DIR=C:\lab\2nd_NGV\.claude-home"
cd /d "%~dp0"
rem Run the arguments via goto, not inside an if/else block: cmd expands the
rem argument list before parsing, so empty or parenthesized arguments break it.
if "%~1"=="" goto interactive
call %*
exit /b %ERRORLEVEL%
:interactive
call claude
exit /b %ERRORLEVEL%
