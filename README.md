# Split-MultiFrame-DICOM

## Introduction
**Split-MultiFrame-DICOM** is a tool to split Enhanced Multi-Frame DICOM files into individual DICOM files. This is especially useful for users of the Eclipse TPS by Varian (<= v.18), which does not support Multi-Frame DICOM files. The provided batch file is necessary because the default command line syntax for `dcm4che` processes one file at a time (see the [README](https://github.com/dcm4che/dcm4che/blob/master/dcm4che-tool/dcm4che-tool-emf2sf/README.md) for more details).

## Disclaimer
This tool is provided without clinical recommendation. It is not intended for clinical use and should only be used for testing and research purposes. Use this tool at your own risk.

## Prerequisites
- Windows operating system
- [dcm4che 5.32.0](https://sourceforge.net/projects/dcm4che/files/dcm4che3/5.32.0/) downloaded and installed
- Java 17 installed (tested with Java 17)
- Basic knowledge of using batch scripts

## Step-by-Step Guide

### 1. Install dcm4che
1. Download the `dcm4che` toolset from [this link](https://sourceforge.net/projects/dcm4che/files/dcm4che3/5.32.0/).
2. Extract the downloaded archive to a directory, e.g., `C:\dcm4che`.

### 2. Install Java 17
1. Download Java 17 from the official [Oracle website](https://www.oracle.com/java/technologies/javase/jdk17-archive-downloads.html).
2. Install Java 17 and add the Java binary path (e.g., `C:\Program Files\Java\jdk-17\bin`) to the PATH environment variable to ensure Java commands are available from the command prompt.

### 3. Create the Batch Script
Create a batch file (`convert_multiframe.bat`) with the following content:

```batch
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
```
*Note: I hardcoded the path to the dcm4che bin folder (set "EMF2SF_PATH=C:\dcm4che\bin") in the batch file because there could be problems with environment variable settings. You have to change the path if you want to store the bin folder elsewhere.

### 4. Run the Batch Script
Place the convert_multiframe.bat file in the directory containing the DICOM files to be converted.
Double-click the batch file to run the script. The script will recursively search all subdirectories and convert all found Multi-Frame DICOM files into individual DICOM files.
After the conversion is complete, you will find the individual DICOM files in the newly created output_YYYY-MM-DD_HH-MM-SS directory in the same directory as the script.

### 5. Extra
- Organize DICOM Files with GUI-DICOMorganizer: To make the resulting files more readable, you can use the **extra_GUI-DICOMorganizer** tool to sort the files by Patient, Acquisition Date, Series Number, and Series Description.
- Use a custom DICOM-Receiver that handles all your incoming data and converts when necessary (advantage: you can specify more easily who and where the DICOM data is stored.

#### Using GUI-DICOMorganizer
1. Download the `extra_GUI-DICOMorganizer` folder from this repository.
2. Open the `.exe` file. The rest should be self-explanatory.
### Troubleshooting
The script cannot find the emf2sf command: Check the path to dcm4che\bin and ensure that the emf2sf command is indeed present in this directory.
No files are converted: Ensure that the Multi-Frame DICOM files are in the same directory or subdirectories where the script is executed.
Support and Contributions
If you have questions or issues, please create an issue in this repository. Contributions are also welcome! Fork the repository and create a pull request with your improvements.

#### Using Custom-DICOM-Receiver
- install python 3.11 and packages mentioned in the file 'DICOM receiver_MRMULTI_parallel.py'
- start the file 'DICOM receiver_MRMULTI_parallel.py'

### License
This project is licensed under the MIT License.
