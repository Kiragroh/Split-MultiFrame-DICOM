# Split-MultiFrame-DICOM
![Banner](banner.png)
## Introduction

**Split-MultiFrame-DICOM** is a small toolset to split Enhanced Multi-Frame DICOM files into individual single-frame DICOM files.

The **preferred method** is the included **Python script** because it is simpler to set up and does not require Java or `dcm4che`. This is especially useful for users of **Eclipse TPS by Varian (<= v18)**, which does not support Multi-Frame DICOM files.

A **dcm4che / emf2sf** workflow is still included as an alternative fallback.

## Disclaimer

This tool is provided **without clinical recommendation**. It is **not intended for clinical use** and should only be used for **testing and research purposes**. Use this tool at your own risk.

---

## Quick Start

```powershell
python -m pip install -U pip
python -m pip install -r requirements.txt
python python_split.py
```

For compressed DICOM files:
```powershell
python -m pip install -U "pylibjpeg[all]"
```

---

## Preferred Method: Python

### Prerequisites

- Windows operating system
- Python 3 installed
- The files `python_split.py` and `requirements.txt`

### 1. Install Python

1. Download Python for Windows from the official Python website:  
   https://www.python.org/downloads/windows/
2. Start the installer
3. **Important:** Enable **"Add Python to PATH"** during installation
4. Finish the installation

### 2. Verify Python Installation

Open **PowerShell** or **Command Prompt** and run:

```powershell
python --version
python -m pip --version
```

If both commands work, Python is installed correctly.

### 3. Download This Repository

Download or clone this repository and place the following files into your working folder:

- `python_split.py`
- `requirements.txt`

You can also place your Enhanced Multi-Frame DICOM file directly into the same folder.

### 4. Install the Required Python Packages

Open PowerShell or Command Prompt in the repository folder and run:

```powershell
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 5. Run the Python Script

If your input file is already in the same folder and named for example `multi.dcm`, run:

```powershell
python python_split.py
```

Or provide the file explicitly:

```powershell
python python_split.py multi.dcm
```

You can also pass a full path:

```powershell
python python_split.py "C:\path\to\your\enhanced_multiframe.dcm"
```

### 6. Output

The script creates a new output folder next to the input file:

```
<input_filename>_split
```

**Example:**
```
multi_split
```

The folder will contain the generated single-frame DICOM files:

```
IM_0001.dcm
IM_0002.dcm
IM_0003.dcm
...
```

### 7. Optional: Support for Compressed DICOM Pixel Data

If the script fails because the source DICOM uses compressed pixel data, install an additional decoder package:

```powershell
python -m pip install -U "pylibjpeg[all]"
```

Then run the script again.

---

## Alternative Method: dcm4che / emf2sf

If you prefer the Java-based route, you can still use `dcm4che` and `emf2sf`.

### Prerequisites

- Windows operating system
- dcm4che 5.32.0 downloaded and extracted
- Java 17 installed
- Basic knowledge of batch scripts

### 1. Install dcm4che

1. Download the dcm4che toolset from:  
   https://dcm4che.org/maven2/org/dcm4che/dcm4che-assembly/5.32.0/
2. Extract the archive to a directory, for example:  
   `C:\dcm4che`

### 2. Install Java 17

1. Install Java 17
2. Verify Java is available in the terminal:
   ```powershell
   java -version
   ```

### 3. Use the Batch Script

Use the provided `convert_multiframe.bat` workflow if you want to process multiple files recursively with `emf2sf`.

---

## Extra Tools

### GUI-DICOMorganizer

Can be used to reorganize the resulting files by patient, date, series number, or series description.

**Usage:**
1. Download the `extra_GUI-DICOMorganizer` folder from this repository
2. Start the `.exe` file

### Custom DICOM Receiver

Can be used if you want automatic receiving, storing, and conversion of incoming data.

**Usage:**
1. Install Python and the packages required by the receiver script
2. Start the file `DICOM receiver_MRMULTI_parallel.py`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python` is not recognized | Python is either not installed correctly or was not added to PATH during installation. Try `python --version`. If that fails, reinstall Python and make sure "Add Python to PATH" is checked. |
| Packages cannot be installed | Run: `python -m pip install -U pip` followed by `python -m pip install -r requirements.txt` |
| Compressed pixel data cannot be read | Install the optional decoder: `python -m pip install -U "pylibjpeg[all]"` |
| Eclipse or another importer reports missing geometry tags | The source Enhanced DICOM may store geometry differently than expected. Validate the generated tags such as: `PixelSpacing`, `ImagePositionPatient`, `ImageOrientationPatient`, `SliceThickness` |
| Java / dcm4che issues | - Check that Java 17 is installed<br>- Check that `java -version` works<br>- Check the path to the `dcm4che\bin` folder |

---

## Support and Contributions

If you have questions or issues, please **create an issue** in this repository.

**Contributions are welcome.** Fork the repository and create a pull request with your improvements.

---

## License

This project is licensed under the **MIT License**.
