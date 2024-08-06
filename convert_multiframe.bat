@echo off
REM Find and process all enhanced DICOM files in subdirectories

REM Get the directory of the batch file
set "BATCH_DIR=%~dp0"

REM Create a timestamp for the output directory
for /f "tokens=1-6 delims=:. " %%i in ("%date% %time%") do set "datetime=%%i-%%j-%%k_%%l-%%m-%%n"
set "OUTPUT_DIR=%BATCH_DIR%\output_%datetime%"

REM Create the output directory
mkdir "%OUTPUT_DIR%"

REM Path to emf2sf command (adjust this path to the actual location of emf2sf)
set "EMF2SF_PATH=C:\dcm4che\bin"

REM Loop through all directories and subdirectories
for /r %%d in (.) do (
    REM Skip directories that contain "output" in the path
    echo %%d | find /i "output" >nul
    if errorlevel 1 (
        pushd %%d
        REM Check for all files in the directory
        for %%f in (*.*) do (
            REM Execute the emf2sf command for each found file
            echo Processing file %%f in directory %%d
            "%EMF2SF_PATH%\emf2sf" --out-dir "%OUTPUT_DIR%" "%%f"
        )
        popd
    )
)

echo Conversion complete! All files are stored in %OUTPUT_DIR%
pause
