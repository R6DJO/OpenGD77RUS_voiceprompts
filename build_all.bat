@echo OFF
FOR %%l IN (russian) DO (
  CALL :ProcessVoicePrompts "languages\%%l"
)

pause

EXIT /B %ERRORLEVEL%


@REM first argument is the VP directory
@REM note: alias is undefined when it's set #
:ProcessVoicePrompts
pushd %~1%
FOR %%x IN (1.25:slow 1.5:# 1.75:normal 2.0:# 2.25:fast 2.5:#) DO (
  CALL :BuildVoicesAtSpeed "%%x"
)
popd
GOTO:EOF

@REM first argument is speed:alias pair
:BuildVoicesAtSpeed
set "PAIR=%~1%"
FOR /F "tokens=1,2 delims=:" %%a IN ("%PAIR%") DO (
  set TEMPO=%%a
  set ALIAS=%%b
  python ..\..\GD77VoicePromptsBuilder.py -c config.csv -t %TEMPO% -A "%ALIAS:#=%"
)
GOTO:EOF
