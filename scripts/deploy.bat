@echo off
:: deploy.bat – Deploy ThreadMeister Extended to the Fusion 360 AddIns folder
::
:: Usage:
::   deploy.bat          deploy to Fusion 360 AddIns folder
::   deploy.bat /preview preview what would be copied (dry run)

setlocal

:: Source is the project root (one level up from this scripts\ folder)
pushd "%~dp0.."
set "SOURCE=%CD%\"
popd

set "TARGET=%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\ThreadMeisterExtended"

:: Check for dry-run flag
set DRYRUN=0
if /i "%1"=="/preview" set DRYRUN=1

echo.
echo ThreadMeister Extended Deploy
echo   Source : %SOURCE%
echo   Target : %TARGET%
echo.

if %DRYRUN%==1 (
    echo [DRY RUN - no files will be changed]
    echo.
)

:: Create target folder if it doesn't exist
if not exist "%TARGET%\" (
    if %DRYRUN%==0 mkdir "%TARGET%"
    echo   Created  target folder
)

:: ── Copy Python modules and manifests ────────────────────────────────────────
call :CleanupOldNames
call :CopyFile "ThreadMeisterExtended.py"
call :CopyCore
call :CopyFile "ThreadMeisterExtended.manifest"
call :CopyFile "manifest.json"
call :CopyFile "License.txt"
call :CopyFile "Readme.md"

:: ── config.ini: only copy if not already present (preserve custom settings) ──
if exist "%TARGET%\config.ini" (
    echo   Skipped  config.ini  ^(already exists - custom settings preserved^)
) else (
    if exist "%SOURCE%config.ini" (
        if %DRYRUN%==0 xcopy /y /q "%SOURCE%config.ini" "%TARGET%\" >nul
        echo   Copied   config.ini  ^(first deploy^)
    )
)

:: ── Copy icons folder ─────────────────────────────────────────────────────────
if exist "%SOURCE%resources\icons\" (
    if %DRYRUN%==0 (
        if not exist "%TARGET%\resources\icons\" mkdir "%TARGET%\resources\icons"
        xcopy /y /q /e "%SOURCE%resources\icons\*" "%TARGET%\resources\icons\" >nul
    )
    echo   Copied   resources\icons\
) else (
    echo   MISSING  resources\icons\
)

:: ── Copy help file ──────────────────────────────────────────────────────────
if exist "%SOURCE%resources\help.html" (
    if %DRYRUN%==0 (
        if not exist "%TARGET%\resources\" mkdir "%TARGET%\resources"
        xcopy /y /q "%SOURCE%resources\help.html" "%TARGET%\resources\" >nul
    )
    echo   Copied   resources\help.html
)

echo.
if %DRYRUN%==1 (
    echo Dry run complete. No files were changed.
) else (
    echo Done. Reload the add-in in Fusion 360:
    echo   Scripts and Add-Ins ^> ThreadMeister Extended ^> Run
)
echo.
goto :eof

:: ── Helper: remove the pre-rename entry point ────────────────────
:: Fusion matches <folder>.manifest, so leaving ThreadMeister.manifest behind
:: next to ThreadMeisterExtended.manifest gives the folder two manifests.
:CleanupOldNames
for %%F in (ThreadMeister.py ThreadMeister.manifest ThreadMeister.png) do (
    if exist "%TARGET%\%%F" (
        if %DRYRUN%==0 del /q "%TARGET%\%%F"
        echo   Removed  %%F  ^(renamed to ThreadMeisterExtended.*^)
    )
)
goto :eof

:: ── Helper: copy a single file ────────────────────────────────────────────────
:CopyFile
if not exist "%SOURCE%%~1" (
    echo   MISSING  %~1
    goto :eof
)
if %DRYRUN%==0 xcopy /y /q "%SOURCE%%~1" "%TARGET%\" >nul
echo   Copied   %~1
goto :eof

:: ── Helper: copy every module in core\ ──────────────────────────
:CopyCore
if not exist "%SOURCE%core\" (
    echo   MISSING  core
    goto :eof
)
if %DRYRUN%==0 (
    if not exist "%TARGET%\core\" mkdir "%TARGET%\core"
    xcopy /y /q "%SOURCE%core\*.py" "%TARGET%\core\" >nul
)
echo   Copied   core\*.py
goto :eof
